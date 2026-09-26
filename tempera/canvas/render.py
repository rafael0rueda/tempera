# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Drawing the image and everything over it."""

from __future__ import annotations

import math
from functools import cache

import cairo
from gi.repository import Adw, Gdk

from ..interface_size import scaled
from ..tools import draw_marquee
from ..tools.base import draw_outline_marquee
from .floating import TEXT_PADDING
from .pointer import HANDLE_RADIUS, HANDLE_RING, HANDLE_SIZE

CHECKER_SIZE = 8
# Below this zoom the image is shrunk, where smoothing reads better than dropped
# pixels; at or above it every image pixel shows as a crisp square.
SMOOTH_ZOOM_BELOW = 1.0


@cache
def _checker_pattern() -> cairo.SurfacePattern:
    """One 2 × 2 tile of the checkerboard, repeated by cairo.

    Drawing each square as its own rectangle came to half a million of them per
    frame on the largest canvas.
    """
    size = CHECKER_SIZE * 2
    tile = cairo.ImageSurface(cairo.FORMAT_RGB24, size, size)
    cr = cairo.Context(tile)
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    cr.set_source_rgb(0.9, 0.9, 0.9)
    cr.rectangle(CHECKER_SIZE, 0, CHECKER_SIZE, CHECKER_SIZE)
    cr.rectangle(0, CHECKER_SIZE, CHECKER_SIZE, CHECKER_SIZE)
    cr.fill()
    pattern = cairo.SurfacePattern(tile)
    pattern.set_extend(cairo.EXTEND_REPEAT)
    pattern.set_filter(cairo.FILTER_NEAREST)
    return pattern


class RenderMixin:
    """Draws the image, a tool's preview, and the outlines and grips over them."""

    def _draw(self, area, cr: cairo.Context, width: int, height: int, *_args):
        image_width, image_height = self._document.width, self._document.height

        # Everything below is laid out in image pixels; this one transform is
        # what makes it appear at the current zoom level on screen.
        cr.save()
        cr.scale(self.zoom, self.zoom)

        cr.save()
        cr.rectangle(0, 0, image_width, image_height)
        cr.clip()
        self._draw_checkerboard(cr)
        cr.set_source_surface(self._document.surface, 0, 0)
        if self.zoom >= SMOOTH_ZOOM_BELOW:
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()

        context = self._drag_context
        if context is None and self.active_tool.in_progress:
            context = self._make_context(self._shape_button)
        if context is not None:
            cr.save()
            self.active_tool.draw_preview(cr, context)
            cr.restore()
        cr.restore()

        if self.pixel_grid_visible:
            self._draw_pixel_grid(cr, image_width, image_height)

        accent = self._accent()
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
        self._draw_handles(cr, accent)
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

    def _draw_handles(self, cr: cairo.Context, accent: Gdk.RGBA) -> None:
        size = scaled(HANDLE_SIZE)
        ring = scaled(HANDLE_RING)
        for hx, hy in self._handles().values():
            # A white ring keeps the grip readable on top of dark artwork.
            _rounded_square(cr, hx, hy, size + 2 * ring, scaled(HANDLE_RADIUS) + ring)
            cr.set_source_rgb(1, 1, 1)
            cr.fill()
            _rounded_square(cr, hx, hy, size, scaled(HANDLE_RADIUS))
            cr.set_source_rgba(accent.red, accent.green, accent.blue, 1.0)
            cr.fill()

    @staticmethod
    def _draw_checkerboard(cr: cairo.Context) -> None:
        """Fill the current clip with the transparency checkerboard."""
        cr.save()
        cr.set_source(_checker_pattern())
        cr.paint()
        cr.restore()


def _rounded_square(cr: cairo.Context, x: float, y: float, size: float, radius: float) -> None:
    """A square path centred on a point, its corners rounded."""
    half = size / 2
    radius = min(radius, half)
    left, top, right, bottom = x - half, y - half, x + half, y + half
    cr.new_sub_path()
    cr.arc(right - radius, top + radius, radius, -math.pi / 2, 0)
    cr.arc(right - radius, bottom - radius, radius, 0, math.pi / 2)
    cr.arc(left + radius, bottom - radius, radius, math.pi / 2, math.pi)
    cr.arc(left + radius, top + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()
