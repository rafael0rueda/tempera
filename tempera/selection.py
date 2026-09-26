# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import cached_property

import cairo

from .document import crop_surface, keep_inside
from .regions import flood_spans, spans_mask

Point = tuple[float, float]


def _has_pixels(mask: cairo.ImageSurface) -> bool:
    mask.flush()
    return any(mask.get_data())


def _extent(mask: cairo.ImageSurface) -> tuple[int, int, int, int] | None:
    """The smallest rectangle holding every covered pixel of a mask, or None if it is empty."""
    mask.flush()
    data, stride, width = mask.get_data(), mask.get_stride(), mask.get_width()
    rows = [row for row in range(mask.get_height()) if any(data[row * stride : row * stride + width])]
    if not rows:
        return None
    # The rows laid over each other, as one number, show every column in use.
    columns = 0
    for row in rows:
        columns |= int.from_bytes(data[row * stride : row * stride + width], "big")
    used = columns.to_bytes(width, "big")
    left = next(index for index, value in enumerate(used) if value)
    right = width - next(index for index, value in enumerate(reversed(used)) if value)
    return left, rows[0], right - left, rows[-1] + 1 - rows[0]


def outline_mask(outline: list[Point], x: int, y: int, width: int, height: int) -> cairo.ImageSurface:
    """The inside of an outline, as a mask covering the rectangle at (x, y).

    Hard-edged, like the pixels a pencil sets, so that a cut-out moved or
    deleted leaves no half-covered fringe behind. Where the outline crosses
    itself, the loops it makes are all inside.
    """
    mask = cairo.ImageSurface(cairo.FORMAT_A8, width, height)
    cr = cairo.Context(mask)
    cr.set_antialias(cairo.ANTIALIAS_NONE)
    cr.set_fill_rule(cairo.FILL_RULE_WINDING)
    cr.translate(-x, -y)
    cr.move_to(*outline[0])
    for point in outline[1:]:
        cr.line_to(*point)
    cr.close_path()
    cr.fill()
    return mask


def _crop_mask(mask: cairo.ImageSurface, x: int, y: int, width: int, height: int) -> cairo.ImageSurface:
    cropped = cairo.ImageSurface(cairo.FORMAT_A8, width, height)
    cr = cairo.Context(cropped)
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_surface(mask, -x, -y)
    cr.paint()
    return cropped


@dataclass
class Selection:
    """Part of the image, picked out to be moved, copied or deleted.

    A rectangle, and for a hand-drawn selection also a mask the size of that
    rectangle saying which of its pixels are inside the outline. Without a
    mask the whole rectangle is selected.
    """

    x: int
    y: int
    width: int
    height: int
    # Compared by identity, so that a new outline always counts as a change.
    mask: cairo.ImageSurface | None = field(default=None, compare=False)
    # The outline as drawn, in image pixels, for the marching ants.
    outline: tuple[Point, ...] | None = field(default=None, compare=False)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Selection):
            return NotImplemented
        return (
            self.rect == other.rect
            and self.mask is other.mask
            and self.outline == other.outline
        )

    @classmethod
    def from_rect(
        cls, x: float, y: float, width: float, height: float, image_width: int, image_height: int
    ) -> Selection | None:
        """A selection clipped to the image, or None when nothing is left of it."""
        left = max(0, round(x))
        top = max(0, round(y))
        right = min(image_width, round(x + width))
        bottom = min(image_height, round(y + height))
        if right <= left or bottom <= top:
            return None
        return cls(left, top, right - left, bottom - top)

    @classmethod
    def from_outline(
        cls, outline: list[Point], image_width: int, image_height: int
    ) -> Selection | None:
        """The pixels inside a hand-drawn outline, or None when it encloses none of the image."""
        if len(outline) < 3:
            return None
        xs = [x for x, _y in outline]
        ys = [y for _x, y in outline]
        left = max(0, math.floor(min(xs)))
        top = max(0, math.floor(min(ys)))
        right = min(image_width, math.ceil(max(xs)))
        bottom = min(image_height, math.ceil(max(ys)))
        if right <= left or bottom <= top:
            return None
        mask = outline_mask(outline, left, top, right - left, bottom - top)
        extent = _extent(mask)
        if extent is None:
            return None
        # Down to what the outline actually encloses on the image, which is
        # less than its box when it runs off the edge.
        x, y, width, height = extent
        if (width, height) != (mask.get_width(), mask.get_height()):
            mask = _crop_mask(mask, x, y, width, height)
        return cls(left + x, top + y, width, height, mask, tuple(outline))

    @classmethod
    def from_color(
        cls, surface: cairo.ImageSurface, x: float, y: float, tolerance: int
    ) -> Selection | None:
        """The pixels joined to the one at a point through colours near enough its own,
        as the magic wand picks them, or None for a point off the image."""
        px, py = int(x), int(y)
        if not (0 <= px < surface.get_width() and 0 <= py < surface.get_height()):
            return None
        surface.flush()
        spans = list(flood_spans(surface, px, py, tolerance))
        rect, mask = spans_mask(spans)
        if sum(end - start for _row, start, end in spans) == rect[2] * rect[3]:
            # Every pixel of the rectangle: it needs no mask.
            return cls(*rect)
        return cls(*rect, mask)

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.width, self.height

    @cached_property
    def edges(self) -> list[tuple[int, int, int, int]]:
        """The border of a masked selection, as horizontal and vertical lines
        (x1, y1, x2, y2) along the edges of its pixels, in image pixels."""
        if self.mask is None:
            x, y, width, height = self.rect
            return [(x, y, x + width, y), (x + width, y, x + width, y + height),
                    (x, y + height, x + width, y + height), (x, y, x, y + height)]
        self.mask.flush()
        data, stride = self.mask.get_data(), self.mask.get_stride()
        width, height = self.width, self.height
        inside = bytes(0 if value == 0 else 1 for value in range(256))
        edges = []
        # Upright lines running down from the row they started on, by column.
        running: dict[int, int] = {}
        previous = bytes(width)
        for row in range(height + 1):
            current = (
                data[row * stride:row * stride + width].tobytes().translate(inside)
                if row < height
                else bytes(width)
            )
            # Across: wherever this row and the one above differ.
            changed = (int.from_bytes(previous, "little") ^ int.from_bytes(current, "little")).to_bytes(
                width, "little"
            )
            start = changed.find(1)
            while start >= 0:
                end = changed.find(0, start)
                end = width if end < 0 else end
                edges.append((self.x + start, self.y + row, self.x + end, self.y + row))
                start = changed.find(1, end)
            # Up and down: wherever a pixel differs from the one to its left.
            padded = b"\x00" + current + b"\x00"
            steps = (int.from_bytes(padded[:-1], "little") ^ int.from_bytes(padded[1:], "little")).to_bytes(
                width + 1, "little"
            )
            columns = set()
            column = steps.find(1)
            while column >= 0:
                columns.add(column)
                column = steps.find(1, column + 1)
            for column in [column for column in running if column not in columns]:
                edges.append((self.x + column, self.y + running.pop(column), self.x + column, self.y + row))
            for column in columns:
                running.setdefault(column, row)
            previous = current
        return edges

    def contains(self, x: float, y: float) -> bool:
        if not (self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height):
            return False
        if self.mask is None:
            return True
        # Inside the outline, not merely inside the rectangle around it.
        column = min(int(x - self.x), self.width - 1)
        row = min(int(y - self.y), self.height - 1)
        self.mask.flush()
        return self.mask.get_data()[row * self.mask.get_stride() + column] != 0

    def clamped(self, image_width: int, image_height: int) -> Selection | None:
        """What is left of the selection on an image that may have shrunk."""
        clipped = self.from_rect(self.x, self.y, self.width, self.height, image_width, image_height)
        if clipped is None or self.mask is None:
            return clipped
        if clipped.rect == self.rect:
            return self
        mask = _crop_mask(self.mask, clipped.x - self.x, clipped.y - self.y, clipped.width, clipped.height)
        if not _has_pixels(mask):
            return None
        return Selection(*clipped.rect, mask, self.outline)

    def pixels(self, surface: cairo.ImageSurface) -> cairo.ImageSurface:
        """A copy of the selected pixels, transparent outside the outline."""
        copy = crop_surface(surface, *self.rect)
        if self.mask is not None:
            keep_inside(copy, self.mask)
        return copy
