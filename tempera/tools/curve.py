# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import cairo

from ..i18n import _
from .base import Tool, distance_to_segment, set_source, snap_45

# A curve takes its line and then this many bends before it lands.
BENDS = 2
# How finely the curve is chopped up to measure a press against it.
SAMPLES = 24


class CurveTool(Tool):
    """A line that is then bent, as in Paint.

    Drag out a straight line, then drag once to bend it towards the pointer and
    once more to bend it again. After the second bend it waits, with a grip on
    each end and on each bend, until it is landed with Enter or moved on from.
    """

    id = "curve"
    label = _("Curve")
    icon_name = "tempera-curve-symbolic"
    fillable = False

    def __init__(self):
        self._start: tuple[float, float] | None = None
        self._end: tuple[float, float] | None = None
        self._controls: list[tuple[float, float]] = []
        self._bends = 0
        # Both bends are in: the curve is waiting to be adjusted or landed.
        self._pending = False
        self._grab: tuple | None = None

    @property
    def in_progress(self) -> bool:
        return self._start is not None

    @property
    def adjustable(self) -> bool:
        return self._pending

    def press(self, ctx, x, y):
        if self._start is None:
            self._start = self._end = (x, y)
            return
        self._bends += 1
        self._bend_to((x, y))

    def _bend_to(self, point: tuple[float, float]) -> None:
        # The first bend pulls the whole curve one way; the second then pulls
        # its far half on its own, which is what makes an S shape possible.
        if self._bends == 1:
            self._controls = [point, point]
        else:
            self._controls[1] = point

    def motion(self, ctx, x, y):
        if self._start is None:
            return
        if self._bends == 0:
            self._end = snap_45(self._start, (x, y)) if ctx.constrain else (x, y)
        else:
            self._bend_to((x, y))

    def release(self, ctx, x, y):
        self.motion(ctx, x, y)
        if self._bends == 0 and self._start == self._end:
            # A click with no line to bend.
            self.cancel()
        elif self._bends >= BENDS:
            self._pending = True

    def _path(self, cr: cairo.Context, ctx) -> None:
        cr.set_line_width(ctx.size)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        set_source(cr, ctx.color)
        cr.move_to(*self._start)
        if self._controls:
            cr.curve_to(*self._controls[0], *self._controls[1], *self._end)
        else:
            cr.line_to(*self._end)

    def draw_preview(self, cr, ctx):
        if self._start is None:
            return
        self._path(cr, ctx)
        cr.stroke()

    def finish(self, ctx):
        if self._start is not None:
            cr = cairo.Context(ctx.surface)
            self._path(cr, ctx)
            cr.stroke()
        self.cancel()

    def cancel(self):
        self._start = self._end = None
        self._controls = []
        self._bends = 0
        self._pending = False
        self._grab = None

    # Adjusting

    def handles(self):
        if not self._pending:
            return {}
        grips = {"start": self._start, "end": self._end}
        if self._controls and self._controls[0] == self._controls[1]:
            # One bend, pulled from a single point: one grip that moves it.
            grips["bend"] = self._controls[0]
        elif self._controls:
            grips["bend1"], grips["bend2"] = self._controls
        return grips

    def _sampled(self) -> list[tuple[float, float]]:
        """The curve chopped into short straight pieces, to measure against."""
        if not self._controls:
            return [self._start, self._end]
        (x0, y0), (x1, y1) = self._start, self._controls[0]
        (x2, y2), (x3, y3) = self._controls[1], self._end
        points = []
        for step in range(SAMPLES + 1):
            t = step / SAMPLES
            u = 1 - t
            a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
            points.append((a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3))
        return points

    def bounds(self):
        if not self._pending:
            return None
        points = self._sampled()
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)

    def contains(self, x, y, reach):
        if not self._pending:
            return False
        points = self._sampled()
        return any(
            distance_to_segment((x, y), points[index], points[index + 1]) <= reach
            for index in range(len(points) - 1)
        )

    def grab(self, handle, x, y):
        if self._pending:
            self._grab = (handle, self._start, self._end, list(self._controls), (x, y))

    def drag_to(self, x, y, constrain=False):
        if self._grab is None:
            return
        handle, start, end, controls, origin = self._grab
        point = (x, y)
        if handle is None:
            dx, dy = x - origin[0], y - origin[1]
            self._start = (start[0] + dx, start[1] + dy)
            self._end = (end[0] + dx, end[1] + dy)
            self._controls = [(cx + dx, cy + dy) for cx, cy in controls]
        elif handle == "start":
            self._start = snap_45(end, point) if constrain else point
        elif handle == "end":
            self._end = snap_45(start, point) if constrain else point
        elif handle == "bend":
            self._controls = [point, point]
        else:
            self._controls[0 if handle == "bend1" else 1] = point

    def move_by(self, dx, dy):
        if not self._pending:
            return
        self._start = (self._start[0] + dx, self._start[1] + dy)
        self._end = (self._end[0] + dx, self._end[1] + dy)
        self._controls = [(x + dx, y + dy) for x, y in self._controls]
