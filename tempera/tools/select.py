# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from ..i18n import _
from .base import ShapeTool, Tool, draw_marquee


class SelectTool(Tool):
    """Rubber-bands a rectangle and hands it to the canvas as the selection."""

    id = "select"
    label = _("Select")
    icon_name = "tempera-select-rectangle-symbolic"
    # Picking a region changes nothing in the image; moving or deleting it later does.
    mutates = False

    def __init__(self):
        self._start: tuple[float, float] | None = None
        self._current: tuple[float, float] | None = None

    def press(self, ctx, x, y):
        self._start = (x, y)
        self._current = (x, y)

    def motion(self, ctx, x, y):
        self._current = (x, y)

    def release(self, ctx, x, y):
        if self._start is not None:
            # An empty rectangle is a plain click, which drops the selection.
            ctx.select_region(*ShapeTool.rect(self._start, (x, y)))
        self._start = None
        self._current = None

    def draw_preview(self, cr, ctx):
        if self._start is not None and self._current is not None:
            draw_marquee(cr, *ShapeTool.rect(self._start, self._current))
