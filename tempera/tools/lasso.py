# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import math

from ..i18n import _
from .base import Tool, draw_outline_marquee

# Pointer moves shorter than this, in image pixels, add no point to the outline:
# a slow hand would otherwise leave thousands of them.
MIN_STEP = 1.0


class LassoTool(Tool):
    """Draws a selection by hand; letting go closes the outline back to where it began."""

    id = "lasso"
    label = _("Free Select")
    icon_name = "tempera-select-free-symbolic"
    # Picking a region changes nothing in the image; moving or deleting it later does.
    mutates = False

    def __init__(self):
        self._outline: list[tuple[float, float]] = []

    def press(self, ctx, x, y):
        self._outline = [(x, y)]

    def motion(self, ctx, x, y):
        if not self._outline:
            return
        last_x, last_y = self._outline[-1]
        if math.hypot(x - last_x, y - last_y) >= MIN_STEP:
            self._outline.append((x, y))

    def release(self, ctx, x, y):
        self.motion(ctx, x, y)
        outline, self._outline = self._outline, []
        # Too little to enclose anything is a plain click, which drops the selection.
        if ctx.select_outline is not None:
            ctx.select_outline(outline)

    def draw_preview(self, cr, ctx):
        draw_outline_marquee(cr, self._outline, closed=False)
