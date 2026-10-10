# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The pixel loops that are slow from Python, done in C when the helper is there.

native/tempera_native.c holds them: the search a fill and the magic wand make,
ten times and more quicker on a photo, and the border of what the wand picked.
Tempera works without it: regions.py and selection.py do the same in Python,
and are what runs from a source tree where nobody has compiled it. Built and
installed, the launcher says where it is; `build-aux/build_native.sh` puts one
next to this file for the source tree.

The calls let go of Python's lock while they run, so one made from a worker
thread leaves the window free.
"""

from __future__ import annotations

import ctypes
import os
import struct
from pathlib import Path

import cairo

# Named in the environment by the launcher; "off" does without it.
ENVIRONMENT = "TEMPERA_NATIVE"
LIBRARY_NAME = "tempera_native.so"


class _Bounds(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_int32),
        ("top", ctypes.c_int32),
        ("right", ctypes.c_int32),
        ("bottom", ctypes.c_int32),
        ("count", ctypes.c_int64),
    ]


def _load() -> ctypes.CDLL | None:
    named = os.environ.get(ENVIRONMENT, "")
    if named == "off":
        return None
    for path in (named, str(Path(__file__).resolve().parent / LIBRARY_NAME)):
        if not path or not os.path.isfile(path):
            continue
        try:
            library = ctypes.CDLL(path)
            pointer, number = ctypes.c_void_p, ctypes.c_int
            library.tempera_flood.restype = number
            library.tempera_flood.argtypes = (
                pointer, number, number, number, number, number, number,
                pointer, number, ctypes.POINTER(_Bounds),
            )  # fmt: skip
            library.tempera_fill.restype = None
            library.tempera_fill.argtypes = (
                pointer, number, pointer, number,
                ctypes.POINTER(_Bounds), ctypes.c_char_p, ctypes.POINTER(_Bounds),
            )  # fmt: skip
            library.tempera_edges.restype = ctypes.c_int64
            library.tempera_edges.argtypes = (
                pointer, number, number, number, number, number, number, number, number,
                number, number, pointer, ctypes.c_int64,
            )  # fmt: skip
        except (OSError, AttributeError):
            # Built for another machine, or an older one without all of it.
            continue
        return library
    return None


# The helper, or None when there is none: then the Python does the work.
library = _load()


def available() -> bool:
    return library is not None


def _address(surface: cairo.ImageSurface) -> int:
    """Where a surface's pixels are in memory."""
    surface.flush()
    return ctypes.addressof(ctypes.c_char.from_buffer(surface.get_data()))


def flood(
    surface: cairo.ImageSurface, x: int, y: int, tolerance: int
) -> tuple[cairo.ImageSurface, tuple[int, int, int, int], int]:
    """The pixels joined to the one at (x, y) through colours near enough its own.

    As an A8 mask the size of the surface, the rectangle around them as
    (x, y, width, height), and how many they are. The point must be on the surface.
    """
    width, height = surface.get_width(), surface.get_height()
    mask = cairo.ImageSurface(cairo.FORMAT_A8, width, height)
    bounds = _Bounds()
    failed = library.tempera_flood(
        _address(surface), surface.get_stride(), width, height, x, y, tolerance,
        _address(mask), mask.get_stride(), ctypes.byref(bounds),
    )  # fmt: skip
    if failed:
        raise MemoryError
    mask.mark_dirty()
    rect = (bounds.left, bounds.top, bounds.right - bounds.left, bounds.bottom - bounds.top)
    return mask, rect, bounds.count


def fill(
    surface: cairo.ImageSurface,
    mask: cairo.ImageSurface,
    rect: tuple[int, int, int, int],
    pixel: bytes,
) -> tuple[int, int, int, int] | None:
    """Give the pixels of one rectangle that a mask covers the four bytes of one colour.

    Returns the rectangle around those it changed, or None when every one was
    that colour already.
    """
    left, top, width, height = rect
    where, changed = _Bounds(left, top, left + width, top + height, 0), _Bounds()
    library.tempera_fill(
        _address(surface), surface.get_stride(), _address(mask), mask.get_stride(),
        ctypes.byref(where), pixel, ctypes.byref(changed),
    )  # fmt: skip
    surface.mark_dirty()
    if changed.count == 0:
        return None
    return changed.left, changed.top, changed.right - changed.left, changed.bottom - changed.top


def count_edges(mask: cairo.ImageSurface, width: int, height: int) -> int:
    """How many lines the border of a mask's covered pixels is made of."""
    return library.tempera_edges(
        _address(mask), mask.get_stride(), width, height, 0, 0, width, height, max(width, height) + 1,
        0, 0, None, 0,
    )  # fmt: skip


def edges(
    mask: cairo.ImageSurface,
    width: int,
    height: int,
    rect: tuple[int, int, int, int],
    cut: int,
    offset: tuple[int, int] = (0, 0),
) -> list[tuple[int, int, int, int]]:
    """The border of a mask's covered pixels inside one rectangle of it, given as
    (left, top, right, bottom): lines (x1, y1, x2, y2) along the pixels' edges,
    moved by `offset`, each cut where it crosses a multiple of `cut`.

    A line along the rectangle's right or bottom side is left out, for the
    rectangle beyond to give, unless that side is the mask's own.
    """
    address, stride = _address(mask), mask.get_stride()
    room = 4096
    while True:
        lines = (ctypes.c_int32 * (room * 4))()
        found = library.tempera_edges(
            address, stride, width, height, *rect, cut, *offset, lines, room
        )
        if found <= room:
            break
        room = found
    # Straight from the numbers to tuples, without a Python loop over them.
    return list(struct.iter_unpack("4i", memoryview(lines).cast("B")[: found * 16]))
