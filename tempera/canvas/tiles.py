# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The image as a grid of textures, so that a change uploads only the tiles it touched."""

from __future__ import annotations

import math
from typing import Callable

import cairo
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk

# Big enough that even the largest canvas, zoomed right out, is a few hundred
# tiles; small enough that a brush stroke re-uploads little around it.
TILE_SIZE = 512
# Tiles scrolled out of view are kept for when they come back, up to this many
# beyond those in view; each holds a copy of up to a megabyte of the image.
SPARE_TILES = 64
# Cairo's ARGB32 is exactly this byte order on little-endian machines.
SURFACE_FORMAT = Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED


def surface_texture(surface: cairo.ImageSurface, x: int, y: int, width: int, height: int) -> Gdk.Texture:
    """A copy of one rectangle of the surface, as a texture."""
    stride = surface.get_stride()
    data = surface.get_data()
    if x == 0 and width * 4 == stride:
        # Whole rows lie one after the other in memory.
        pixels = bytes(data[y * stride:(y + height) * stride])
    else:
        start, end = x * 4, (x + width) * 4
        pixels = b"".join(
            data[row + start:row + end] for row in range(y * stride, (y + height) * stride, stride)
        )
    return Gdk.MemoryTexture.new(width, height, SURFACE_FORMAT, GLib.Bytes.new(pixels), width * 4)


def mask_texture(mask: cairo.ImageSurface) -> Gdk.Texture:
    """A texture of a cairo A8 mask, for GTK to cut with."""
    mask.flush()
    return Gdk.MemoryTexture.new(
        mask.get_width(),
        mask.get_height(),
        Gdk.MemoryFormat.A8,
        GLib.Bytes.new(bytes(mask.get_data())),
        mask.get_stride(),
    )


class ImageTiles:
    """Textures for the parts of an image in view, rebuilt only where it changed."""

    def __init__(self):
        self._surface: cairo.ImageSurface | None = None
        self._textures: dict[tuple[int, int], Gdk.Texture] = {}

    def invalidate(self, rect: tuple[int, int, int, int] | None = None) -> None:
        """Forget the tiles a rectangle of the image touches, or with None all of them."""
        if rect is None:
            self._textures.clear()
            return
        x, y, width, height = rect
        if width <= 0 or height <= 0 or not self._textures:
            return
        for column in range(max(0, x) // TILE_SIZE, (x + width - 1) // TILE_SIZE + 1):
            for row in range(max(0, y) // TILE_SIZE, (y + height - 1) // TILE_SIZE + 1):
                self._textures.pop((column, row), None)

    def snapshot(
        self,
        snapshot: Gtk.Snapshot,
        surface: cairo.ImageSurface,
        visible: tuple[float, float, float, float],
        zoom: float,
        scaling: Gsk.ScalingFilter,
        align: Callable[[float, float], tuple[float, float]],
    ) -> None:
        """Draw the tiles overlapping the visible rectangle, given in image pixels, at a zoom.

        Each tile is given its place on screen rather than drawn under a scale,
        which GTK's software renderer would smooth whatever the filter. `align`
        moves a point on screen onto the nearest corner of a device pixel: tiles
        whose edges fell between two would each half cover the pixels along the
        seam, and leave a faint line there.
        """
        if surface is not self._surface:
            self._surface = surface
            self._textures.clear()
        width, height = surface.get_width(), surface.get_height()
        left, top, visible_width, visible_height = visible
        columns = range(
            max(0, int(left) // TILE_SIZE),
            min(math.ceil(width / TILE_SIZE), math.ceil((left + visible_width) / TILE_SIZE)),
        )
        rows = range(
            max(0, int(top) // TILE_SIZE),
            min(math.ceil(height / TILE_SIZE), math.ceil((top + visible_height) / TILE_SIZE)),
        )
        flushed = False
        for row in rows:
            y = row * TILE_SIZE
            tile_height = min(TILE_SIZE, height - y)
            for column in columns:
                x = column * TILE_SIZE
                tile_width = min(TILE_SIZE, width - x)
                texture = self._textures.get((column, row))
                if texture is None:
                    if not flushed:
                        surface.flush()
                        flushed = True
                    texture = surface_texture(surface, x, y, tile_width, tile_height)
                    self._textures[(column, row)] = texture
                left, top = align(x * zoom, y * zoom)
                right, bottom = align((x + tile_width) * zoom, (y + tile_height) * zoom)
                bounds = Graphene.Rect().init(left, top, right - left, bottom - top)
                snapshot.append_scaled_texture(texture, scaling, bounds)

        in_view = len(columns) * len(rows)
        if len(self._textures) > in_view + SPARE_TILES:
            self._textures = {
                key: texture
                for key, texture in self._textures.items()
                if key[0] in columns and key[1] in rows
            }
