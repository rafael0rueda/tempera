# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import math

from ..i18n import _
from .base import ShapeTool


class RoundedRectangleTool(ShapeTool):
    id = "rounded-rectangle"
    label = _("Rounded Rectangle")
    icon_name = "tempera-shape-rounded-rectangle-symbolic"

    def render(self, cr, ctx, start, end):
        x, y, width, height = self.rect(start, end)
        if width <= 0 or height <= 0:
            return
        # The corners stay in proportion to the shape rather than a fixed size,
        # so a small one is not all corner.
        radius = min(width, height) / 5
        cr.new_sub_path()
        cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
        cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
        cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
        cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()
        self.paint_shape(cr, ctx)
