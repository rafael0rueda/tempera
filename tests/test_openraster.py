# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reading and writing OpenRaster, the layered format other paint programs share."""

import io
import struct
import zipfile

import cairo
import pytest

from tempera import openraster
from tempera.document import Document, Layer, new_surface
from tempera.openraster import OpenRasterError, read_openraster, write_openraster

from pixels import paint_pixel, pixel_at

RED = (1.0, 0.0, 0.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)
CLEAR = (0.0, 0.0, 0.0, 0.0)


def layered() -> Document:
    document = Document(new_surface(6, 4, WHITE))
    document.add_layer()
    paint_pixel(document.surface, 1, 2, RED)
    document.rename_layer(1, "Ink & <notes>")
    document.set_layer_opacity(1, 0.25)
    document.add_layer()
    document.set_layer_visible(2, False)
    return document


def written(document: Document, complete: bool = True) -> bytes:
    stream = io.BytesIO()
    write_openraster(stream, document.layers, document.width, document.height, complete)
    return stream.getvalue()


def png(surface) -> bytes:
    stream = io.BytesIO()
    surface.write_to_png(stream)
    return stream.getvalue()


def archive(members: dict[str, bytes]) -> io.BytesIO:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as ora:
        for name, data in members.items():
            ora.writestr(name, data)
    stream.seek(0)
    return stream


def test_the_layers_come_back_as_they_were_written():
    width, height, layers = read_openraster(io.BytesIO(written(layered())))
    assert (width, height) == (6, 4)
    assert [layer.name for layer in layers] == ["Background", "Ink & <notes>", "Layer 3"]
    assert [layer.visible for layer in layers] == [True, True, False]
    assert [layer.opacity for layer in layers] == [1.0, 0.25, 1.0]
    assert pixel_at(layers[1].surface, 1, 2) == (255, 0, 0, 255)
    assert pixel_at(layers[1].surface, 0, 0)[3] == 0
    assert pixel_at(layers[0].surface, 1, 2) == (255, 255, 255, 255)


def test_the_file_is_what_other_programs_expect():
    data = written(layered())
    # The type, first and stored as it is, readable from the start of the file.
    assert data[30:38] == b"mimetype" and data[38:54] == b"image/openraster"
    with zipfile.ZipFile(io.BytesIO(data)) as ora:
        assert ora.namelist()[0] == "mimetype"
        assert ora.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        stack = ora.read("stack.xml").decode()
        # Top first.
        assert stack.index("Layer 3") < stack.index("Ink &amp; &lt;notes&gt;") < stack.index("Background")
        merged = cairo.ImageSurface.create_from_png(io.BytesIO(ora.read("mergedimage.png")))
        assert (merged.get_width(), merged.get_height()) == (6, 4)
        thumbnail = cairo.ImageSurface.create_from_png(io.BytesIO(ora.read("Thumbnails/thumbnail.png")))
        assert max(thumbnail.get_width(), thumbnail.get_height()) <= openraster.THUMBNAIL_SIZE


def test_a_copy_for_tempera_alone_leaves_out_the_flattened_picture():
    with zipfile.ZipFile(io.BytesIO(written(layered(), complete=False))) as ora:
        assert "mergedimage.png" not in ora.namelist()
        assert "Thumbnails/thumbnail.png" not in ora.namelist()


def test_layers_placed_anywhere_and_in_groups_are_read_onto_the_canvas():
    dot = new_surface(2, 2, RED)
    stack = b"""<?xml version="1.0"?>
    <image w="8" h="8">
      <stack>
        <stack x="1" y="1" opacity="0.5" visibility="hidden">
          <layer src="data/dot.png" x="2" y="3" name="In a group" opacity="0.5"/>
        </stack>
        <text>ignored</text>
        <layer src="data/bottom.png"/>
      </stack>
    </image>"""
    width, height, layers = read_openraster(
        archive({"stack.xml": stack, "data/dot.png": png(dot), "data/bottom.png": png(new_surface(8, 8, WHITE))})
    )
    assert (width, height) == (8, 8)
    group = layers[1]
    assert group.name == "In a group"
    assert group.opacity == 0.25 and not group.visible
    assert pixel_at(group.surface, 3, 4) == (255, 0, 0, 255)
    assert pixel_at(group.surface, 2, 3)[3] == 0
    # An unnamed layer gets a name.
    assert layers[0].name == "Layer 1"


@pytest.mark.parametrize(
    "members",
    [
        {"stack.xml": b"<image"},
        {"stack.xml": b"<picture w='2' h='2'/>"},
        {"other.txt": b""},
        {"stack.xml": b"<image w='0' h='2'><stack><layer src='a.png'/></stack></image>"},
        {"stack.xml": b"<image w='99999' h='2'><stack><layer src='a.png'/></stack></image>"},
        {"stack.xml": b"<image w='2' h='2'><stack/></image>"},
        {"stack.xml": b"<image w='2' h='2'><stack><layer src='missing.png'/></stack></image>"},
        {"stack.xml": b"<image w='2' h='2'><stack><layer src='a.png'/></stack></image>", "a.png": b"not a png"},
    ],
)
def test_a_broken_file_is_refused_with_a_reason(members):
    with pytest.raises(OpenRasterError):
        read_openraster(archive(members))


def test_something_that_is_not_a_zip_is_refused():
    with pytest.raises(OpenRasterError):
        read_openraster(io.BytesIO(b"GIF89a, not a zip at all"))


def test_a_layer_declaring_a_vast_size_is_refused_before_it_is_decoded():
    real = png(new_surface(1, 1, RED))
    # The same PNG, with a header claiming 100 000 pixels square.
    vast = real[:16] + struct.pack(">II", 100_000, 100_000) + real[24:]
    stack = b"<image w='2' h='2'><stack><layer src='a.png'/></stack></image>"
    with pytest.raises(OpenRasterError):
        read_openraster(archive({"stack.xml": stack, "a.png": vast}))


def test_too_many_layers_are_refused(monkeypatch):
    monkeypatch.setattr(openraster, "MAX_LAYERS", 2)
    layers = b"".join(b"<layer src='a.png'/>" for _each in range(3))
    stack = b"<image w='2' h='2'><stack>" + layers + b"</stack></image>"
    with pytest.raises(OpenRasterError):
        read_openraster(archive({"stack.xml": stack, "a.png": png(new_surface(2, 2, RED))}))


def test_a_member_bigger_than_its_limit_is_refused(monkeypatch):
    monkeypatch.setattr(openraster, "MAX_LAYER_BYTES", 10)
    stack = b"<image w='2' h='2'><stack><layer src='a.png'/></stack></image>"
    with pytest.raises(OpenRasterError):
        read_openraster(archive({"stack.xml": stack, "a.png": png(new_surface(2, 2, RED))}))


def test_a_layer_of_its_own_writes_and_reads_back():
    layer = Layer(new_surface(3, 3, CLEAR), "Only", True, 1.0)
    stream = io.BytesIO()
    write_openraster(stream, [layer], 3, 3)
    stream.seek(0)
    _width, _height, [back] = read_openraster(stream)
    assert back.name == "Only"
