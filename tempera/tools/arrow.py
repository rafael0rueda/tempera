# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import math

import cairo

from ..i18n import _
from .base import set_source
from .line import LineTool


def head_length(size: int) -> float:
    """How long the arrowhead is for a line this thick; it grows with the brush."""
    return 3 * size + 8


class ArrowTool(LineTool):
    """A line with a solid head at the end the drag finished on."""

    id = "arrow"
    label = _("Arrow")
    icon_name = "tempera-shape-arrow-symbolic"

    def render(self, cr, ctx, start, end):
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        if length == 0:
            return
        ux, uy = (end[0] - start[0]) / length, (end[1] - start[1]) / length
        # A short drag is all head, rather than a shaft poking out of its tip.
        head = min(head_length(ctx.size), length)
        half_width = 0.6 * head_length(ctx.size)
        base = (end[0] - ux * head, end[1] - uy * head)

        set_source(cr, ctx.color)
        if length > head:
            # The round cap at the base is hidden inside the head, which is
            # widest there.
            cr.set_line_width(ctx.size)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.move_to(*start)
            cr.line_to(*base)
            cr.stroke()

        cr.move_to(*end)
        cr.line_to(base[0] - uy * half_width, base[1] + ux * half_width)
        cr.line_to(base[0] + uy * half_width, base[1] - ux * half_width)
        cr.close_path()
        cr.fill()
