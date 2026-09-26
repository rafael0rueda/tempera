# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The canvas's selection: making it, and cutting, cropping or lifting it."""

from __future__ import annotations


import cairo

from ..selection import Selection
from ..tools import SELECTION_TOOL_IDS


class SelectionMixin:
    """The selection: made by the select tools, then cut, cropped, deleted or lifted."""

    @property
    def selecting(self) -> bool:
        """Whether a selection tool is the one holding the pointer."""
        return self.active_tool.id in SELECTION_TOOL_IDS

    @property
    def has_selection(self) -> bool:
        return self._selection is not None

    @property
    def selection_size(self) -> tuple[int, int] | None:
        """How big the selection is, for the readout in the bottom bar."""
        if self._selection is None:
            return None
        return self._selection.width, self._selection.height

    def set_selection(self, selection: Selection | None) -> None:
        if selection == self._selection:
            return
        self._selection = selection
        self.queue_draw()
        self.emit("selection-changed")

    def select_region(self, x: float, y: float, width: float, height: float) -> None:
        """Take the rectangle the select tool just dragged out."""
        self.set_selection(
            Selection.from_rect(x, y, width, height, self._document.width, self._document.height)
        )
        if self._selection is not None:
            # Esc and Delete belong to the selection from here on.
            self.grab_focus()

    def select_outline(self, outline: list[tuple[float, float]]) -> None:
        """Take the outline the lasso just drew."""
        self.set_selection(
            Selection.from_outline(outline, self._document.width, self._document.height)
        )
        if self._selection is not None:
            self.grab_focus()

    def select_pixels(self, selection: Selection | None) -> None:
        """Take a selection picked out pixel by pixel, as the magic wand's is."""
        self.set_selection(selection)
        if self._selection is not None:
            self.grab_focus()

    def select_all(self) -> None:
        self.commit_floating()
        self.select_region(0, 0, self._document.width, self._document.height)

    def _selection_at(self, x: float, y: float) -> "Selection | None":
        """The selection under a point, when the select tool is there to grab it."""
        if not self.selecting or self._selection is None:
            return None
        return self._selection if self._selection.contains(x, y) else None

    def clear_selection(self) -> bool:
        if self._selection is None:
            return False
        self.set_selection(None)
        return True

    def selection_surface(self) -> cairo.ImageSurface | None:
        """A copy of the selected pixels, for the clipboard."""
        if self._selection is None:
            return None
        return self._selection.pixels(self._document.surface)

    def delete_selection(self) -> bool:
        if self._selection is None:
            return False
        self._document.erase(self._selection.rect, mask=self._selection.mask)
        self.set_selection(None)
        return True

    def crop_to_selection(self) -> bool:
        if self._selection is None:
            return False
        self._document.crop_to(*self._selection.rect, mask=self._selection.mask)
        self.set_selection(None)
        return True

    def _lift_selection(self, copy: bool) -> None:
        """Float the selected pixels so the drag can carry them somewhere else."""
        selection = self._selection
        surface = selection.pixels(self._document.surface)
        self.set_selection(None)
        self.begin_paste(
            surface,
            selection.x,
            selection.y,
            source=None if copy else selection.rect,
            source_mask=None if copy else selection.mask,
        )
