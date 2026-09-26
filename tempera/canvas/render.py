# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drawing the image and everything over it."""

from __future__ import annotations

import math
from functools import cache

import cairo
from gi.repository import Adw, Gdk, Graphene, Gsk, Gtk

from ..document import Damage, Layer
from ..interface_size import scaled
from ..tools import draw_marquee
from ..tools.base import draw_edges_marquee, draw_outline_marquee
from .floating import TEXT_PADDING, rotate_grip
from .pointer import HANDLE_RADIUS, HANDLE_RING, HANDLE_SIZE
from .tiles import ImageTiles, mask_texture, surface_texture

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
    """Draws the layers, what floats over them, and the outlines and grips on top.

    Each layer goes to the GPU as tiles of texture, which it scales to the
    zoom and blends at the layer's opacity by itself, and only the tiles a
    change touched are uploaded again. What is drawn with cairo covers just the
    part of the screen it takes up.
    """

    def _init_render(self) -> None:
        # Each layer's textures, for as long as the layer is in the picture.
        self._tiles: dict[Layer, ImageTiles] = {}

    def _layer_tiles(self, layer: Layer) -> ImageTiles:
        tiles = self._tiles.get(layer)
        if tiles is None:
            tiles = self._tiles[layer] = ImageTiles()
        return tiles

    def _damage(self, x1: float, y1: float, x2: float, y2: float) -> None:
        """A tool painted within these extents of the current layer; their tiles need uploading again."""
        # Antialiasing reaches into the pixels the extents only partly cover.
        left, top = math.floor(x1) - 1, math.floor(y1) - 1
        rect = (left, top, math.ceil(x2) + 1 - left, math.ceil(y2) + 1 - top)
        self._layer_tiles(self._document.layer).invalidate(rect)

    def _invalidate(self, damage: Damage) -> None:
        """Forget the textures a change to the document touched."""
        if damage is None:
            for tiles in self._tiles.values():
                tiles.invalidate()
            return
        for layer, rect in damage:
            tiles = self._tiles.get(layer)
            if tiles is not None:
                tiles.invalidate(rect)

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
            self._snapshot_layers(snapshot, visible, (left, top, right - left, bottom - top))

        accent = self._accent()
        self._snapshot_cairo(snapshot, visible, lambda cr: self._draw_chrome(cr, accent))
        self._snapshot_handles(snapshot, accent)

    def _snapshot_layers(
        self,
        snapshot: Gtk.Snapshot,
        visible: tuple[float, float, float, float],
        region: tuple[float, float, float, float],
    ) -> None:
        """The layers bottom up, each at its opacity, with what floats over the
        current one drawn right above it, where it will land."""
        document, zoom = self._document, self.zoom
        scaling = Gsk.ScalingFilter.NEAREST if zoom >= SMOOTH_ZOOM_BELOW else Gsk.ScalingFilter.TRILINEAR
        align = self._pixel_aligner()
        vacating = self._paste is not None and self._paste.source is not None
        for index, layer in enumerate(document.layers):
            current = index == document.current
            # What floats over a hidden layer still shows while it is placed.
            if not layer.visible and not current:
                continue
            see_through = layer.visible and layer.opacity < 1
            if see_through:
                snapshot.push_opacity(layer.opacity)
            if layer.visible:
                if current and vacating:
                    # A selection being moved has left its place empty.
                    self._push_vacated_mask(snapshot)
                self._layer_tiles(layer).snapshot(snapshot, layer.surface, region, zoom, scaling, align)
                if current and vacating:
                    snapshot.pop()
                if index == 0:
                    self._snapshot_cairo(snapshot, visible, self._draw_bottom_extras)
            if current:
                self._snapshot_cairo(snapshot, visible, self._draw_layer_extras)
            if see_through:
                snapshot.pop()

        # Textures of layers no longer in the picture; one brought back by an
        # undo is uploaded again.
        present = {id(layer) for layer in document.layers}
        for layer in [layer for layer in self._tiles if id(layer) not in present]:
            del self._tiles[layer]

    def _push_vacated_mask(self, snapshot: Gtk.Snapshot) -> None:
        """Start drawing the current layer with the place a moved selection left cut out of it."""
        paste, zoom = self._paste, self.zoom
        x, y, width, height = paste.source
        bounds = _rect(x * zoom, y * zoom, width * zoom, height * zoom)
        snapshot.push_mask(Gsk.MaskMode.INVERTED_ALPHA)
        if paste.source_mask is None:
            if zoom < SMOOTH_ZOOM_BELOW:
                # Shrunk smoothly, the pixels taken blur a little past where
                # they were; a screen pixel more of hole hides the fringe.
                bounds = _rect(x * zoom - 1, y * zoom - 1, width * zoom + 2, height * zoom + 2)
            snapshot.append_color(Gdk.RGBA(red=0, green=0, blue=0, alpha=1), bounds)
        else:
            snapshot.append_scaled_texture(
                mask_texture(paste.source_mask), Gsk.ScalingFilter.NEAREST, bounds
            )
        snapshot.pop()

    def _snapshot_cairo(
        self, snapshot: Gtk.Snapshot, visible: tuple[float, float, float, float], draw
    ) -> None:
        """Draw with cairo, over no more of the screen than what is drawn covers.

        It is drawn once into a recording, just to learn how much it covers:
        most of the time that is nothing, or a small box, rather than the
        whole view. Then it is drawn again into a node that size. Playing the
        recording back instead would be one drawing rather than two, but GTK's
        GPU renderers lose dashed lines at an angle from it.
        """
        def prepare(cr: cairo.Context) -> None:
            cr.rectangle(*visible)
            cr.clip()
            # Laid out in image pixels; this one transform is what makes it
            # appear at the current zoom level on screen.
            cr.scale(self.zoom, self.zoom)

        recording = cairo.RecordingSurface(cairo.CONTENT_COLOR_ALPHA, None)
        cr = cairo.Context(recording)
        prepare(cr)
        draw(cr)
        x, y, width, height = recording.ink_extents()
        if width <= 0 or height <= 0:
            return
        left, top = math.floor(x), math.floor(y)
        cr = snapshot.append_cairo(_rect(left, top, math.ceil(x + width) - left, math.ceil(y + height) - top))
        prepare(cr)
        draw(cr)

    def _draw_bottom_extras(self, cr: cairo.Context) -> None:
        """What floats leaves white on the bottom layer: where a paste or text makes
        the canvas grow, and where a selection moved from it."""
        document = self._document
        image_width, image_height = document.width, document.height
        paste = self._paste
        if paste is not None:
            if paste.source is not None and document.current == 0:
                cr.save()
                cr.set_source_rgb(1, 1, 1)
                if paste.source_mask is None:
                    cr.rectangle(*paste.source)
                    cr.fill()
                else:
                    cr.mask_surface(paste.source_mask, paste.source[0], paste.source[1])
                cr.restore()
            self._draw_overhang(cr, *paste.bounds(), image_width, image_height)
        text = self._text
        if text is not None:
            width, height = text.size
            if width > 0 and height > 0:
                self._draw_overhang(cr, text.x, text.y, width, height, image_width, image_height)

    def _draw_layer_extras(self, cr: cairo.Context) -> None:
        """What is on its way onto the current layer: a tool's preview, a paste, or text."""
        document = self._document
        context = self._drag_context
        if context is None and self.active_tool.in_progress:
            context = self._make_context(self._shape_button)
        if context is not None:
            cr.save()
            cr.rectangle(0, 0, document.width, document.height)
            cr.clip()
            self.active_tool.draw_preview(cr, context)
            cr.restore()

        if self._paste is not None:
            self._paste.paint(cr)

        text = self._text
        if text is not None:
            width, height = text.size
            if width > 0 and height > 0:
                text.render(cr)

    def _draw_chrome(self, cr: cairo.Context, accent: Gdk.RGBA) -> None:
        """The outlines, the caret and the grid, over every layer."""
        image_width, image_height = self._document.width, self._document.height
        if self.pixel_grid_visible:
            self._draw_pixel_grid(cr, image_width, image_height)

        frame = self.active_tool.frame() if self.active_tool.adjustable else None
        if frame is not None and frame[2] >= 1 and frame[3] >= 1:
            self._draw_dashed_rect(cr, accent, *frame)
        if self._resize_size is not None:
            self._draw_resize_preview(cr, accent, image_width, image_height)
        paste = self._paste
        if paste is not None:
            if paste.transformed:
                self._draw_dashed_outline(cr, accent, paste.corners())
            else:
                self._draw_dashed_rect(cr, accent, paste.x, paste.y, paste.width, paste.height)
        self._draw_rotate_stalk(cr, accent)
        if self._text is not None:
            self._draw_text_frame(cr, accent)
        selection = self._selection
        if selection is not None:
            if selection.outline is not None:
                cr.save()
                cr.rectangle(0, 0, image_width, image_height)
                cr.clip()
                draw_outline_marquee(cr, selection.outline)
                cr.restore()
            elif selection.mask is not None:
                # Picked out pixel by pixel: the ants follow the pixels' edges.
                draw_edges_marquee(cr, selection.edges)
            else:
                draw_marquee(cr, *selection.rect)

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
    def _draw_dashed_outline(cr: cairo.Context, accent: Gdk.RGBA, corners) -> None:
        """The dashed line around a turned or skewed paste.

        At an angle it runs across pixels rather than between them, blurred
        over the edge of what it outlines; dashes over a white line show on
        anything, as the white ring around a grip does.
        """
        cr.save()
        # One screen pixel wide, whatever the zoom, as the upright one is.
        x_scale, _y_scale = cr.user_to_device_distance(1, 0)
        cr.move_to(*corners[0])
        for corner in corners[1:]:
            cr.line_to(*corner)
        cr.close_path()
        cr.set_line_width(2 / x_scale)
        cr.set_source_rgb(1, 1, 1)
        cr.stroke_preserve()
        cr.set_line_width(1.25 / x_scale)
        cr.set_dash([4 / x_scale, 3 / x_scale])
        cr.set_source_rgba(accent.red, accent.green, accent.blue, 1.0)
        cr.stroke()
        cr.restore()

    def _draw_rotate_stalk(self, cr: cairo.Context, accent: Gdk.RGBA) -> None:
        """A short line from the middle of the top edge to the grip that turns it."""
        if "rotate" not in self._handles():
            return
        if self._paste is not None:
            grip, anchor = self._paste.rotate_grip()
        else:
            grip, anchor = rotate_grip(*self._selection.rect)
        cr.save()
        cr.set_source_rgba(accent.red, accent.green, accent.blue, 1.0)
        x_scale, _y_scale = cr.user_to_device_distance(1, 0)
        cr.set_line_width(1.5 / x_scale)
        cr.move_to(*anchor)
        cr.line_to(*grip)
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

    def _draw_text_frame(self, cr: cairo.Context, accent: Gdk.RGBA) -> None:
        text = self._text
        width, height = text.size
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
        for name, (hx, hy) in handles.items():
            for extent, corner, color in layers:
                half = extent / 2
                if name == "rotate":
                    # Round, to tell it from the grips that stretch.
                    corner = half
                square = _rect(hx - half, hy - half, extent, extent)
                # Built in steps: what init_from_rect() returns points into the
                # temporary struct it was called on, which is freed straight away.
                outline = Gsk.RoundedRect()
                outline.init_from_rect(square, min(corner, half))
                snapshot.push_rounded_clip(outline)
                snapshot.append_color(color, square)
                snapshot.pop()
        snapshot.restore()
