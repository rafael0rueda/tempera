# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import math

import cairo

from ..i18n import _
from .base import set_source, stroke_outline
from .line import LineTool


def head_length(size: int) -> float:
    """How long the arrowhead is for a line this thick; it grows with the brush."""
    return 3 * size + 8


class ArrowTool(LineTool):
    """A line with a solid head at the end the drag finished on, or at both ends."""

    id = "arrow"
    label = _("Arrow")
    icon_name = "tempera-shape-arrow-symbolic"

    def render(self, cr, ctx, start, end):
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        if length == 0:
            return
        ux, uy = (end[0] - start[0]) / length, (end[1] - start[1]) / length
        both = ctx.arrow_ends == "both"
        # A short drag is all head, rather than a shaft poking out of its
        # tip; with two heads, each gets half of it.
        head = min(head_length(ctx.size), length / 2 if both else length)
        half_width = 0.6 * head_length(ctx.size)
        tips = [(end, (ux, uy))] + ([(start, (-ux, -uy))] if both else [])

        set_source(cr, ctx.color)
        shaft_start = (start[0] + ux * head, start[1] + uy * head) if both else start
        shaft_end = (end[0] - ux * head, end[1] - uy * head)
        if length > head * len(tips):
            # The round cap at a base is hidden inside the head, which is
            # widest there.
            cr.set_line_width(ctx.size)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.move_to(*shaft_start)
            cr.line_to(*shaft_end)
            stroke_outline(cr, ctx)

        for tip, (dx, dy) in tips:
            base = (tip[0] - dx * head, tip[1] - dy * head)
            cr.move_to(*tip)
            cr.line_to(base[0] - dy * half_width, base[1] + dx * half_width)
            cr.line_to(base[0] + dy * half_width, base[1] - dx * half_width)
            cr.close_path()
            cr.fill()
