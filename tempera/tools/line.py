# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import cairo

from ..i18n import _
from .base import ShapeTool, set_source, snap_45


class LineTool(ShapeTool):
    id = "line"
    label = _("Line")
    icon_name = "tempera-line-symbolic"
    fillable = False
    # No box to stretch: a line is adjusted by the grips on its two ends.
    box_handles = False

    def render(self, cr, ctx, start, end):
        cr.set_line_width(ctx.size)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        set_source(cr, ctx.color)
        cr.move_to(*start)
        cr.line_to(*end)
        cr.stroke()

    def _constrain(self, point):
        """Snap the drag to the nearest 45° angle, keeping its length."""
        return snap_45(self._start, point)
