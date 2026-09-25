# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import math

from ..i18n import _
from .base import ShapeTool


class EllipseTool(ShapeTool):
    id = "ellipse"
    label = _("Ellipse")
    icon_name = "tempera-shape-ellipse-symbolic"

    def render(self, cr, ctx, start, end):
        x, y, width, height = self.rect(start, end)
        if width <= 0 or height <= 0:
            return
        cr.save()
        cr.translate(x + width / 2, y + height / 2)
        cr.scale(width / 2, height / 2)
        cr.arc(0, 0, 1, 0, 2 * math.pi)
        cr.restore()
        self.paint_shape(cr, ctx)
