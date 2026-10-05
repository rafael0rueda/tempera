# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Between GdkPixbuf, which reads and writes image files, and the cairo surfaces Tempera paints on.

GTK is moving away from these three calls, and each warns that it is
deprecated. They are kept to this one module so that replacing them, when GTK
offers something that works from Python, is a change in one place.
"""

from __future__ import annotations

import cairo
from gi.repository import Gdk, GdkPixbuf


def surface_from_pixbuf(pixbuf: GdkPixbuf.Pixbuf) -> cairo.ImageSurface:
    """Copy a pixbuf into a surface Tempera can draw on."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, pixbuf.get_width(), pixbuf.get_height())
    cr = cairo.Context(surface)
    Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.paint()
    return surface


def pixbuf_from_surface(surface: cairo.ImageSurface) -> GdkPixbuf.Pixbuf:
    """A whole surface as a pixbuf, for an encoder to write."""
    surface.flush()
    return Gdk.pixbuf_get_from_surface(surface, 0, 0, surface.get_width(), surface.get_height())


def pixbuf_from_texture(texture: Gdk.Texture) -> GdkPixbuf.Pixbuf:
    """A texture's pixels, which Gdk.Texture.download() cannot hand to Python:
    PyGObject gives the texture a copy of the buffer, so they never arrive."""
    return Gdk.pixbuf_get_from_texture(texture)
