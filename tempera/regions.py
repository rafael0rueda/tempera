# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Finding the pixels of a colour: the region a fill spreads over or the magic
wand picks out, and the pixels a transparent selection leaves out."""

from __future__ import annotations

from collections.abc import Iterator

import cairo
from gi.repository import Gdk


def premultiplied(color: Gdk.RGBA) -> tuple[int, int, int, int]:
    """A colour as the bytes of one of cairo's ARGB32 pixels, in memory order."""
    alpha = color.alpha
    return (
        round(color.blue * alpha * 255),
        round(color.green * alpha * 255),
        round(color.red * alpha * 255),
        round(alpha * 255),
    )


def row_masks(surface: cairo.ImageSurface, target: bytes, tolerance: int):
    """A function giving one row of the image as a mask: 1 where a pixel matches.

    The per-pixel comparison happens inside bytes.translate() and big-integer
    ANDs rather than in Python, one row at a time and only for the rows asked
    for. A row all of the target colour, the usual case when filling a
    background, is matched whole with one comparison.
    """
    width, stride = surface.get_width(), surface.get_stride()
    data = surface.get_data()
    tables = [
        bytes(1 if abs(value - channel) <= tolerance else 0 for value in range(256))
        for channel in target
    ]
    uniform = target * width
    everything = b"\x01" * width

    def row_mask(y: int) -> bytearray:
        # One contiguous copy of the row: picking every fourth byte out of a
        # bytes object is several times quicker than out of a memoryview.
        pixels = data[y * stride:y * stride + width * 4].tobytes()
        if pixels == uniform:
            return bytearray(everything)
        combined = -1
        for channel, table in enumerate(tables):
            matched = pixels[channel::4].translate(table)
            combined &= int.from_bytes(matched, "little")
        return bytearray(combined.to_bytes(width, "little"))

    return row_mask


def target_at(surface: cairo.ImageSurface, x: int, y: int) -> bytes:
    """The pixel at a point, as its four bytes."""
    origin = y * surface.get_stride() + x * 4
    return bytes(surface.get_data()[origin:origin + 4])


def flood_spans(
    surface: cairo.ImageSurface, x: int, y: int, tolerance: int
) -> Iterator[tuple[int, int, int]]:
    """The runs of pixels, as (row, left, right) with right excluded, joined to the
    one at (x, y) through pixels of near enough its colour.

    A scanline search: each run is found whole and its neighbours above and
    below are looked through once. The caller may paint each run as it comes;
    a run's row is always read before it is handed out.
    """
    width, height = surface.get_width(), surface.get_height()
    row_mask = row_masks(surface, target_at(surface, x, y), tolerance)
    # Built as the search reaches each row. A run already found is zeroed in
    # its mask, so it is never found twice.
    masks: list[bytearray | None] = [None] * height
    stack = [(x, y)]
    while stack:
        seed_x, seed_y = stack.pop()
        mask = masks[seed_y]
        if mask is None:
            mask = masks[seed_y] = row_mask(seed_y)
        if not mask[seed_x]:
            continue

        left = mask.rfind(0, 0, seed_x) + 1
        right = mask.find(0, seed_x)
        if right < 0:
            right = width
        mask[left:right] = bytes(right - left)
        # Neighbouring rows are read before the run is handed out, in case
        # the caller paints it.
        for neighbour_y in (seed_y - 1, seed_y + 1):
            if 0 <= neighbour_y < height and masks[neighbour_y] is None:
                masks[neighbour_y] = row_mask(neighbour_y)
        yield seed_y, left, right

        for neighbour_y in (seed_y - 1, seed_y + 1):
            if not 0 <= neighbour_y < height:
                continue
            neighbour = masks[neighbour_y]
            # One seed per run of matching pixels alongside the one just found.
            scan = neighbour.find(1, left, right)
            while scan >= 0:
                stack.append((scan, neighbour_y))
                end = neighbour.find(0, scan, right)
                if end < 0:
                    break
                scan = neighbour.find(1, end, right)


def spans_mask(
    spans: list[tuple[int, int, int]],
) -> tuple[tuple[int, int, int, int], cairo.ImageSurface] | None:
    """The rectangle around some runs of pixels, and an A8 mask of them within it."""
    if not spans:
        return None
    left = min(start for _row, start, _end in spans)
    right = max(end for _row, _start, end in spans)
    top = min(row for row, _start, _end in spans)
    bottom = max(row for row, _start, _end in spans) + 1
    mask = cairo.ImageSurface(cairo.FORMAT_A8, right - left, bottom - top)
    mask.flush()
    data, stride = mask.get_data(), mask.get_stride()
    for row, start, end in spans:
        offset = (row - top) * stride - left
        data[offset + start:offset + end] = b"\xff" * (end - start)
    mask.mark_dirty()
    return (left, top, right - left, bottom - top), mask


def without_color(surface: cairo.ImageSurface, color: Gdk.RGBA) -> cairo.ImageSurface:
    """A copy of a surface with every pixel of exactly one colour made see-through."""
    width, height = surface.get_width(), surface.get_height()
    copy = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(copy)
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_surface(surface, 0, 0)
    cr.paint()
    copy.flush()
    row_mask = row_masks(copy, bytes(premultiplied(color)), 0)
    # 255 keeps a pixel, 0 clears it.
    keep = cairo.ImageSurface(cairo.FORMAT_A8, width, height)
    keep.flush()
    data, stride = keep.get_data(), keep.get_stride()
    flip = bytes(255 if value == 0 else 0 for value in range(256))
    for y in range(height):
        data[y * stride:y * stride + width] = bytes(row_mask(y)).translate(flip)
    keep.mark_dirty()
    cr.set_operator(cairo.OPERATOR_DEST_IN)
    cr.set_source_surface(keep, 0, 0)
    cr.paint()
    return copy
