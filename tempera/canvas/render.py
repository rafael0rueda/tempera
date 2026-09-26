# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drawing the image and everything over it."""

from __future__ import annotations

import math
from functools import cache

import cairo
from gi.repository import Adw, Gdk, Graphene, Gsk, Gtk

from ..interface_size import scaled
from ..tools import draw_marquee
from ..tools.base import draw_outline_marquee
from .floating import TEXT_PADDING
from .pointer import HANDLE_RADIUS, HANDLE_RING, HANDLE_SIZE
from .tiles import ImageTiles, surface_texture

CHECKER_SIZE = 8
# Below this zoom the image is shrunk, where smoothing reads better than dropped
# pixels; at or above it every image pixel shows as a crisp square.
SMOOTH_ZOOM_BELOW = 1.0


@cache
def _checker_texture() -> Gdk.Texture:
    """One 2 × 2 tile of the checkerboard, repeated under the image."""
    size = CHECKER_SIZE * 2
    tile = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(tile)
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    cr.set_source_rgb(0.9, 0.9, 0.9)
    cr.rectangle(CHECKER_SIZE, 0, CHECKER_SIZE, CHECKER_SIZE)
    cr.rectangle(0, CHECKER_SIZE, CHECKER_SIZE, CHECKER_SIZE)
    cr.fill()
    tile.flush()
    return surface_texture(tile, 0, 0, size, size)


def _rect(x: float, y: float, width: float, height: float) -> Graphene.Rect:
    return Graphene.Rect().init(x, y, width, height)


class RenderMixin:
    """Draws the image, a tool's preview, and the outlines and grips over them.

    The image goes to the GPU as tiles of texture, which it scales to the zoom
    by itself, and only the tiles a change touched are uploaded again. What is
    drawn over it with cairo covers just the part of the screen it takes up.
    """

    def _init_render(self) -> None:
        self._tiles = ImageTiles()

    def _damage(self, x1: float, y1: float, x2: float, y2: float) -> None:
        """A tool painted within these extents; their tiles need uploading again."""
        # Antialiasing reaches into the pixels the extents only partly cover.
        left, top = math.floor(x1) - 1, math.floor(y1) - 1
        self._tiles.invalidate((left, top, math.ceil(x2) + 1 - left, math.ceil(y2) + 1 - top))

    def _visible_area(self) -> tuple[float, float, float, float]:
        """The part of the canvas in view, in its own coordinates."""
        width, height = self._content_size
        scrolled = self.get_ancestor(Gtk.ScrolledWindow)
        if scrolled is not None:
            found, bounds = scrolled.compute_bounds(self)
            if found:
                left, top = max(0.0, bounds.get_x()), max(0.0, bounds.get_y())
                right = min(float(width), bounds.get_x() + bounds.get_width())
                bottom = min(float(height), bounds.get_y() + bounds.get_height())
                return left, top, max(0.0, right - left), max(0.0, bottom - top)
        return 0.0, 0.0, float(width), float(height)

    def _pixel_aligner(self):
        """A function moving a point on the canvas onto the nearest corner of a device pixel.

        Device pixels are counted from the corner of the window's surface, which
        with a fractional scale, or a scroll part way through a pixel, the
        canvas's own corner need not sit on.
        """
        native = self.get_native()
        surface = native.get_surface() if native is not None else None
        if surface is None:
            return lambda x, y: (round(x), round(y))
        scale = surface.get_scale()
        found, origin = self.compute_point(native, Graphene.Point().init(0, 0))
        offset_x, offset_y = native.get_surface_transform()
        if not found:
            return lambda x, y: (round(x), round(y))
        origin_x, origin_y = origin.x + offset_x, origin.y + offset_y
        return lambda x, y: (
            round((x + origin_x) * scale) / scale - origin_x,
            round((y + origin_y) * scale) / scale - origin_y,
        )

    def _render(self, snapshot: Gtk.Snapshot) -> None:
        document, zoom = self._document, self.zoom
        visible = self._visible_area()
        view_x, view_y, view_width, view_height = visible
        if view_width <= 0 or view_height <= 0:
            return

        # The part of the image in view, in image pixels.
        left, top = view_x / zoom, view_y / zoom
        right = min(float(document.width), (view_x + view_width) / zoom)
        bottom = min(float(document.height), (view_y + view_height) / zoom)
        if right > left and bottom > top:
            # Laid out on screen rather than in image pixels under a scale: see
            # ImageTiles.snapshot().
            checker = CHECKER_SIZE * 2 * zoom
            snapshot.push_repeat(
                _rect(left * zoom, top * zoom, (right - left) * zoom, (bottom - top) * zoom),
                _rect(0, 0, checker, checker),
            )
            snapshot.append_scaled_texture(
                _checker_texture(), Gsk.ScalingFilter.NEAREST, _rect(0, 0, checker, checker)
            )
            snapshot.pop()
            scaling = (
                Gsk.ScalingFilter.NEAREST if zoom >= SMOOTH_ZOOM_BELOW else Gsk.ScalingFilter.TRILINEAR
            )
            self._tiles.snapshot(
                snapshot,
                document.surface,
                (left, top, right - left, bottom - top),
                zoom,
                scaling,
                self._pixel_aligner(),
            )

        accent = self._accent()
        self._snapshot_overlays(snapshot, visible, accent)
        self._snapshot_handles(snapshot, accent)

    def _snapshot_overlays(
        self, snapshot: Gtk.Snapshot, visible: tuple[float, float, float, float], accent: Gdk.RGBA
    ) -> None:
        """Draw the previews and outlines with cairo, over no more than they cover.

        They are recorded first, and the recording played back into a cairo
        node just the size of what it holds: most of the time that is nothing,
        or a small box, rather than the whole view.
        """
        recording = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
        cr = cairo.Context(recording)
        cr.rectangle(*visible)
        cr.clip()
        self._draw_overlays(cr, accent)
        x, y, width, height = recording.ink_extents()
        if width <= 0 or height <= 0:
            return
        left, top = math.floor(x), math.floor(y)
        bounds = _rect(left, top, math.ceil(x + width) - left, math.ceil(y + height) - top)
        cr = snapshot.append_cairo(bounds)
        cr.set_source_surface(recording, 0, 0)
        cr.paint()

    def _draw_overlays(self, cr: cairo.Context, accent: Gdk.RGBA) -> None:
        image_width, image_height = self._document.width, self._document.height

        # Everything below is laid out in image pixels; this one transform is
        # what makes it appear at the current zoom level on screen.
        cr.save()
        cr.scale(self.zoom, self.zoom)

        context = self._drag_context
        if context is None and self.active_tool.in_progress:
            context = self._make_context(self._shape_button)
        if context is not None:
            cr.save()
            cr.rectangle(0, 0, image_width, image_height)
            cr.clip()
            self.active_tool.draw_preview(cr, context)
            cr.restore()

        if self.pixel_grid_visible:
            self._draw_pixel_grid(cr, image_width, image_height)

        frame = self.active_tool.frame() if self.active_tool.adjustable else None
        if frame is not None and frame[2] >= 1 and frame[3] >= 1:
            self._draw_dashed_rect(cr, accent, *frame)
        if self._resize_size is not None:
            self._draw_resize_preview(cr, accent, image_width, image_height)
        if self._paste is not None:
            self._draw_paste(cr, accent, image_width, image_height)
        if self._text is not None:
            self._draw_text(cr, accent, image_width, image_height)
        if self._selection is not None:
            if self._selection.outline is not None:
                cr.save()
                cr.rectangle(0, 0, image_width, image_height)
                cr.clip()
                draw_outline_marquee(cr, self._selection.outline)
                cr.restore()
            else:
                draw_marquee(cr, *self._selection.rect)
        cr.restore()

    def _draw_pixel_grid(self, cr: cairo.Context, image_width: int, image_height: int) -> None:
        """A line between every two pixels, drawn on screen pixels so it stays one pixel thin."""
        cr.save()
        cr.rectangle(0, 0, image_width, image_height)
        cr.clip()
        # Only the lines in view: a large image has far more than the screen shows.
        left, top, right, bottom = cr.clip_extents()
        zoom = self.zoom
        cr.scale(1 / zoom, 1 / zoom)
        for x in range(max(1, int(left)), min(image_width, int(right) + 1)):
            cr.move_to(round(x * zoom) + 0.5, top * zoom)
            cr.line_to(round(x * zoom) + 0.5, bottom * zoom)
        for y in range(max(1, int(top)), min(image_height, int(bottom) + 1)):
            cr.move_to(left * zoom, round(y * zoom) + 0.5)
            cr.line_to(right * zoom, round(y * zoom) + 0.5)
        cr.set_line_width(1)
        # A half-see-through grey darkens light pixels and lightens dark ones,
        # so the lines show on both without hiding the colours between them.
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.45)
        cr.stroke()
        cr.restore()

    @staticmethod
    def _accent() -> Gdk.RGBA:
        return Adw.StyleManager.get_default().get_accent_color_rgba()

    @staticmethod
    def _draw_dashed_rect(
        cr: cairo.Context, accent: Gdk.RGBA, x: float, y: float, width: float, height: float
    ) -> None:
        cr.save()
        cr.set_source_rgba(accent.red, accent.green, accent.blue, 1.0)
        cr.set_line_width(1)
        cr.set_dash([4, 3])
        cr.rectangle(x + 0.5, y + 0.5, width - 1, height - 1)
        cr.stroke()
        cr.restore()

    @staticmethod
    def _draw_overhang(
        cr: cairo.Context,
        x: float,
        y: float,
        width: float,
        height: float,
        image_width: int,
        image_height: int,
    ) -> None:
        """Fill the part of a rectangle that hangs off the image with white.

        That is the colour the canvas grows with, so the preview of a paste or a
        text box matches what committing it produces.
        """
        cr.save()
        cr.rectangle(x, y, width, height)
        cr.clip()
        # Even-odd over both rectangles leaves exactly the overhanging part.
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(x, y, width, height)
        cr.rectangle(0, 0, image_width, image_height)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()
        cr.restore()

    def _draw_resize_preview(
        self, cr: cairo.Context, accent: Gdk.RGBA, image_width: int, image_height: int
    ) -> None:
        width, height = self._resize_size
        cr.save()

        # Even-odd over both rectangles tints exactly what is being added or cropped.
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(0, 0, image_width, image_height)
        cr.rectangle(0, 0, width, height)
        cr.set_source_rgba(accent.red, accent.green, accent.blue, 0.25)
        cr.fill()
        cr.restore()

        self._draw_dashed_rect(cr, accent, 0, 0, width, height)

    def _draw_paste(
        self, cr: cairo.Context, accent: Gdk.RGBA, image_width: int, image_height: int
    ) -> None:
        paste = self._paste
        if paste.source is not None:
            # The pixels are on their way out of here; show the white they leave behind.
            cr.save()
            cr.set_source_rgb(1, 1, 1)
            if paste.source_mask is None:
                cr.rectangle(*paste.source)
                cr.fill()
            else:
                cr.mask_surface(paste.source_mask, paste.source[0], paste.source[1])
            cr.restore()

        self._draw_overhang(
            cr, paste.x, paste.y, paste.width, paste.height, image_width, image_height
        )

        cr.save()
        cr.rectangle(paste.x, paste.y, paste.width, paste.height)
        cr.clip()
        cr.translate(paste.x, paste.y)
        cr.scale(paste.scale_x, paste.scale_y)
        cr.set_source_surface(paste.surface, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()
        cr.restore()

        self._draw_dashed_rect(cr, accent, paste.x, paste.y, paste.width, paste.height)

    def _draw_text(
        self, cr: cairo.Context, accent: Gdk.RGBA, image_width: int, image_height: int
    ) -> None:
        text = self._text
        width, height = text.size
        if width > 0 and height > 0:
            self._draw_overhang(cr, text.x, text.y, width, height, image_width, image_height)
            text.render(cr)

        # The outline sits outside the glyphs, and outside what gets rasterised.
        self._draw_dashed_rect(
            cr,
            accent,
            text.x - TEXT_PADDING,
            text.y - TEXT_PADDING,
            width + 2 * TEXT_PADDING,
            height + 2 * TEXT_PADDING,
        )

        if self._caret_visible:
            caret_x, caret_y, caret_height = text.caret_rect()
            cr.set_source_rgba(
                text.color.red, text.color.green, text.color.blue, text.color.alpha
            )
            cr.rectangle(caret_x, caret_y, 1, caret_height)
            cr.fill()

    def _snapshot_handles(self, snapshot: Gtk.Snapshot, accent: Gdk.RGBA) -> None:
        """The grips, as rounded squares; they grow with the zoom like the image."""
        handles = self._handles()
        if not handles:
            return
        size, ring, radius = scaled(HANDLE_SIZE), scaled(HANDLE_RING), scaled(HANDLE_RADIUS)
        # A white ring keeps the grip readable on top of dark artwork.
        layers = (
            (size + 2 * ring, radius + ring, Gdk.RGBA(red=1, green=1, blue=1, alpha=1)),
            (size, radius, Gdk.RGBA(red=accent.red, green=accent.green, blue=accent.blue, alpha=1)),
        )
        snapshot.save()
        snapshot.scale(self.zoom, self.zoom)
        for hx, hy in handles.values():
            for extent, corner, color in layers:
                half = extent / 2
                square = _rect(hx - half, hy - half, extent, extent)
                # Built in steps: what init_from_rect() returns points into the
                # temporary struct it was called on, which is freed straight away.
                outline = Gsk.RoundedRect()
                outline.init_from_rect(square, min(corner, half))
                snapshot.push_rounded_clip(outline)
                snapshot.append_color(color, square)
                snapshot.pop()
        snapshot.restore()
