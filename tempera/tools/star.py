# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import math

from ..i18n import _
from .base import ShapeTool

POINTS = 5
# The inner corners of a regular five-pointed star, as a share of its outer radius.
INNER_RATIO = math.sin(math.pi / 10) / math.sin(3 * math.pi / 10)


def star_points(x: float, y: float, width: float, height: float) -> list[tuple[float, float]]:
    """The corners of a star fitted into a rectangle, pointing up."""
    cx, cy = x + width / 2, y + height / 2
    corners = []
    for index in range(2 * POINTS):
        scale = 1 if index % 2 == 0 else INNER_RATIO
        angle = -math.pi / 2 + index * math.pi / POINTS
        corners.append(
            (cx + scale * width / 2 * math.cos(angle), cy + scale * height / 2 * math.sin(angle))
        )
    return corners


class StarTool(ShapeTool):
    id = "star"
    label = _("Star")
    icon_name = "tempera-shape-star-symbolic"

    def render(self, cr, ctx, start, end):
        x, y, width, height = self.rect(start, end)
        if width <= 0 or height <= 0:
            return
        corners = star_points(x, y, width, height)
        cr.move_to(*corners[0])
        for corner in corners[1:]:
            cr.line_to(*corner)
        cr.close_path()
        self.paint_shape(cr, ctx)
