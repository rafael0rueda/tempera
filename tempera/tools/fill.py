# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import cairo
from gi.repository import Gdk

from ..i18n import _
from ..regions import flood_spans, premultiplied, target_at
from .base import Tool, ToolContext

TOLERANCE = 32


# The name the tests and older code know it by.
_premultiplied = premultiplied


def flood_fill(
    surface: cairo.ImageSurface, x: int, y: int, color: Gdk.RGBA, tolerance: int = TOLERANCE
) -> tuple[int, int, int, int] | None:
    """Scanline flood fill over the surface's ARGB32 buffer.

    Returns the rectangle it painted over, or None when it changed nothing.
    """
    width, height = surface.get_width(), surface.get_height()
    if not (0 <= x < width and 0 <= y < height):
        return None

    surface.flush()
    replacement = premultiplied(color)
    target = target_at(surface, x, y)
    # Filling with a colour that still matches the target would never terminate.
    if all(abs(replacement[i] - target[i]) <= tolerance for i in range(4)):
        return None

    stride = surface.get_stride()
    data = surface.get_data()
    replacement_bytes = bytes(replacement)
    # The bounds of everything painted, as [left, right) and [top, bottom).
    bounds = [width, height, 0, 0]
    for row_y, left, right in flood_spans(surface, x, y, tolerance):
        row = row_y * stride
        data[row + left * 4:row + right * 4] = replacement_bytes * (right - left)
        bounds[0] = min(bounds[0], left)
        bounds[1] = min(bounds[1], row_y)
        bounds[2] = max(bounds[2], right)
        bounds[3] = max(bounds[3], row_y + 1)

    surface.mark_dirty()
    left, top, right, bottom = bounds
    return left, top, right - left, bottom - top


class FillTool(Tool):
    id = "fill"
    label = _("Fill")
    icon_name = "tempera-fill-symbolic"
    tip_icon_name = "tempera-fill-tip-symbolic"
    background = True

    def colors_used(self, ctx: ToolContext):
        return (ctx.color,)

    def press(self, ctx: ToolContext, x, y):
        painted = flood_fill(ctx.surface, int(x), int(y), ctx.color, ctx.tolerance)
        if painted is not None:
            left, top, width, height = painted
            ctx.damage(left, top, left + width, top + height)
