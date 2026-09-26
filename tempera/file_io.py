# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import io
import os
from typing import Callable

import cairo
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from .background import run_in_background
from .document import MAX_SIZE, Document, Layer, copy_surface, flatten, new_surface, surface_from_pixbuf
from .i18n import _
from .openraster import OpenRasterError, read_openraster, write_openraster

EXTENSION_FORMATS = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".bmp": "bmp",
    ".tiff": "tiff",
    ".tif": "tiff",
    ".webp": "webp",
    ".ico": "ico",
    ".ora": "ora",
}
# The one format that keeps the layers; the rest get the picture as it shows.
LAYERED_FORMAT = "ora"
FLATTEN_FORMATS = {"jpeg", "bmp"}
# Readable image types, for the Open dialog and the desktop file. GIF and ICO
# open like the rest; GIF just cannot be written back.
OPEN_MIME_TYPES = (
    "image/png",
    "image/jpeg",
    "image/bmp",
    "image/tiff",
    "image/webp",
    "image/gif",
    "image/vnd.microsoft.icon",
    "image/openraster",
)
# The ICO format stores its size in a byte, where 0 means 256.
ICO_MAX_SIZE = 256
DEFAULT_EXTENSION = ".png"
LAYERED_EXTENSION = ".ora"
LOAD_CHUNK = 64 * 1024
# No image that fits on a canvas is anywhere near this big; an uncompressed
# 8192 × 8192 TIFF, the worst case Tempera can hold, is about 256 MB.
MAX_FILE_BYTES = 512 * 1024 * 1024


def image_filters() -> Gio.ListStore:
    store = Gio.ListStore.new(Gtk.FileFilter)

    images = Gtk.FileFilter(name=_("Images"))
    for mime in OPEN_MIME_TYPES:
        images.add_mime_type(mime)
    store.append(images)

    png = Gtk.FileFilter(name=_("PNG image"))
    png.add_mime_type("image/png")
    store.append(png)

    ora = Gtk.FileFilter(name=_("OpenRaster image, with layers"))
    ora.add_mime_type("image/openraster")
    store.append(ora)

    every = Gtk.FileFilter(name=_("All files"))
    every.add_pattern("*")
    store.append(every)
    return store


def image_error(message: str) -> GLib.Error:
    """A failure to read or write an image, raised the way GdkPixbuf reports its own."""
    return GLib.Error.new_literal(Gio.io_error_quark(), message, Gio.IOErrorEnum.FAILED)


def fits(width: int, height: int) -> bool:
    return width <= MAX_SIZE and height <= MAX_SIZE


def check_image_size(width: int, height: int) -> None:
    """Refuse an image bigger than a canvas can be, before its pixels are copied."""
    if not fits(width, height):
        # Short enough for a toast at the window's default width.
        raise image_error(
            _("Too large at {width} × {height} px (the limit is {limit})").format(
                width=width, height=height, limit=MAX_SIZE
            )
        )


def check_readable(file: Gio.File) -> None:
    """Refuse anything that is not an ordinary local file of a sensible size.

    Reading from a named pipe or a device such as /dev/zero would otherwise
    never finish, hanging the app with no way out.
    """
    if file.get_path() is None:
        # Tempera stays offline, so a web or network address is never fetched.
        raise image_error(
            _("“{name}” is not a file on this computer").format(name=file.get_basename())
        )

    info = file.query_info(
        "standard::type,standard::size", Gio.FileQueryInfoFlags.NONE, None
    )
    if info.get_file_type() != Gio.FileType.REGULAR:
        raise image_error(
            _("“{name}” is not an ordinary file").format(name=file.get_basename())
        )
    size = info.get_size()
    if size > MAX_FILE_BYTES:
        limit = MAX_FILE_BYTES // (1024 * 1024)
        raise image_error(
            _("Too big at {size} MB (the limit is {limit} MB)").format(
                size=size // (1024 * 1024), limit=limit
            )
        )


def is_openraster(file: Gio.File) -> bool:
    """Whether a file holds layers as OpenRaster: by its first bytes, which say so,
    or else by its name."""
    if os.path.splitext(file.get_basename())[1].lower() == ".ora":
        return True
    stream = file.read(None)
    try:
        start = stream.read_bytes(64, None).get_data()
    finally:
        stream.close(None)
    # A zip whose first member, stored as it is, is named "mimetype" and says so.
    return start[:4] == b"PK\x03\x04" and start[30:54] == b"mimetypeimage/openraster"


def _read_layers(file: Gio.File) -> list[Layer]:
    try:
        with open(file.get_path(), "rb") as stream:
            _width, _height, layers = read_openraster(stream)
    except OpenRasterError as error:
        raise image_error(str(error)) from None
    except OSError as error:
        raise image_error(error.strerror or str(error)) from None
    return layers


def load_layers(file: Gio.File) -> list[Layer]:
    """The layers of an image file, bottom first: its own if it keeps them, or one
    of the picture. Raises GLib.Error when it cannot be read."""
    check_readable(file)
    if is_openraster(file):
        return _read_layers(file)
    return [Layer(_decode(file), _("Background"))]


def load_surface(file: Gio.File) -> cairo.ImageSurface:
    """Decode an image file into a surface, raising GLib.Error when it cannot be.

    A file with layers comes as the picture it shows.
    """
    check_readable(file)
    if is_openraster(file):
        layers = _read_layers(file)
        surface = layers[0].surface
        return flatten(layers, 0, 0, surface.get_width(), surface.get_height())
    return _decode(file)


def _decode(file: Gio.File) -> cairo.ImageSurface:
    """Decode a flat image file, one GdkPixbuf can read.

    A small file can declare enormous dimensions, so the size is checked as soon
    as the loader has read the header rather than after decoding gigabytes.
    """
    declared = (0, 0)
    read_bytes = 0

    def on_size_prepared(loader, width, height):
        nonlocal declared
        declared = (width, height)
        if not fits(width, height):
            # The loader goes on to decode into whatever size is set here, so
            # shrink it to nothing rather than let it allocate the real thing.
            loader.set_size(1, 1)

    # Opened first: a loader that is never closed warns when it is freed.
    stream = file.read(None)
    loader = GdkPixbuf.PixbufLoader()
    loader.connect("size-prepared", on_size_prepared)
    try:
        while fits(*declared) and read_bytes <= MAX_FILE_BYTES:
            chunk = stream.read_bytes(LOAD_CHUNK, None)
            if chunk.get_size() == 0:
                break
            # A file can grow, or report a size it does not keep to.
            read_bytes += chunk.get_size()
            loader.write_bytes(chunk)
        loader.close()
    except GLib.Error:
        # Closing twice is harmless.
        try:
            loader.close()
        except GLib.Error:
            pass
        # Cutting a too-large image short is expected to upset the decoder.
        if fits(*declared):
            raise
    finally:
        stream.close(None)

    check_image_size(*declared)
    # Cameras and phones store a photo sideways and say which way up it goes;
    # ignoring that would open portrait photos lying on their side.
    return surface_from_pixbuf(loader.get_pixbuf().apply_embedded_orientation())


def load_document(file: Gio.File) -> Document:
    document = Document(layers=load_layers(file))
    document.file = file
    return document


def default_extension(layered: bool) -> str:
    """What a name gets when it needs one: OpenRaster for a picture with layers to keep."""
    return LAYERED_EXTENSION if layered else DEFAULT_EXTENSION


def with_default_extension(file: Gio.File, layered: bool = False) -> Gio.File:
    """The file to save to, with .png added unless the name ends in a format Tempera writes.

    Otherwise a name without an extension, or with one such as .gif, would get
    PNG data under a name that says something else. A picture with layers gets
    .ora instead, which keeps them.
    """
    if format_for(file) is not None:
        return file
    return file.get_parent().get_child(file.get_basename() + default_extension(layered))


def save_as_name(file: Gio.File | None, layered: bool = False) -> str:
    """The name Save As suggests for a file: its own, or as PNG if its format cannot be written.

    For a picture with layers, the name is kept but made OpenRaster, so the
    layers are kept too unless the user picks otherwise.
    """
    if file is None:
        return _("Untitled") + default_extension(layered)
    name = file.get_basename()
    if layered:
        return os.path.splitext(name)[0] + LAYERED_EXTENSION
    if format_for(file) is not None:
        return name
    return os.path.splitext(name)[0] + DEFAULT_EXTENSION


def format_for(file: Gio.File) -> str | None:
    """The format a file's extension asks for, or None if Tempera cannot write it."""
    # The name rather than the path, which a network location does not have.
    extension = os.path.splitext(file.get_basename())[1].lower()
    return EXTENSION_FORMATS.get(extension)


def image_to_save(document: Document, file: Gio.File) -> tuple[object, str]:
    """What to write and the format to write it in, or raise if it cannot be done.

    For OpenRaster that is copies of the layers; for the other formats, the
    picture as it shows, as a pixbuf.

    Taken on the main thread, before the encoding goes off to a worker: it is a
    copy, so painting on while the file is written cannot change what is saved.
    """
    image_format = format_for(file)
    if image_format is None:
        extension = os.path.splitext(file.get_basename())[1]
        raise image_error(
            _("Cannot save images as {extension}").format(extension=extension)
            if extension
            else _("Cannot save an image without a file extension")
        )
    if image_format == "ico" and max(document.width, document.height) > ICO_MAX_SIZE:
        raise image_error(
            _("ICO images can be at most {size} × {size} px").format(size=ICO_MAX_SIZE)
        )

    if image_format == LAYERED_FORMAT:
        layers = [
            Layer(copy_surface(layer.surface), layer.name, layer.visible, layer.opacity)
            for layer in document.layers
        ]
        return (layers, document.width, document.height), image_format
    if image_format in FLATTEN_FORMATS:
        # These formats have no alpha channel, so composite onto white first.
        flattened = new_surface(document.width, document.height)
        cr = cairo.Context(flattened)
        cr.set_source_surface(document.flattened(), 0, 0)
        cr.paint()
        flattened.flush()
        with_alpha = Gdk.pixbuf_get_from_surface(flattened, 0, 0, document.width, document.height)
        # These encoders reject an alpha channel outright, so drop it.
        pixbuf = GdkPixbuf.Pixbuf.new(
            GdkPixbuf.Colorspace.RGB, False, 8, document.width, document.height
        )
        pixbuf.fill(0xFFFFFFFF)
        with_alpha.composite(
            pixbuf, 0, 0, document.width, document.height,
            0, 0, 1, 1, GdkPixbuf.InterpType.NEAREST, 255,
        )
    else:
        pixbuf = document.to_pixbuf()
    return pixbuf, image_format


def encode_image(picture, image_format: str, quality: int) -> GLib.Bytes:
    """Encode what image_to_save() gave, in memory. Slow for a large picture, so worth a worker thread."""
    if image_format == LAYERED_FORMAT:
        stream = io.BytesIO()
        write_openraster(stream, *picture)
        return GLib.Bytes.new(stream.getvalue())
    pixbuf = picture
    options = (["quality"], [str(quality)]) if image_format == "jpeg" else ([], [])
    _ok, data = pixbuf.save_to_bufferv(image_format, *options)
    return GLib.Bytes.new(data)


def save_document(document: Document, file: Gio.File, quality: int = 90) -> None:
    """Save now, in this thread. The window uses save_document_async instead."""
    picture, image_format = image_to_save(document, file)
    depth = document.save_point()
    data = encode_image(picture, image_format, quality)
    # Encoded in memory first, then swapped in whole: writing straight to the
    # file would truncate the original before an encoder or a full disk failed.
    file.replace_contents(data.get_data(), None, False, Gio.FileCreateFlags.NONE, None)
    document.file = file
    document.mark_saved(depth)


def load_surface_async(
    file: Gio.File,
    on_surface: Callable[[cairo.ImageSurface], None],
    on_error: Callable[[str], None],
) -> None:
    """Decode an image in the background, so a big or slow file does not freeze the window."""

    def done(result):
        if isinstance(result, GLib.Error):
            on_error(result.message)
        else:
            on_surface(result)

    run_in_background(lambda: load_surface(file), done)


def load_document_async(
    file: Gio.File,
    on_document: Callable[[Document], None],
    on_error: Callable[[str], None],
) -> None:
    def done(result):
        if isinstance(result, GLib.Error):
            on_error(result.message)
            return
        # Made here rather than in the worker: a document is only ever touched
        # on the UI thread.
        document = Document(layers=result)
        document.file = file
        on_document(document)

    run_in_background(lambda: load_layers(file), done)


def save_document_async(
    document: Document,
    file: Gio.File,
    on_saved: Callable[[], None],
    on_error: Callable[[str], None],
    quality: int = 90,
) -> None:
    """Encode in the background and write asynchronously, marking what was written as saved."""
    try:
        picture, image_format = image_to_save(document, file)
    except GLib.Error as error:
        on_error(error.message)
        return
    depth = document.save_point()

    def on_written(source, result):
        try:
            source.replace_contents_finish(result)
        except GLib.Error as error:
            on_error(error.message)
            return
        document.file = file
        document.mark_saved(depth)
        on_saved()

    def done(result):
        if isinstance(result, GLib.Error):
            on_error(result.message)
            return
        file.replace_contents_bytes_async(
            result, None, False, Gio.FileCreateFlags.NONE, None, on_written
        )

    run_in_background(lambda: encode_image(picture, image_format, quality), done)
