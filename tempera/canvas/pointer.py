# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pointer input: the grips, the cursor, and drags that paint, move or resize."""

from __future__ import annotations

from dataclasses import replace

from gi.repository import Gdk, GLib

from ..background import run_in_background
from ..document import MAX_SIZE
from ..interface_size import scaled
from ..tools import ToolContext
from ..tools.base import rect_handles
from .floating import TEXT_PADDING

# The resize grips, at the default interface size; they grow with it.
HANDLE_SIZE = 10
HANDLE_RADIUS = 3
HANDLE_RING = 2
HANDLE_GRAB = 12
# Room around the image so the grips sitting on its edge are fully visible.
HANDLE_MARGIN = 8
# How near, in screen pixels at the default interface size, a click must land
# to hit a point already placed, such as a polygon's first corner.
POINT_REACH = 6
# How far the pointer has to travel before a click inside a text box counts
# as dragging it somewhere else rather than placing the caret.
MOVE_THRESHOLD = 4
HANDLE_CURSORS = {
    "e": "ew-resize",
    "w": "ew-resize",
    "n": "ns-resize",
    "s": "ns-resize",
    "ne": "nesw-resize",
    "sw": "nesw-resize",
    "nw": "nwse-resize",
    "se": "nwse-resize",
    "paste": "move",
    "text": "text",
    "selection": "move",
}


class PointerMixin:
    """The grips, the cursor over them, and the drags that paint, move or resize."""

    def _handles(self) -> dict[str, tuple[float, float]]:
        if self._paste is not None:
            # Scales the pasted pixels rather than the canvas.
            return rect_handles(self._paste.x, self._paste.y, self._paste.width, self._paste.height)
        if self.active_tool.adjustable:
            # A shape that has been drawn but not landed: its own grips reshape it.
            return self.active_tool.handles()
        if self.has_floating or self.active_tool.in_progress:
            # A text box owns the pointer until it lands, and a shape being
            # placed takes every click, even on the edge of the image.
            return {}
        if self.selecting and self._selection is not None:
            # Scales the selected pixels in place.
            return rect_handles(*self._selection.rect)
        width, height = self._resize_size or (self._document.width, self._document.height)
        return {
            "e": (width, height / 2),
            "s": (width / 2, height),
            "se": (width, height),
        }

    def _paste_resized(self, x: float, y: float) -> tuple[float, float, float, float]:
        """New (x, y, width, height) for the floating paste, dragging one handle."""
        ox, oy, ow, oh = self._paste_resize_origin
        handle = self._paste_resize_handle
        left, right = ox, ox + ow
        top, bottom = oy, oy + oh
        if "w" in handle:
            left = max(0.0, min(x, right - 1))
        elif "e" in handle:
            right = min(max(x, left + 1), left + MAX_SIZE)
        if "n" in handle:
            top = max(0.0, min(y, bottom - 1))
        elif "s" in handle:
            bottom = min(max(y, top + 1), top + MAX_SIZE)
        return left, top, right - left, bottom - top

    def _resize_paste(self, x: float, y: float) -> None:
        left, top, width, height = self._paste_resized(x, y)
        self._paste.x, self._paste.y = left, top
        self._paste.scale_x = width / self._paste.surface.get_width()
        self._paste.scale_y = height / self._paste.surface.get_height()
        self._sync_content_size()
        self.queue_draw()
        self.emit("floating-changed")

    def _shape_reach(self) -> float:
        """How near a pending shape a press has to land to take hold of it."""
        return scaled(POINT_REACH) / self.zoom + self._brush_size / 2

    def _handle_box(self) -> tuple[float, float, float, float]:
        """The rectangle the handles belong to: a paste, a shape, a selection, or the image."""
        if self._paste is not None:
            return self._paste.x, self._paste.y, self._paste.width, self._paste.height
        bounds = self.active_tool.bounds() if self.active_tool.adjustable else None
        if bounds is not None:
            return bounds
        if self.selecting and self._selection is not None:
            return self._selection.rect
        return 0, 0, self._document.width, self._document.height

    def _handle_at(self, x: float, y: float) -> str | None:
        """The closest handle within reach, since a small selection or paste
        packs all 8 into less room than the grab tolerance around each one."""
        best: str | None = None
        best_distance = None
        box_x, box_y, box_width, box_height = self._handle_box()
        if box_x < x < box_x + box_width and box_y < y < box_y + box_height:
            # From inside, only the grip as drawn: the rest of a small selection
            # or paste is for dragging it somewhere else, and of the image for painting.
            grab = scaled(HANDLE_SIZE) / 2
        else:
            grab = scaled(HANDLE_GRAB)
        for name, (hx, hy) in self._handles().items():
            if abs(x - hx) <= grab and abs(y - hy) <= grab:
                distance = (x - hx) ** 2 + (y - hy) ** 2
                if best_distance is None or distance < best_distance:
                    best, best_distance = name, distance
        return best

    def _set_cursor(self, handle: str | None) -> None:
        if handle is not None and handle not in HANDLE_CURSORS:
            # A grip on one of a shape's own points, which goes anywhere.
            name = "move"
        else:
            name = HANDLE_CURSORS.get(handle, "crosshair")
        self.set_cursor(Gdk.Cursor.new_from_name(name))

    def _on_motion(self, controller, x, y) -> None:
        self._last_pointer = (x, y)
        x, y = self._to_image(x, y)
        self.emit("pointer-moved", x, y)
        if self._drag_origin is not None:
            return
        if self.active_tool.in_progress:
            # The side or bend still to come follows the pointer.
            self.active_tool.hover(x, y)
            self.queue_draw()
        handle = self._handle_at(x, y)
        if handle is not None:
            self._set_cursor(handle)
            return
        if self._paste is not None and self._paste.contains(x, y):
            self._set_cursor("paste")
            return
        if self.active_tool.adjustable and self.active_tool.contains(x, y, self._shape_reach()):
            self._set_cursor("selection")
            return
        if self._text is not None and self._text.contains(x, y, TEXT_PADDING):
            self._set_cursor("text")
            return
        if self._selection_at(x, y) is not None:
            self._set_cursor("selection")
            return
        self._set_cursor(None)

    def _on_leave(self, *_args) -> None:
        self._set_cursor(None)
        self.emit("pointer-left")

    def _resized_to(self, x: float, y: float) -> tuple[int, int]:
        width, height = self._document.width, self._document.height
        if self._resize_handle in ("e", "se"):
            width = round(x)
        if self._resize_handle in ("s", "se"):
            height = round(y)
        return max(1, min(width, MAX_SIZE)), max(1, min(height, MAX_SIZE))

    # Pointer input

    def _make_context(self, button: int) -> ToolContext:
        return ToolContext(
            surface=self._document.surface,
            primary=self.colors.primary,
            secondary=self.colors.secondary,
            button=button,
            size=self.brush_size,
            fill_shapes=self.fill_shapes,
            outline_shapes=self.outline_shapes,
            erase_to_transparency=self.erase_to_transparency,
            tolerance=self.fill_tolerance,
            density=self.airbrush_density,
            reach=scaled(POINT_REACH) / self.zoom,
            pick_color=lambda color, btn: self.emit("color-picked", color, btn),
            begin_text=self.begin_text,
            select_region=self.select_region,
            select_outline=self.select_outline,
            damage=self._damage,
        )

    def _on_drag_begin(self, gesture, start_x, start_y):
        if gesture.get_current_button() == Gdk.BUTTON_MIDDLE:
            # The middle button pans the view; it does not paint.
            return
        if self._working:
            # The last fill is not done yet; this press would paint under it.
            return
        start_x, start_y = self._to_image(start_x, start_y)
        self._drag_origin = (start_x, start_y)

        if self._text is not None:
            if self._text.contains(start_x, start_y, TEXT_PADDING):
                # A click moves the caret, which leaves any half-composed word behind.
                self._im.reset()
                self._text.set_preedit("", 0)
                self._text_origin = (self._text.x, self._text.y)
                self._text_moved = False
                self.grab_focus()
            else:
                # Clicking away lands the text; the click itself does not draw.
                self.commit_text()
            return

        handle = self._handle_at(start_x, start_y)
        # Ctrl leaves the original where it is, so the drag copies instead of moves.
        copy = bool(gesture.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK)

        if self._paste is not None:
            if handle is not None:
                self._paste_resize_handle = handle
                self._paste_resize_origin = (
                    self._paste.x,
                    self._paste.y,
                    self._paste.width,
                    self._paste.height,
                )
                self._set_cursor(handle)
                return
            if self._paste.contains(start_x, start_y):
                self._paste_origin = (self._paste.x, self._paste.y)
                self._set_cursor("paste")
            else:
                # Clicking away lands the paste; the click itself does not draw.
                self.commit_paste()
            return

        if self.active_tool.adjustable:
            if handle is not None:
                self.active_tool.grab(handle, start_x, start_y)
                self._set_cursor(handle)
            elif self.active_tool.contains(start_x, start_y, self._shape_reach()):
                self.active_tool.grab(None, start_x, start_y)
                self._set_cursor("selection")
            else:
                # Pressing away lands the shape, and this same drag draws the
                # next one; a press that never moves just lands it.
                origin, self._drag_origin = self._drag_origin, None
                self.finish_shape()
                self._drag_origin = origin
            if self.active_tool.adjustable:
                self._shape_adjusting = True
                return

        # Grabbing a selection's own handle scales it in place, without a
        # separate gesture to first lift it the way moving it needs.
        if self.selecting and self._selection is not None and handle is not None:
            self._lift_selection(copy)
            self._paste_resize_handle = handle
            self._paste_resize_origin = (
                self._paste.x,
                self._paste.y,
                self._paste.width,
                self._paste.height,
            )
            self._set_cursor(handle)
            return

        # Only the select tool picks the pixels up; the others paint over them.
        if self._selection_at(start_x, start_y) is not None:
            self._lift_selection(copy)
            self._paste_origin = (self._paste.x, self._paste.y)
            self._set_cursor("paste")
            return

        if handle is not None:
            self._resize_handle = handle
            self._resize_size = (self._document.width, self._document.height)
            self._set_cursor(handle)
            self.queue_draw()
            return

        if not self.active_tool.in_progress:
            self._shape_button = gesture.get_current_button()
        self._drag_context = self._make_context(self._shape_button)
        if self.active_tool.mutates:
            self._document.begin_change()
        if self.active_tool.background:
            self._press_in_background(start_x, start_y)
        else:
            self.active_tool.press(self._drag_context, start_x, start_y)
        if self.active_tool.repeat_ms:
            self._repeat_source = GLib.timeout_add(self.active_tool.repeat_ms, self._on_repeat)
        self.queue_draw()

    def _press_in_background(self, x: float, y: float) -> None:
        """Run a slow press, such as a fill, off the UI thread.

        The stroke lasts until it is done, whenever the button is let go: the
        canvas takes no other press or key meanwhile, and the actions that
        change the image wait, as they do for any drag.
        """
        tool = self.active_tool
        # What it paints is noted here and passed on once it is done, since
        # only the UI thread may touch what is drawn on screen.
        painted: list[tuple[float, float, float, float]] = []
        context = replace(self._drag_context, damage=lambda *extents: painted.append(extents))
        self._working = True
        self.set_cursor(Gdk.Cursor.new_from_name("progress"))

        def work() -> Exception | None:
            try:
                tool.press(context, x, y)
            except Exception as error:
                # Handed back rather than lost with the thread, so the stroke
                # still ends and the error still shows.
                return error
            return None

        def done(error: Exception | None) -> None:
            self._working = False
            self._set_cursor(None)
            for extents in painted:
                self._damage(*extents)
            if self._pending_release is not None:
                release, self._pending_release = self._pending_release, None
                self._finish_stroke(*release)
            else:
                self.queue_draw()
            if error is not None:
                raise error

        run_in_background(work, done)

    def _on_repeat(self) -> bool:
        if self._drag_context is None:
            self._repeat_source = 0
            return GLib.SOURCE_REMOVE
        self.active_tool.repeat(self._drag_context)
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _stop_repeat(self) -> None:
        if self._repeat_source:
            GLib.source_remove(self._repeat_source)
            self._repeat_source = 0

    def _on_drag_update(self, gesture, offset_x, offset_y):
        if self._drag_origin is None:
            return
        offset_x, offset_y = offset_x / self.zoom, offset_y / self.zoom
        x, y = self._drag_origin[0] + offset_x, self._drag_origin[1] + offset_y

        if self._text_origin is not None:
            if not self._text_moved and max(abs(offset_x), abs(offset_y)) < MOVE_THRESHOLD:
                # Still small enough to be the wobble of a click placing the caret.
                return
            self._text_moved = True
            self._text.move_to(self._text_origin[0] + offset_x, self._text_origin[1] + offset_y)
            self._refresh_text()
            return

        if self._paste_resize_handle is not None:
            self._resize_paste(x, y)
            return

        if self._shape_adjusting:
            self.active_tool.drag_to(
                x, y, bool(gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK)
            )
            self.queue_draw()
            return

        if self._paste_origin is not None:
            self._paste.move_to(self._paste_origin[0] + offset_x, self._paste_origin[1] + offset_y)
            self._sync_content_size()
            self.queue_draw()
            self.emit("floating-changed")
            return

        if self._resize_handle is not None:
            self._resize_size = self._resized_to(x, y)
            self._sync_content_size()
            self.emit("resize-preview", *self._resize_size)
            self.queue_draw()
            return

        if self._drag_context is None or self._working:
            return

        self._drag_context.constrain = bool(
            gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK
        )
        self.active_tool.motion(self._drag_context, x, y)
        self.queue_draw()

    def _on_drag_end(self, gesture, offset_x, offset_y):
        if self._drag_origin is None:
            return
        offset_x, offset_y = offset_x / self.zoom, offset_y / self.zoom
        x, y = self._drag_origin[0] + offset_x, self._drag_origin[1] + offset_y

        if self._text_origin is not None:
            if not self._text_moved:
                # A click rather than a drag: put the caret where it landed.
                self._text.caret_at(x, y)
            self._text_origin = None
            self._text_moved = False
            self._drag_origin = None
            self._refresh_text()
            return

        if self._paste_resize_handle is not None:
            self._resize_paste(x, y)
            self._paste_resize_handle = None
            self._paste_resize_origin = None
            self._drag_origin = None
            return

        if self._shape_adjusting:
            self.active_tool.drag_to(
                x, y, bool(gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK)
            )
            self._shape_adjusting = False
            self._drag_origin = None
            self.queue_draw()
            return

        if self._paste_origin is not None or self._paste is not None:
            # A floating paste stays floating; the drag only moved it.
            self._paste_origin = None
            self._drag_origin = None
            return

        if self._resize_handle is not None:
            width, height = self._resized_to(x, y)
            self._resize_handle = None
            self._resize_size = None
            self._drag_origin = None
            self._document.resize(width, height)
            self._sync_content_size()
            self.queue_draw()
            return

        if self._drag_context is None:
            # The press landed a paste instead of starting a stroke.
            self._drag_origin = None
            return

        self._stop_repeat()
        self._drag_context.constrain = bool(
            gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK
        )
        if self._working:
            # The press is still at work; the stroke ends once it is done.
            self._pending_release = (x, y)
            self._drag_origin = None
            return
        self._finish_stroke(x, y)

    def _finish_stroke(self, x: float, y: float) -> None:
        """Let the tool finish, and keep what it painted as one step to undo."""
        self.active_tool.release(self._drag_context, x, y)
        if self.active_tool.mutates:
            self._document.finish_change()
            # A shape only counts once it lands.
            if not self.active_tool.in_progress:
                self.colors.remember(*self.active_tool.colors_used(self._drag_context))
        self._drag_origin = None
        self._drag_context = None
        if self.active_tool.in_progress:
            # Enter lands the shape and Esc drops it.
            self.grab_focus()
            self.emit("floating-changed")
        self.queue_draw()
