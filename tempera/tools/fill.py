# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import cairo
from gi.repository import Gdk

from ..i18n import _
from ..regions import flood_spans, premultiplied, target_at
from .base import Tool, ToolContext

TOLERANCE = 32


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
    replacement_bytes = bytes(premultiplied(color))
    # A colour close to the one clicked on is still a fill: every pixel
    # within the tolerance takes it. The search reads each row before any of
    # it is painted, so it ends whatever the colour.
    if tolerance == 0 and replacement_bytes == target_at(surface, x, y):
        return None

    stride = surface.get_stride()
    data = surface.get_data()
    # The bounds of everything painted, as [left, right) and [top, bottom).
    bounds = [width, height, 0, 0]
    for row_y, left, right in flood_spans(surface, x, y, tolerance):
        row = row_y * stride
        run = replacement_bytes * (right - left)
        if data[row + left * 4:row + right * 4] == run:
            # Already this colour: not something it painted.
            continue
        data[row + left * 4:row + right * 4] = run
        bounds[0] = min(bounds[0], left)
        bounds[1] = min(bounds[1], row_y)
        bounds[2] = max(bounds[2], right)
        bounds[3] = max(bounds[3], row_y + 1)

    surface.mark_dirty()
    left, top, right, bottom = bounds
    if right <= left:
        return None
    return left, top, right - left, bottom - top


class FillTool(Tool):
    id = "fill"
    options_page = "fill"
    tolerance = "fill_tolerance"
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
