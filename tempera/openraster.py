# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""OpenRaster, the layered image format GIMP, Krita and MyPaint share.

An .ora file is a zip archive: each layer as a PNG, and stack.xml listing them
top first with their names, positions, opacity and visibility. Alongside go
the whole picture flattened, and a thumbnail of it, for programs that only
want to show the file.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from xml.etree import ElementTree

import cairo

from .document import (
    MAX_SIZE,
    TRANSPARENT,
    Layer,
    clean_name,
    flatten,
    layer_limit,
    new_surface,
)
from .i18n import _

MIMETYPE = "image/openraster"
THUMBNAIL_SIZE = 256
# The description of even a hundred layers is a few kilobytes; anything much
# bigger is not describing a picture Tempera could hold.
MAX_STACK_BYTES = 1024 * 1024
# One layer's PNG, however it was compressed.
MAX_LAYER_BYTES = 512 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


# What a file from another program can hold that Tempera cannot.
BLENDING, GROUPS, OVERHANG = "blending", "groups", "overhang"


class OpenRasterError(Exception):
    """A file that is not OpenRaster, or not one Tempera can open."""


def _png(surface: cairo.ImageSurface) -> bytes:
    stream = io.BytesIO()
    surface.write_to_png(stream)
    return stream.getvalue()


def _thumbnail(picture: cairo.ImageSurface) -> cairo.ImageSurface:
    width, height = picture.get_width(), picture.get_height()
    scale = min(1.0, THUMBNAIL_SIZE / max(width, height))
    thumbnail = cairo.ImageSurface(
        cairo.FORMAT_ARGB32, max(1, round(width * scale)), max(1, round(height * scale))
    )
    cr = cairo.Context(thumbnail)
    cr.scale(scale, scale)
    cr.set_source_surface(picture, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_GOOD)
    cr.paint()
    return thumbnail


def write_openraster(
    stream,
    layers: list[Layer],
    width: int,
    height: int,
    complete: bool = True,
    members: list[tuple[str, bytes | None]] | None = None,
) -> None:
    """Write the layers, listed bottom first, as an OpenRaster file.

    Without `complete`, the flattened picture and the thumbnail other programs
    look for are left out: a copy Tempera keeps for itself does not need them.

    `members` gives each layer the name its PNG goes under in the archive, and
    the PNG itself where there is one already, which is then written as it is
    and the layer's surface not looked at.
    """
    image = ElementTree.Element("image", version="0.0.6", w=str(width), h=str(height))
    stack = ElementTree.SubElement(image, "stack")
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        # First and uncompressed, so the type can be told from the first bytes.
        archive.writestr("mimetype", MIMETYPE, compress_type=zipfile.ZIP_STORED)
        for index in reversed(range(len(layers))):
            layer = layers[index]
            source, png = members[index] if members is not None else (f"data/layer{index}.png", None)
            ElementTree.SubElement(
                stack,
                "layer",
                name=clean_name(layer.name),
                src=source,
                x="0",
                y="0",
                opacity=f"{layer.opacity:.4g}",
                visibility="visible" if layer.visible else "hidden",
            )
            # PNG is compressed already.
            archive.writestr(
                source, _png(layer.surface) if png is None else png, compress_type=zipfile.ZIP_STORED
            )
        archive.writestr(
            "stack.xml", ElementTree.tostring(image, encoding="UTF-8", xml_declaration=True)
        )
        if complete:
            picture = flatten(layers, 0, 0, width, height)
            archive.writestr("mergedimage.png", _png(picture), compress_type=zipfile.ZIP_STORED)
            archive.writestr(
                "Thumbnails/thumbnail.png", _png(_thumbnail(picture)), compress_type=zipfile.ZIP_STORED
            )


def _read_member(archive: zipfile.ZipFile, name: str, limit: int) -> bytes:
    try:
        with archive.open(name) as member:
            # Read one byte past the limit rather than trusting the size the
            # archive declares, which a hostile file can understate.
            data = member.read(limit + 1)
    except KeyError:
        raise OpenRasterError(_("The file is missing “{name}”").format(name=name)) from None
    except (zipfile.BadZipFile, OSError, EOFError, zlib.error) as error:
        raise OpenRasterError(str(error)) from None
    except (RuntimeError, NotImplementedError):
        # A member locked with a password, or packed in a way Python cannot unpack.
        raise OpenRasterError(_("“{name}” cannot be read").format(name=name)) from None
    if len(data) > limit:
        raise OpenRasterError(_("“{name}” is too big").format(name=name))
    return data


def _dimension(value: str | None) -> int:
    try:
        number = int(value or "")
    except ValueError:
        raise OpenRasterError(_("The image has no size")) from None
    if not 1 <= number <= MAX_SIZE:
        raise OpenRasterError(
            _("A picture can be at most {size} × {size} px").format(size=MAX_SIZE)
        )
    return number


def _number(value: str | None, fallback: float, kind=float):
    try:
        return kind(value) if value is not None else fallback
    except ValueError:
        return fallback


def _layers_in(
    element, x: int, y: int, opacity: float, visible: bool, found: list, limit: int, lost: list
) -> None:
    """Every layer inside a stack, top first, with the offsets, opacity and visibility
    of the stacks around it carried down.

    What Tempera has no place for is named in `lost`: how a layer blends with
    those beneath it, other than lying over them, and layers kept in groups.
    """
    for child in element:
        if child.get("composite-op", "svg:src-over") != "svg:src-over" and BLENDING not in lost:
            lost.append(BLENDING)
        if child.tag == "stack" and GROUPS not in lost:
            lost.append(GROUPS)
        child_x = x + _number(child.get("x"), 0, int)
        child_y = y + _number(child.get("y"), 0, int)
        child_opacity = opacity * max(0.0, min(_number(child.get("opacity"), 1.0), 1.0))
        child_visible = visible and child.get("visibility", "visible") != "hidden"
        if child.tag == "stack":
            _layers_in(child, child_x, child_y, child_opacity, child_visible, found, limit, lost)
        elif child.tag == "layer" and child.get("src"):
            found.append((child, child_x, child_y, child_opacity, child_visible))
        if len(found) > limit:
            raise OpenRasterError(
                _("A picture this size can have at most {count} layers").format(count=limit)
            )


def _decode_png(data: bytes, name: str) -> cairo.ImageSurface:
    # The size, from the header, before decoding: a small file can declare a
    # vast image.
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise OpenRasterError(_("“{name}” is not a PNG image").format(name=name))
    width, height = struct.unpack(">II", data[16:24])
    if not (1 <= width <= MAX_SIZE and 1 <= height <= MAX_SIZE):
        raise OpenRasterError(
            _("A picture can be at most {size} × {size} px").format(size=MAX_SIZE)
        )
    try:
        return cairo.ImageSurface.create_from_png(io.BytesIO(data))
    except (cairo.Error, MemoryError) as error:
        raise OpenRasterError(str(error)) from None


def read_openraster(stream, lost: list[str] | None = None) -> tuple[int, int, list[Layer]]:
    """The canvas size and the layers, bottom first, of an OpenRaster file.

    A file from GIMP or Krita can hold what Tempera has no place for; each
    such thing found is named in `lost`, when a list is given for it:
    BLENDING, GROUPS, or OVERHANG for pixels beyond the edge of the canvas.
    """
    lost = [] if lost is None else lost
    try:
        archive = zipfile.ZipFile(stream)
    except (zipfile.BadZipFile, OSError, EOFError):
        raise OpenRasterError(_("The file is not an OpenRaster image")) from None
    with archive:
        try:
            image = ElementTree.fromstring(_read_member(archive, "stack.xml", MAX_STACK_BYTES))
        except ElementTree.ParseError:
            raise OpenRasterError(_("The file's list of layers is damaged")) from None
        if image.tag != "image":
            raise OpenRasterError(_("The file's list of layers is damaged"))
        width, height = _dimension(image.get("w")), _dimension(image.get("h"))
        found: list = []
        # Counted before any is decoded: each one takes a whole canvas of
        # memory, however small its PNG.
        limit = layer_limit(width, height)
        for stack in image.findall("stack"):
            _layers_in(stack, 0, 0, 1.0, True, found, limit, lost)
        if not found:
            raise OpenRasterError(_("The file has no layers"))

        layers = []
        for element, x, y, opacity, visible in reversed(found):
            source = element.get("src")
            pixels = _decode_png(_read_member(archive, source, MAX_LAYER_BYTES), source)
            # Each layer covers the whole canvas here, wherever it sat in the file.
            reaches_past = (
                x < 0 or y < 0 or x + pixels.get_width() > width or y + pixels.get_height() > height
            )
            if reaches_past and OVERHANG not in lost:
                lost.append(OVERHANG)
            try:
                surface = new_surface(width, height, TRANSPARENT)
                cr = cairo.Context(surface)
                cr.set_source_surface(pixels, x, y)
                cr.paint()
            except (cairo.Error, MemoryError):
                raise OpenRasterError(_("There is not enough memory to open the image")) from None
            name = element.get("name") or _("Layer {number}").format(number=len(layers) + 1)
            layers.append(Layer(surface, name, visible, opacity))
    return width, height, layers
