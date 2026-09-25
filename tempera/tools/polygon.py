# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import math

import cairo

from ..i18n import _
from .base import Tool, distance_to_segment, paint_shape, set_source, snap_45


class PolygonTool(Tool):
    """A shape of straight sides, placed one corner at a time.

    Drag out the first side, or click its first corner, then click each corner
    after it. Clicking the first corner again closes the shape; so does clicking
    the last corner twice, or pressing Enter. Once closed it waits, with a grip
    on every corner, until it is landed.
    """

    id = "polygon"
    label = _("Polygon")
    icon_name = "tempera-shape-polygon-symbolic"
    fillable = True

    def __init__(self):
        self._points: list[tuple[float, float]] = []
        # Where the pointer hovers between clicks, for the side still to come.
        self._hover: tuple[float, float] | None = None
        # The press landed on a corner already placed, so its release closes the shape.
        self._closing = False
        self._dragging = False
        # Closed, and waiting to be adjusted or landed.
        self._pending = False
        self._grab: tuple | None = None

    @property
    def in_progress(self) -> bool:
        return bool(self._points)

    @property
    def adjustable(self) -> bool:
        return self._pending

    @property
    def points(self) -> list[tuple[float, float]]:
        return list(self._points)

    @staticmethod
    def _near(a: tuple[float, float], b: tuple[float, float], reach: float) -> bool:
        return math.hypot(a[0] - b[0], a[1] - b[1]) <= reach

    def press(self, ctx, x, y):
        self._hover = None
        self._dragging = True
        if not self._points:
            # The first corner, and the second following the drag from it.
            self._points = [(x, y), (x, y)]
            return
        closes_at_start = len(self._points) >= 3 and self._near((x, y), self._points[0], ctx.reach)
        if closes_at_start or self._near((x, y), self._points[-1], ctx.reach):
            self._closing = True
            return
        self._points.append((x, y))

    def motion(self, ctx, x, y):
        if self._closing or len(self._points) < 2:
            return
        point = (x, y)
        if ctx.constrain:
            point = snap_45(self._points[-2], point)
        self._points[-1] = point

    def release(self, ctx, x, y):
        self.motion(ctx, x, y)
        self._dragging = False
        if self._closing:
            self._closing = False
            self._pending = True
            return
        if len(self._points) == 2 and self._near(self._points[0], self._points[1], ctx.reach):
            # A click rather than a drag: only the first corner is placed.
            self._points.pop()

    def hover(self, x, y):
        if self._pending:
            # Closed: no side is still to come.
            return
        self._hover = (x, y)

    def draw_preview(self, cr, ctx):
        if not self._points:
            return
        if self._pending:
            self._paint(cr, ctx, self._points)
            return
        points = list(self._points)
        if self._hover is not None and not self._dragging:
            points.append(self._hover)
        cr.set_line_width(ctx.size)
        cr.set_line_join(cairo.LINE_JOIN_MITER)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        set_source(cr, ctx.color)
        cr.move_to(*points[0])
        for point in points[1:]:
            cr.line_to(*point)
        if len(points) == 1:
            # Cairo draws a round-capped dot for a path that goes nowhere.
            cr.close_path()
        cr.stroke()

    @staticmethod
    def _paint(cr: cairo.Context, ctx, points: list[tuple[float, float]]) -> None:
        """The closed shape, or the single side that two corners make."""
        cr.move_to(*points[0])
        for point in points[1:]:
            cr.line_to(*point)
        if len(points) == 2:
            # Two corners make only a side, which has no inside to fill.
            cr.set_line_width(ctx.size)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            set_source(cr, ctx.color)
            cr.stroke()
            return
        cr.close_path()
        paint_shape(cr, ctx)

    def finish(self, ctx):
        points = self._points
        self.cancel()
        if len(points) < 2:
            return
        self._paint(cairo.Context(ctx.surface), ctx, points)

    def cancel(self):
        self._points = []
        self._hover = None
        self._closing = False
        self._dragging = False
        self._pending = False
        self._grab = None

    # Adjusting

    def handles(self):
        if not self._pending:
            return {}
        return {f"corner-{index}": point for index, point in enumerate(self._points)}

    def bounds(self):
        if not self._pending:
            return None
        xs = [x for x, _y in self._points]
        ys = [y for _x, y in self._points]
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)

    def contains(self, x, y, reach):
        if not self._pending:
            return False
        sides = list(zip(self._points, self._points[1:] + self._points[:1]))
        if len(self._points) == 2:
            # Only a side: what there is to take hold of is the line itself.
            sides = sides[:1]
        elif self._inside((x, y)):
            return True
        return any(distance_to_segment((x, y), start, end) <= reach for start, end in sides)

    def _inside(self, point: tuple[float, float]) -> bool:
        """Whether a point falls within the closed outline, by counting crossings."""
        x, y = point
        inside = False
        for (ax, ay), (bx, by) in zip(self._points, self._points[1:] + self._points[:1]):
            if (ay > y) != (by > y) and x < ax + (y - ay) / (by - ay) * (bx - ax):
                inside = not inside
        return inside

    def grab(self, handle, x, y):
        if self._pending:
            self._grab = (handle, list(self._points), (x, y))

    def drag_to(self, x, y, constrain=False):
        if self._grab is None:
            return
        handle, points, origin = self._grab
        if handle is None:
            dx, dy = x - origin[0], y - origin[1]
            self._points = [(px + dx, py + dy) for px, py in points]
            return
        index = int(handle.split("-")[1])
        point = (x, y)
        if constrain:
            # Square on to the corner before it, the way placing a side does.
            point = snap_45(points[index - 1], point)
        self._points[index] = point

    def move_by(self, dx, dy):
        if not self._pending:
            return
        self._points = [(x + dx, y + dy) for x, y in self._points]
