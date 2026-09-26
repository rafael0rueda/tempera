# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The widget that centres the canvas and draws its shadow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gi.repository import Gdk, Graphene, Gsk, Gtk

if TYPE_CHECKING:
    from .widget import Canvas


# The image's drop shadow: (colour alpha, y offset, blur), a tight one for the
# edge and a soft one for depth.
IMAGE_SHADOWS = ((0.25, 1, 3), (0.18, 10, 30))


class CanvasFrame(Gtk.Widget):
    """Centres the canvas in whatever room the scrolled window gives it.

    The offset is held while a button is down or a paste is floating: a resize
    grip or an overhanging paste grows the canvas, and re-centring then would
    slide the image out from under the pointer. It catches up once they end.
    """

    def __init__(self, canvas: Canvas):
        super().__init__()
        self.canvas = canvas
        canvas.set_parent(self)
        self.offset = (0, 0)
        canvas.connect("floating-changed", lambda *_args: self.queue_resize())

    def _held(self) -> bool:
        return self.canvas.is_dragging or self.canvas.has_floating

    def do_dispose(self) -> None:
        self.canvas.unparent()

    def do_get_request_mode(self) -> Gtk.SizeRequestMode:
        return Gtk.SizeRequestMode.CONSTANT_SIZE

    def do_measure(self, orientation: Gtk.Orientation, for_size: int):
        minimum, natural, _, _ = self.canvas.measure(orientation, -1)
        if self._held():
            # Room for the canvas to grow from where it is pinned, not from 0.
            offset = self.offset[0 if orientation == Gtk.Orientation.HORIZONTAL else 1]
            minimum, natural = minimum + offset, natural + offset
        return minimum, natural, -1, -1

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        _, child_width, _, _ = self.canvas.measure(Gtk.Orientation.HORIZONTAL, -1)
        _, child_height, _, _ = self.canvas.measure(Gtk.Orientation.VERTICAL, -1)
        if not self._held():
            self.offset = (max(0, (width - child_width) // 2), max(0, (height - child_height) // 2))
        x, y = self.offset
        allocation = Gdk.Rectangle()
        allocation.x, allocation.y = x, y
        allocation.width, allocation.height = child_width, child_height
        self.canvas.size_allocate(allocation, -1)
        # The shadow is the frame's to draw, and follows the image as it moves or grows.
        self.queue_draw()

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        # Under the image only, not the room kept past it for the grips.
        canvas = self.canvas
        found, origin = canvas.compute_point(self, Graphene.Point().init(0, 0))
        if found:
            document = canvas.document
            bounds = Graphene.Rect().init(
                origin.x, origin.y, document.width * canvas.zoom, document.height * canvas.zoom
            )
            # Built in steps: what init_from_rect() returns points into the
            # temporary struct it was called on, which is freed straight away.
            outline = Gsk.RoundedRect()
            outline.init_from_rect(bounds, 0)
            for alpha, offset, blur in IMAGE_SHADOWS:
                color = Gdk.RGBA(red=0, green=0, blue=0, alpha=alpha)
                snapshot.append_outset_shadow(outline, color, 0, offset, 0, blur)
        self.snapshot_child(canvas, snapshot)
