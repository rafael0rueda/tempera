# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from ..i18n import _
from .base import ShapeTool


class TriangleTool(ShapeTool):
    """An upright isosceles triangle filling the dragged rectangle."""

    id = "triangle"
    label = _("Triangle")
    icon_name = "tempera-shape-triangle-symbolic"

    def render(self, cr, ctx, start, end):
        x, y, width, height = self.rect(start, end)
        if width <= 0 or height <= 0:
            return
        cr.move_to(x + width / 2, y)
        cr.line_to(x + width, y + height)
        cr.line_to(x, y + height)
        cr.close_path()
        self.paint_shape(cr, ctx)
