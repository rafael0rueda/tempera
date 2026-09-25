# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from ..i18n import _
from .base import ShapeTool


class RectangleTool(ShapeTool):
    id = "rectangle"
    label = _("Rectangle")
    icon_name = "tempera-shape-rectangle-symbolic"

    def render(self, cr, ctx, start, end):
        cr.rectangle(*self.rect(start, end))
        self.paint_shape(cr, ctx)
