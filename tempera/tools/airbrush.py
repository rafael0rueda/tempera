# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import math
import random

from ..i18n import _
from .base import FreehandTool

DENSITY_RANGE = (1, 100)
DEFAULT_DENSITY = 50
# How often the airbrush sprays again while the button is held still.
SPRAY_INTERVAL_MS = 30
# Dots per spray for each square pixel of the spray circle at full density: at
# 100 a circle is mostly covered after about a second held in one place.
_DOTS_PER_AREA = 0.08


def dots_per_spray(size: int, density: int) -> int:
    area = math.pi * (size / 2) ** 2
    return max(1, round(area * density / 100 * _DOTS_PER_AREA))


class AirbrushTool(FreehandTool):
    """Sprays dots at random inside a circle the size of the brush, for as long as it is held."""

    id = "airbrush"
    label = _("Airbrush")
    icon_name = "tempera-airbrush-symbolic"
    tip_icon_name = "tempera-airbrush-tip-symbolic"
    repeat_ms = SPRAY_INTERVAL_MS

    def __init__(self, seed: int | None = None):
        super().__init__()
        self.random = random.Random(seed)
        self._point: tuple[float, float] | None = None

    def _spray(self, ctx) -> None:
        cr = self._context(ctx)
        radius = ctx.size / 2
        cx, cy = self._point
        for _dot in range(dots_per_spray(ctx.size, ctx.density)):
            # The square root spreads the dots evenly over the circle rather
            # than bunching them in the middle.
            distance = radius * math.sqrt(self.random.random())
            angle = 2 * math.pi * self.random.random()
            x = math.floor(cx + distance * math.cos(angle))
            y = math.floor(cy + distance * math.sin(angle))
            cr.rectangle(x, y, 1, 1)
        cr.fill()

    def press(self, ctx, x, y):
        self._point = (x, y)
        self._spray(ctx)

    def motion(self, ctx, x, y):
        if self._point is None:
            return
        self._point = (x, y)
        self._spray(ctx)

    def repeat(self, ctx):
        if self._point is not None:
            self._spray(ctx)

    def release(self, ctx, x, y):
        self._point = None
