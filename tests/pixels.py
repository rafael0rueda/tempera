# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Small pixel-reading helpers shared by the surface-based tests."""

import cairo
from gi.repository import Gdk, Graphene, Gsk, Gtk


def pixel_at(surface: cairo.ImageSurface, x: int, y: int) -> tuple[int, int, int, int]:
    """(r, g, b, a) at a pixel, from cairo's premultiplied BGRA bytes.

    Only accurate for fully opaque fills, where premultiplied and straight
    alpha are the same numbers — which is all these tests use.
    """
    surface.flush()
    stride = surface.get_stride()
    data = surface.get_data()
    offset = y * stride + x * 4
    b, g, r, a = data[offset], data[offset + 1], data[offset + 2], data[offset + 3]
    return (r, g, b, a)


def paint_pixel(surface: cairo.ImageSurface, x: int, y: int, color) -> None:
    cr = cairo.Context(surface)
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_rgba(*color)
    cr.rectangle(x, y, 1, 1)
    cr.fill()


def render_widget(widget: Gtk.Widget, width: int, height: int) -> cairo.ImageSurface:
    """What a widget draws, as GTK would put it on screen, rendered in software."""
    snapshot = Gtk.Snapshot()
    widget.do_snapshot(snapshot)
    target = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    node = snapshot.to_node()
    if node is None:
        return target
    renderer = Gsk.CairoRenderer()
    renderer.realize_for_display(Gdk.Display.get_default())
    try:
        texture = renderer.render_texture(node, Graphene.Rect().init(0, 0, width, height))
    finally:
        renderer.unrealize()
    downloader = Gdk.TextureDownloader.new(texture)
    downloader.set_format(Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED)
    pixels, stride = downloader.download_bytes()
    target.flush()
    data, target_stride = target.get_data(), target.get_stride()
    source = pixels.get_data()
    for row in range(height):
        data[row * target_stride:row * target_stride + width * 4] = source[row * stride:row * stride + width * 4]
    target.mark_dirty()
    return target
