# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import cairo
from gi.repository import Gdk


@dataclass
class ToolContext:
    """Everything a tool needs for one interaction, handed over by the canvas."""

    surface: cairo.ImageSurface
    primary: Gdk.RGBA
    secondary: Gdk.RGBA
    button: int
    size: int
    fill_shapes: bool
    pick_color: Callable[[Gdk.RGBA, int], None]
    begin_text: Callable[[float, float, Gdk.RGBA], None]
    select_region: Callable[[float, float, float, float], None]
    # Shift held: squares up a shape or snaps a line to a 45° angle.
    constrain: bool = False
    # Whether a shape that can be filled also gets its outline drawn.
    outline_shapes: bool = True
    # The eraser rubs back to transparency rather than to the secondary color.
    erase_to_transparency: bool = False
    # How far from the color under the pointer a flood fill still spreads.
    tolerance: int = 32
    # How thickly the airbrush sprays, from 1 to 100.
    density: int = 50
    # How close, in image pixels, a click must land to hit a point already
    # placed, such as the first corner of a polygon being closed.
    reach: float = 4.0
    # Hands a hand-drawn outline to the canvas as the selection.
    select_outline: Callable[[list[tuple[float, float]]], None] | None = None

    @property
    def color(self) -> Gdk.RGBA:
        return self.secondary if self.button == Gdk.BUTTON_SECONDARY else self.primary

    @property
    def alt_color(self) -> Gdk.RGBA:
        return self.primary if self.button == Gdk.BUTTON_SECONDARY else self.secondary


def set_source(cr: cairo.Context, color: Gdk.RGBA) -> None:
    cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)


def draw_marquee(cr: cairo.Context, x: float, y: float, width: float, height: float) -> None:
    """The dashed outline of a selection: black over white, so it reads on any artwork."""
    cr.save()
    # Half a screen pixel in from the edge, so the line lands on whole pixels.
    half = 0.5 / cr.user_to_device_distance(1, 0)[0]
    cr.rectangle(x + half, y + half, max(width - 2 * half, 0), max(height - 2 * half, 0))
    _stroke_marquee(cr)
    cr.restore()


def draw_outline_marquee(cr: cairo.Context, outline, closed: bool = True) -> None:
    """The same dashes, along a hand-drawn outline rather than a rectangle."""
    if len(outline) < 2:
        return
    cr.save()
    cr.move_to(*outline[0])
    for point in outline[1:]:
        cr.line_to(*point)
    if closed:
        cr.close_path()
    _stroke_marquee(cr)
    cr.restore()


def _stroke_marquee(cr: cairo.Context) -> None:
    # One screen pixel wide and dashed in screen pixels, whatever the zoom.
    x_scale, _y_scale = cr.user_to_device_distance(1, 0)
    cr.set_line_width(1 / x_scale)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.set_source_rgb(1, 1, 1)
    cr.stroke_preserve()
    cr.set_dash([4 / x_scale, 4 / x_scale])
    cr.set_source_rgb(0, 0, 0)
    cr.stroke()


class Tool:
    id = ""
    label = ""
    icon_name = ""
    # The part of the icon that paints, drawn over it in the primary colour.
    tip_icon_name = ""
    mutates = True
    # Whether the size in the tool options applies: a brush width, a line
    # width, or for text the font size.
    sized = False
    # Above 0, the canvas calls repeat() this often (in ms) while the button is
    # held, even when the pointer does not move.
    repeat_ms = 0

    def press(self, ctx: ToolContext, x: float, y: float) -> None:
        pass

    def motion(self, ctx: ToolContext, x: float, y: float) -> None:
        pass

    def release(self, ctx: ToolContext, x: float, y: float) -> None:
        pass

    def draw_preview(self, cr: cairo.Context, ctx: ToolContext) -> None:
        pass

    def repeat(self, ctx: ToolContext) -> None:
        pass

    # Tools that take several clicks, such as the polygon, stay in progress
    # between drags. The canvas keeps drawing their preview, sends them the
    # pointer as it hovers, and lets Enter finish them or Esc drop them.

    @property
    def in_progress(self) -> bool:
        return False

    def hover(self, x: float, y: float) -> None:
        pass

    def finish(self, ctx: ToolContext) -> None:
        """Draw what has been placed so far into the image."""

    def cancel(self) -> None:
        pass

    # A shape that has been drawn but not yet landed is adjustable: it shows
    # grips the canvas can hand back drags for, and can be moved as a whole
    # until Enter, another tool, or a press away from it lands it.

    @property
    def adjustable(self) -> bool:
        return False

    def handles(self) -> dict[str, tuple[float, float]]:
        """Where the grips sit, in image pixels, named for the cursor they take."""
        return {}

    def frame(self) -> tuple[float, float, float, float] | None:
        """The dashed outline to draw around the shape, for the ones grips box in."""
        return None

    def bounds(self) -> tuple[float, float, float, float] | None:
        """Everything the shape covers, for deciding how near a grip a press is."""
        return None

    def contains(self, x: float, y: float, reach: float) -> bool:
        """Whether a press there has hold of the shape, to drag it somewhere else."""
        return False

    def grab(self, handle: str | None, x: float, y: float) -> None:
        """Start adjusting: a grip by name, or the whole shape with None."""

    def drag_to(self, x: float, y: float, constrain: bool = False) -> None:
        """Carry on the adjustment the pointer is now here."""

    def move_by(self, dx: float, dy: float) -> None:
        """Shift the whole shape, for the arrow keys."""


class FreehandTool(Tool):
    """Draws a continuous stroke straight onto the document surface."""

    sized = True

    antialias = True
    line_cap = cairo.LINE_CAP_ROUND

    def __init__(self):
        self._last: tuple[float, float] | None = None

    def stroke_color(self, ctx: ToolContext) -> Gdk.RGBA:
        return ctx.color

    def _context(self, ctx: ToolContext) -> cairo.Context:
        cr = cairo.Context(ctx.surface)
        if not self.antialias:
            cr.set_antialias(cairo.ANTIALIAS_NONE)
        # A see-through color paints over what is there; an opaque one replaces
        # it, which is what lets the eraser rub back to transparency.
        color = self.stroke_color(ctx)
        cr.set_operator(
            cairo.OPERATOR_OVER if 0 < color.alpha < 1 else cairo.OPERATOR_SOURCE
        )
        cr.set_line_width(ctx.size)
        cr.set_line_cap(self.line_cap)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        set_source(cr, color)
        return cr

    def _snap(self, value: float) -> float:
        # Hard-edged tools need half-pixel offsets to land on whole pixels.
        return value if self.antialias else int(value) + 0.5

    def _dot(self, cr: cairo.Context, ctx: ToolContext, x: float, y: float) -> None:
        # Cairo renders nothing for a zero-length segment unless the cap is round,
        # so a click that never moves has to paint its own dot.
        radius = ctx.size / 2
        if self.line_cap == cairo.LINE_CAP_ROUND:
            cr.arc(x, y, radius, 0, 2 * math.pi)
        else:
            cr.rectangle(x - radius, y - radius, ctx.size, ctx.size)
        cr.fill()

    def press(self, ctx, x, y):
        x, y = self._snap(x), self._snap(y)
        self._last = (x, y)
        self._dot(self._context(ctx), ctx, x, y)

    def motion(self, ctx, x, y):
        if self._last is None:
            return
        x, y = self._snap(x), self._snap(y)
        cr = self._context(ctx)
        cr.move_to(*self._last)
        cr.line_to(x, y)
        cr.stroke()
        self._last = (x, y)

    def release(self, ctx, x, y):
        self.motion(ctx, x, y)
        self._last = None


def rect_handles(
    x: float, y: float, width: float, height: float
) -> dict[str, tuple[float, float]]:
    """The eight grips of a rectangle, named after the compass point they sit on."""
    return {
        "nw": (x, y),
        "n": (x + width / 2, y),
        "ne": (x + width, y),
        "w": (x, y + height / 2),
        "e": (x + width, y + height / 2),
        "sw": (x, y + height),
        "s": (x + width / 2, y + height),
        "se": (x + width, y + height),
    }


def distance_to_segment(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    """How far a point is from the line between two others, as drawn rather than extended."""
    px, py = point
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    length = dx * dx + dy * dy
    if length == 0:
        return math.hypot(px - sx, py - sy)
    # Where along the segment the point falls, kept between its two ends.
    along = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / length))
    return math.hypot(px - (sx + along * dx), py - (sy + along * dy))


def resize_box(
    handle: str,
    rect: tuple[float, float, float, float],
    x: float,
    y: float,
    constrain: bool = False,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """A rectangle with one grip dragged to a point, as its two opposite corners.

    The sides the grip does not touch stay where they are, and a side never
    crosses the one facing it. Constrained, the shape squares up around the
    corner the grip is pulling away from.
    """
    left, top, width, height = rect
    right, bottom = left + width, top + height
    if "w" in handle:
        left = min(x, right)
    elif "e" in handle:
        right = max(x, left)
    if "n" in handle:
        top = min(y, bottom)
    elif "s" in handle:
        bottom = max(y, top)
    if constrain:
        size = max(right - left, bottom - top)
        if "w" in handle:
            left = right - size
        else:
            right = left + size
        if "n" in handle:
            top = bottom - size
        else:
            bottom = top + size
    return (left, top), (right, bottom)


def snap_45(origin: tuple[float, float], point: tuple[float, float]) -> tuple[float, float]:
    """Turn the line from origin to point to the nearest 45° angle, keeping its length."""
    x, y = point
    sx, sy = origin
    dx, dy = x - sx, y - sy
    angle = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
    length = math.hypot(dx, dy)
    return (sx + length * math.cos(angle), sy + length * math.sin(angle))


class ShapeTool(Tool):
    """Rubber-bands a shape while dragging, then holds it adjustable until it lands."""

    # Whether "Fill shape" applies: closed shapes have an inside to fill.
    fillable = True
    # Whether the grips box the shape in. A line has no box to stretch, so it
    # is dragged by its two ends instead.
    box_handles = True

    def __init__(self):
        self._start: tuple[float, float] | None = None
        self._current: tuple[float, float] | None = None
        # The drag is over and the shape is waiting to be adjusted or landed.
        self._pending = False
        # Where the shape and the pointer were when a grip was taken hold of.
        self._grab: tuple[str | None, tuple, tuple, tuple] | None = None

    @property
    def in_progress(self) -> bool:
        return self._pending

    @property
    def adjustable(self) -> bool:
        return self._pending

    def press(self, ctx, x, y):
        self._start = (x, y)
        self._current = (x, y)
        self._pending = False

    def motion(self, ctx, x, y):
        self._current = self._constrain((x, y)) if ctx.constrain else (x, y)

    def release(self, ctx, x, y):
        self._current = self._constrain((x, y)) if ctx.constrain else (x, y)
        if self._start is None or self._start == self._current:
            # A press that never moved places nothing, the way a click is no curve.
            self.cancel()
            return
        self._pending = True

    def draw_preview(self, cr, ctx):
        if self._start is not None and self._current is not None:
            self.render(cr, ctx, self._start, self._current)

    def finish(self, ctx):
        start, end = self._start, self._current
        self.cancel()
        if start is None or end is None:
            return
        cr = cairo.Context(ctx.surface)
        self.render(cr, ctx, start, end)

    def cancel(self):
        self._start = None
        self._current = None
        self._pending = False
        self._grab = None

    # Adjusting

    def handles(self):
        if not self._pending:
            return {}
        if self.box_handles:
            return rect_handles(*self.rect(self._start, self._current))
        return {"start": self._start, "end": self._current}

    def frame(self):
        if not self._pending or not self.box_handles:
            return None
        return self.rect(self._start, self._current)

    def bounds(self):
        if not self._pending:
            return None
        return self.rect(self._start, self._current)

    def contains(self, x, y, reach):
        if not self._pending:
            return False
        if self.box_handles:
            bx, by, width, height = self.rect(self._start, self._current)
            return bx - reach <= x <= bx + width + reach and by - reach <= y <= by + height + reach
        return distance_to_segment((x, y), self._start, self._current) <= reach

    def grab(self, handle, x, y):
        if self._pending:
            self._grab = (handle, self._start, self._current, (x, y))

    def drag_to(self, x, y, constrain=False):
        if self._grab is None:
            return
        handle, start, end, origin = self._grab
        if handle is None:
            dx, dy = x - origin[0], y - origin[1]
            self._start = (start[0] + dx, start[1] + dy)
            self._current = (end[0] + dx, end[1] + dy)
        elif self.box_handles:
            self._start, self._current = resize_box(
                handle, self.rect(start, end), x, y, constrain
            )
        elif handle == "start":
            self._start = snap_45(end, (x, y)) if constrain else (x, y)
        else:
            self._current = snap_45(start, (x, y)) if constrain else (x, y)

    def move_by(self, dx, dy):
        if not self._pending:
            return
        self._start = (self._start[0] + dx, self._start[1] + dy)
        self._current = (self._current[0] + dx, self._current[1] + dy)

    def render(self, cr, ctx, start, end) -> None:
        raise NotImplementedError

    def _constrain(self, point: tuple[float, float]) -> tuple[float, float]:
        """Square up the drag: equal width and height, same direction as the drag."""
        x, y = point
        sx, sy = self._start
        size = max(abs(x - sx), abs(y - sy))
        return (sx + size * (1 if x >= sx else -1), sy + size * (1 if y >= sy else -1))

    @staticmethod
    def rect(start, end) -> tuple[float, float, float, float]:
        x = min(start[0], end[0])
        y = min(start[1], end[1])
        return x, y, abs(end[0] - start[0]), abs(end[1] - start[1])

    def paint_shape(self, cr, ctx) -> None:
        paint_shape(cr, ctx)


def paint_shape(cr: cairo.Context, ctx: ToolContext) -> None:
    """Fill the path with the alternate color when filling is on, then stroke its outline.

    With neither asked for, the outline is drawn anyway: a shape that leaves no
    mark would look like the tool had stopped working.
    """
    cr.set_line_width(ctx.size)
    cr.set_line_join(cairo.LINE_JOIN_MITER)
    if ctx.fill_shapes:
        set_source(cr, ctx.alt_color)
        cr.fill_preserve()
    if ctx.outline_shapes or not ctx.fill_shapes:
        set_source(cr, ctx.color)
        cr.stroke()
    else:
        cr.new_path()
