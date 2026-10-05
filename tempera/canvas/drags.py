# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""What a held button is doing, from the press to the release.

A press on the canvas starts one of these, chosen once by what was under the
pointer; every move and the release then go to it alone. Each holds on to the
very thing it took hold of, so a drag whose paste or text box has since landed
simply has nothing left to do.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ..document import MAX_SIZE
from .floating import SIDE_GRIPS, FloatingPaste, too_large_message

if TYPE_CHECKING:
    from ..text import TextBox
    from ..tools import Tool
    from .widget import Canvas

# How far the pointer has to travel before a click inside a text box counts
# as dragging it somewhere else rather than placing the caret.
MOVE_THRESHOLD = 4


class Drag:
    """A press that does nothing more until the button is let go: one that landed
    a paste or a text box by clicking away from it."""

    def __init__(self, canvas: Canvas):
        self.canvas = canvas

    def update(self, x: float, y: float, dx: float, dy: float, shift: bool) -> None:
        """The pointer moved to (x, y) on the image, (dx, dy) from where it was pressed."""

    def end(self, x: float, y: float, dx: float, dy: float, shift: bool) -> None:
        """The button was let go."""


class TextDrag(Drag):
    """A press inside a text box: a click places the caret, a drag moves the box."""

    def __init__(self, canvas: Canvas, text: TextBox):
        super().__init__(canvas)
        self.text = text
        self.origin = (text.x, text.y)
        self.moved = False

    def update(self, x, y, dx, dy, shift) -> None:
        if self.canvas._text is not self.text:
            return
        if not self.moved and max(abs(dx), abs(dy)) < MOVE_THRESHOLD:
            # Still small enough to be the wobble of a click placing the caret.
            return
        self.moved = True
        self.text.move_to(self.origin[0] + dx, self.origin[1] + dy)
        self.canvas._refresh_text()

    def end(self, x, y, dx, dy, shift) -> None:
        if self.canvas._text is not self.text:
            return
        if not self.moved:
            # A click rather than a drag: put the caret where it landed.
            self.text.caret_at(x, y)
        self.canvas._refresh_text()


class PasteMove(Drag):
    """Carrying a floating paste somewhere else."""

    def __init__(self, canvas: Canvas, paste: FloatingPaste):
        super().__init__(canvas)
        self.paste = paste
        self.origin = (paste.x, paste.y)
        canvas._set_cursor("paste")

    def update(self, x, y, dx, dy, shift) -> None:
        if self.canvas._paste is not self.paste:
            return
        self.paste.move_to(self.origin[0] + dx, self.origin[1] + dy)
        self.canvas._paste_changed()

    # A floating paste stays floating; the drag only moved it.
    end = update


class PasteGrab(Drag):
    """One of a floating paste's grips, taken hold of: to turn it, skew it or stretch it."""

    def __init__(
        self, canvas: Canvas, paste: FloatingPaste, handle: str, x: float, y: float, skew: bool
    ):
        super().__init__(canvas)
        self.paste = paste
        self.handle = handle
        if handle == "rotate":
            self.kind = "rotate"
        elif skew and handle in SIDE_GRIPS:
            self.kind = "skew"
        else:
            self.kind = "resize"
        # How it was, for each move of the pointer to be measured from.
        self.start = (x, y)
        self.grabbed = replace(paste)
        canvas._set_cursor("rotating" if self.kind == "rotate" else handle)

    def update(self, x, y, dx, dy, shift) -> None:
        if self.canvas._paste is not self.paste:
            return
        if self.kind == "rotate":
            self.paste.rotate_from(self.grabbed, self.start, (x, y), snap=shift)
        elif self.kind == "skew":
            self.paste.skew_from(self.grabbed, self.handle, self.start, (x, y))
        else:
            self.paste.resize_from(self.grabbed, self.handle, (x, y))
        self.canvas._paste_changed()

    def end(self, x, y, dx, dy, shift) -> None:
        self.update(x, y, dx, dy, shift)
        self.canvas._set_cursor(None)


class ShapeAdjust(Drag):
    """A grip on a shape waiting to land, or the shape itself, being dragged."""

    def __init__(self, canvas: Canvas, tool: Tool):
        super().__init__(canvas)
        self.tool = tool

    def update(self, x, y, dx, dy, shift) -> None:
        if self.canvas.active_tool is not self.tool or not self.tool.adjustable:
            return
        self.tool.drag_to(x, y, shift)
        self.canvas.queue_draw()

    end = update


class CanvasResize(Drag):
    """One of the picture's own grips, pulling the canvas larger or smaller."""

    def __init__(self, canvas: Canvas, handle: str):
        super().__init__(canvas)
        self.handle = handle
        canvas._resize_size = (canvas._document.width, canvas._document.height)
        canvas._set_cursor(handle)
        canvas.queue_draw()

    def size_at(self, x: float, y: float) -> tuple[int, int]:
        document = self.canvas._document
        width, height = document.width, document.height
        if self.handle in ("e", "se"):
            width = round(x)
        if self.handle in ("s", "se"):
            height = round(y)
        return max(1, min(width, MAX_SIZE)), max(1, min(height, MAX_SIZE))

    def update(self, x, y, dx, dy, shift) -> None:
        canvas = self.canvas
        canvas._resize_size = self.size_at(x, y)
        canvas._sync_content_size()
        canvas.emit("resize-preview", *canvas._resize_size)
        canvas.queue_draw()

    def end(self, x, y, dx, dy, shift) -> None:
        canvas = self.canvas
        canvas._resize_size = None
        if not canvas._document.resize(*self.size_at(x, y)):
            canvas.emit("message", too_large_message(len(canvas._document.layers)))
        canvas._sync_content_size()
        canvas.queue_draw()


class Stroke(Drag):
    """A tool at work: painting, or placing a point of a shape."""

    def update(self, x, y, dx, dy, shift) -> None:
        canvas = self.canvas
        if canvas._drag_context is None or canvas._working:
            return
        canvas._drag_context.constrain = shift
        canvas.active_tool.motion(canvas._drag_context, x, y)
        canvas.queue_draw()

    def end(self, x, y, dx, dy, shift) -> None:
        canvas = self.canvas
        if canvas._drag_context is None:
            return
        canvas._stop_repeat()
        canvas._drag_context.constrain = shift
        if canvas._working:
            # The press is still at work; the stroke ends once it is done.
            canvas._pending_release = (x, y)
            return
        canvas._finish_stroke(x, y)
