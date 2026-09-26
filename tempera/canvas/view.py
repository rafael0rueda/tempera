# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Zooming the canvas, and moving around the image it shows."""

from __future__ import annotations


from gi.repository import Gdk, GLib, Graphene, Gtk

from ..interface_size import scaled
from .frame import CanvasFrame
from .pointer import HANDLE_MARGIN

ZOOM_MIN = 0.1
# The pixel grid shows from this zoom up; below it the lines would crowd out
# the pixels they outline.
PIXEL_GRID_ZOOM = 4.0
ZOOM_MAX = 8.0
# What Ctrl+Plus/Minus step through, and Ctrl+scroll rounds towards.
ZOOM_PRESETS = [0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 8.0]
# Multiplier per scroll-wheel notch while zooming.
ZOOM_SCROLL_FACTOR = 1.1
# The canvas margin set in style.css. Zoom to Fit leaves it on both sides, plus
# the strip the resize grips need.
CANVAS_MARGIN = 32


def fit_zoom(image: tuple[int, int], viewport: tuple[int, int]) -> float:
    """The zoom at which an image just fits in the room available."""
    return min(viewport[0] / image[0], viewport[1] / image[1])


class ZoomMixin:
    """Zoom levels, and panning and pinching on the scrolling area around the canvas."""

    def _to_image(self, x: float, y: float) -> tuple[float, float]:
        """Widget-space pointer coordinates, converted to image pixels."""
        return x / self.zoom, y / self.zoom

    def set_zoom(self, zoom: float, anchor: tuple[float, float] | None = None) -> None:
        """Change the zoom level, optionally keeping a widget-space point fixed.

        `anchor` is the point on screen (e.g. the pointer) that should still be
        over the same image pixel once the zoom changes.
        """
        zoom = max(ZOOM_MIN, min(zoom, ZOOM_MAX))
        if zoom == self.zoom:
            return
        old_zoom = self.zoom
        self.zoom = zoom
        self._sync_content_size()
        self.queue_draw()
        self.emit("zoom-changed", zoom)
        if anchor is not None:
            self._preserve_anchor(anchor, old_zoom, zoom)

    def _preserve_anchor(
        self, anchor: tuple[float, float], old_zoom: float, new_zoom: float
    ) -> None:
        scrolled = self.get_ancestor(Gtk.ScrolledWindow)
        if scrolled is None:
            return
        image_x, image_y = anchor[0] / old_zoom, anchor[1] / old_zoom
        horizontal, vertical = scrolled.get_hadjustment(), scrolled.get_vadjustment()
        # Captured now, before the resize below reaches the adjustments: once
        # their bounds shrink (zooming out), GTK clamps .value on its own as
        # part of that same update, so reading .value fresh from inside the
        # tick callback would nudge from the already-clamped position instead
        # of the one the pointer was actually anchored to.
        base_value = (horizontal.get_value(), vertical.get_value())
        # Centring moves the canvas as it grows or shrinks, and the scroll has to
        # absorb that too.
        base_offset = self._frame_offset()
        stale_bounds = (horizontal.get_upper(), vertical.get_upper())
        attempts = 0

        def adjust(widget, frame_clock) -> bool:
            nonlocal attempts
            attempts += 1
            settled = (horizontal.get_upper(), vertical.get_upper()) != stale_bounds
            if not settled and attempts < 10:
                return GLib.SOURCE_CONTINUE
            offset = self._frame_offset()
            horizontal.set_value(
                base_value[0] + offset[0] - base_offset[0] + image_x * (new_zoom - old_zoom)
            )
            vertical.set_value(
                base_value[1] + offset[1] - base_offset[1] + image_y * (new_zoom - old_zoom)
            )
            return GLib.SOURCE_REMOVE

        self.add_tick_callback(adjust)

    def _frame_offset(self) -> tuple[int, int]:
        parent = self.get_parent()
        return parent.offset if isinstance(parent, CanvasFrame) else (0, 0)

    def zoom_in(self) -> None:
        bigger = [level for level in ZOOM_PRESETS if level > self.zoom + 1e-9]
        self.set_zoom(bigger[0] if bigger else ZOOM_MAX)

    def zoom_out(self) -> None:
        smaller = [level for level in ZOOM_PRESETS if level < self.zoom - 1e-9]
        self.set_zoom(smaller[-1] if smaller else ZOOM_MIN)

    def reset_zoom(self) -> None:
        self.set_zoom(1.0)

    def _viewport_size(self) -> tuple[int, int]:
        scrolled = self.get_ancestor(Gtk.ScrolledWindow)
        if scrolled is None:
            return (0, 0)
        padding = 2 * CANVAS_MARGIN + scaled(HANDLE_MARGIN)
        return (scrolled.get_width() - padding, scrolled.get_height() - padding)

    def zoom_to_fit(self) -> bool:
        """Zoom so the whole image is in view. False while the window has no size yet."""
        width, height = self._viewport_size()
        if width <= 0 or height <= 0:
            return False
        self.set_zoom(fit_zoom((self._document.width, self._document.height), (width, height)))
        return True

    def fit_if_too_large(self) -> None:
        """Open a photo bigger than the window zoomed out, rather than showing a corner of it.

        Called as a document arrives, which may be before the window has been
        given its size; then it waits for the first frame that has one.
        """
        def fit(*_args) -> bool:
            width, height = self._viewport_size()
            if width <= 0 or height <= 0:
                return GLib.SOURCE_CONTINUE
            if self._document.width > width or self._document.height > height:
                self.zoom_to_fit()
            else:
                self.reset_zoom()
            return GLib.SOURCE_REMOVE

        if fit() is GLib.SOURCE_CONTINUE:
            self.add_tick_callback(fit)

    # Panning and pinching, on the scrolling area around the canvas

    def attach_to_viewport(self, scrolled: Gtk.ScrolledWindow) -> None:
        """Take middle-drag and pinch gestures from the area the canvas scrolls in.

        They belong there rather than on the canvas itself, which moves under
        the pointer as it scrolls, and whose own drag gesture is for drawing.
        """
        pan = Gtk.GestureDrag(
            button=Gdk.BUTTON_MIDDLE, propagation_phase=Gtk.PropagationPhase.CAPTURE
        )
        pan.connect("drag-begin", self._on_pan_begin)
        pan.connect("drag-update", self._on_pan_update)
        pan.connect("drag-end", self._on_pan_end)
        scrolled.add_controller(pan)

        pinch = Gtk.GestureZoom()
        pinch.connect("begin", self._on_pinch_begin)
        pinch.connect("scale-changed", self._on_pinch_changed)
        scrolled.add_controller(pinch)
        self._pinch_zoom = 1.0

        # Only what is in view gets drawn, so scrolling, or a window growing,
        # brings in parts that have not been.
        for adjustment in (scrolled.get_hadjustment(), scrolled.get_vadjustment()):
            adjustment.connect("value-changed", lambda *_args: self.queue_draw())
            adjustment.connect("changed", lambda *_args: self.queue_draw())

    def _adjustments(self) -> tuple[Gtk.Adjustment, Gtk.Adjustment] | None:
        scrolled = self.get_ancestor(Gtk.ScrolledWindow)
        if scrolled is None:
            return None
        return scrolled.get_hadjustment(), scrolled.get_vadjustment()

    def _on_pan_begin(self, gesture, start_x, start_y) -> None:
        adjustments = self._adjustments()
        if adjustments is None:
            return
        self._pan_origin = tuple(adjustment.get_value() for adjustment in adjustments)
        self.set_cursor(Gdk.Cursor.new_from_name("grabbing"))

    def _on_pan_update(self, gesture, offset_x, offset_y) -> None:
        adjustments = self._adjustments()
        if adjustments is None or self._pan_origin is None:
            return
        # Drag the image with the pointer: the view goes the other way.
        for adjustment, origin, offset in zip(adjustments, self._pan_origin, (offset_x, offset_y)):
            adjustment.set_value(origin - offset)

    def _on_pan_end(self, gesture, offset_x, offset_y) -> None:
        self._pan_origin = None
        self._set_cursor(None)

    def _on_pinch_begin(self, gesture, sequence) -> None:
        self._pinch_zoom = self.zoom

    def _on_pinch_changed(self, gesture, scale: float) -> None:
        found, center = gesture.get_bounding_box_center()
        anchor = None
        if found:
            scrolled = self.get_ancestor(Gtk.ScrolledWindow)
            point = Graphene.Point()
            point.init(center.x, center.y)
            ok, here = scrolled.compute_point(self, point)
            if ok:
                anchor = (here.x, here.y)
        self.set_zoom(self._pinch_zoom * scale, anchor=anchor)

    def _on_scroll(self, controller, dx: float, dy: float) -> bool:
        if not controller.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            return Gdk.EVENT_PROPAGATE
        self.set_zoom(self.zoom * ZOOM_SCROLL_FACTOR ** -dy, anchor=self._last_pointer)
        return Gdk.EVENT_STOP
