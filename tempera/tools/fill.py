# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import cairo
from gi.repository import Gdk

from ..i18n import _
from .base import Tool, ToolContext

TOLERANCE = 32


def _premultiplied(color: Gdk.RGBA) -> tuple[int, int, int, int]:
    alpha = color.alpha
    return (
        round(color.blue * alpha * 255),
        round(color.green * alpha * 255),
        round(color.red * alpha * 255),
        round(alpha * 255),
    )


def _row_masks(surface: cairo.ImageSurface, target: bytes, tolerance: int):
    """A function giving one row of the image as a mask: 1 where a pixel matches.

    The per-pixel comparison happens inside bytes.translate() and big-integer
    ANDs rather than in Python, one row at a time and only for the rows the
    fill actually reaches.
    """
    width, stride = surface.get_width(), surface.get_stride()
    data = surface.get_data()
    tables = [
        bytes(1 if abs(value - channel) <= tolerance else 0 for value in range(256))
        for channel in target
    ]

    def row_mask(y: int) -> bytearray:
        pixels = data[y * stride:y * stride + width * 4]
        combined = -1
        for channel, table in enumerate(tables):
            matched = pixels[channel::4].tobytes().translate(table)
            combined &= int.from_bytes(matched, "little")
        return bytearray(combined.to_bytes(width, "little"))

    return row_mask


def flood_fill(surface: cairo.ImageSurface, x: int, y: int, color: Gdk.RGBA,
               tolerance: int = TOLERANCE) -> bool:
    """Scanline flood fill over the surface's ARGB32 buffer."""
    width, height = surface.get_width(), surface.get_height()
    if not (0 <= x < width and 0 <= y < height):
        return False

    surface.flush()
    stride = surface.get_stride()
    data = surface.get_data()
    replacement = _premultiplied(color)

    origin = y * stride + x * 4
    target = bytes(data[origin:origin + 4])

    # Filling with a colour that still matches the target would never terminate.
    if all(abs(replacement[i] - target[i]) <= tolerance for i in range(4)):
        return False

    row_mask = _row_masks(surface, target, tolerance)
    # Built as the fill reaches each row. A filled span is zeroed in its mask,
    # so it is never matched, or filled, twice.
    masks: list[bytearray | None] = [None] * height
    replacement_bytes = bytes(replacement)

    stack = [(x, y)]
    while stack:
        seed_x, seed_y = stack.pop()
        mask = masks[seed_y]
        if mask is None:
            mask = masks[seed_y] = row_mask(seed_y)
        if not mask[seed_x]:
            continue

        # The run of matching pixels around the seed: [left, right).
        left = mask.rfind(0, 0, seed_x) + 1
        right = mask.find(0, seed_x)
        if right < 0:
            right = width
        mask[left:right] = bytes(right - left)
        row = seed_y * stride
        data[row + left * 4:row + right * 4] = replacement_bytes * (right - left)

        for neighbour_y in (seed_y - 1, seed_y + 1):
            if not 0 <= neighbour_y < height:
                continue
            neighbour = masks[neighbour_y]
            if neighbour is None:
                neighbour = masks[neighbour_y] = row_mask(neighbour_y)
            # One seed per run of matching pixels alongside the span just filled.
            scan = neighbour.find(1, left, right)
            while scan >= 0:
                stack.append((scan, neighbour_y))
                end = neighbour.find(0, scan, right)
                if end < 0:
                    break
                scan = neighbour.find(1, end, right)

    surface.mark_dirty()
    return True


class FillTool(Tool):
    id = "fill"
    label = _("Fill")
    icon_name = "tempera-fill-symbolic"
    tip_icon_name = "tempera-fill-tip-symbolic"

    def colors_used(self, ctx: ToolContext):
        return (ctx.color,)

    def press(self, ctx: ToolContext, x, y):
        flood_fill(ctx.surface, int(x), int(y), ctx.color, ctx.tolerance)
