# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import resource
import struct
import time
import zlib
from pathlib import Path

import pytest
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from tempera.document import MAX_SIZE, Document, new_surface
from tempera.file_io import (
    ICO_MAX_SIZE,
    MAX_FILE_BYTES,
    OPEN_MIME_TYPES,
    format_for,
    image_filters,
    load_document,
    load_document_async,
    load_surface,
    save_as_name,
    save_document,
    save_document_async,
    with_default_extension,
)

from pixels import paint_pixel, pixel_at

RED = (1.0, 0.0, 0.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)
TRANSPARENT = (0.0, 0.0, 0.0, 0.0)


def gio_file(path: Path) -> Gio.File:
    return Gio.File.new_for_path(str(path))


# format_for


def test_format_for_known_extensions():
    assert format_for(gio_file(Path("a.png"))) == "png"
    assert format_for(gio_file(Path("a.jpg"))) == "jpeg"
    assert format_for(gio_file(Path("a.jpeg"))) == "jpeg"
    assert format_for(gio_file(Path("a.bmp"))) == "bmp"
    assert format_for(gio_file(Path("a.tiff"))) == "tiff"
    assert format_for(gio_file(Path("a.tif"))) == "tiff"
    assert format_for(gio_file(Path("a.webp"))) == "webp"
    assert format_for(gio_file(Path("a.ico"))) == "ico"


def test_format_for_is_case_insensitive():
    assert format_for(gio_file(Path("a.PNG"))) == "png"
    assert format_for(gio_file(Path("a.JPG"))) == "jpeg"


def test_format_for_is_none_for_a_format_tempera_cannot_write():
    assert format_for(gio_file(Path("a.xyz"))) is None
    assert format_for(gio_file(Path("a.gif"))) is None
    assert format_for(gio_file(Path("a"))) is None


def test_format_for_a_network_location_without_a_local_path():
    file = Gio.File.new_for_uri("sftp://example.com/pictures/photo.JPG")
    assert file.get_path() is None
    assert format_for(file) == "jpeg"


# with_default_extension


def test_with_default_extension_adds_png_to_a_bare_name(tmp_path):
    file = with_default_extension(gio_file(tmp_path / "drawing"))
    assert file.get_path() == str(tmp_path / "drawing.png")


def test_with_default_extension_keeps_a_name_that_has_one(tmp_path):
    chosen = gio_file(tmp_path / "photo.jpg")
    assert with_default_extension(chosen).equal(chosen)


def test_with_default_extension_adds_png_after_a_format_it_cannot_write(tmp_path):
    file = with_default_extension(gio_file(tmp_path / "animation.gif"))
    assert file.get_path() == str(tmp_path / "animation.gif.png")


# save_as_name


def test_save_as_name_keeps_a_writable_name():
    assert save_as_name(gio_file(Path("photo.jpg"))) == "photo.jpg"


def test_save_as_name_suggests_png_for_a_format_it_cannot_write():
    assert save_as_name(gio_file(Path("animation.gif"))) == "animation.png"


# image_filters


def test_image_filters_offers_images_png_openraster_and_all_files():
    store = image_filters()
    names = [store.get_item(i).get_name() for i in range(store.get_n_items())]
    assert names == ["Images", "PNG image", "OpenRaster image, with layers", "All files"]
    assert all(isinstance(store.get_item(i), Gtk.FileFilter) for i in range(store.get_n_items()))


def test_images_filter_includes_gif_and_ico():
    _name, rules = image_filters().get_item(0).to_gvariant().unpack()
    mime_types = {pattern for _kind, pattern in rules}
    assert mime_types == set(OPEN_MIME_TYPES)
    assert {"image/gif", "image/vnd.microsoft.icon"} <= mime_types


# load_document


def test_load_document_reads_pixels_and_sets_the_file(tmp_path):
    path = tmp_path / "loaded.png"
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 2, 2)
    pixbuf.fill(0x00FF00FF)  # opaque green, RGBA byte order
    pixbuf.savev(str(path), "png", [], [])

    file = gio_file(path)
    document = load_document(file)

    assert (document.width, document.height) == (2, 2)
    assert pixel_at(document.surface, 0, 0) == (0, 255, 0, 255)
    assert document.file == file


def jpeg_with_orientation(orientation: int) -> bytes:
    """A 40 × 20 JPEG, red in its stored top-left corner, tagged with an EXIF orientation."""
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 40, 20)
    pixbuf.fill(0xFFFFFFFF)
    pixbuf.new_subpixbuf(0, 0, 8, 8).fill(0xFF0000FF)
    _ok, data = pixbuf.save_to_bufferv("jpeg", ["quality"], ["100"])
    # One little-endian TIFF directory holding only the Orientation tag (0x0112).
    tiff = b"II*\0" + struct.pack("<I", 8) + struct.pack("<HHHIHHI", 1, 0x0112, 3, 1, orientation, 0, 0)
    exif = b"Exif\0\0" + tiff
    app1 = b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif
    return data[:2] + app1 + data[2:]


def is_red(pixel) -> bool:
    red, green, blue, _alpha = pixel
    return red > 200 and green < 80 and blue < 80


def test_load_surface_turns_a_photo_the_way_its_camera_says(tmp_path):
    path = tmp_path / "portrait.jpg"
    # 6: stored lying on its side, shown turned a quarter clockwise.
    path.write_bytes(jpeg_with_orientation(6))

    surface = load_surface(gio_file(path))

    assert (surface.get_width(), surface.get_height()) == (20, 40)
    assert is_red(pixel_at(surface, 16, 3))
    assert not is_red(pixel_at(surface, 3, 3))


def test_load_surface_leaves_an_upright_photo_alone(tmp_path):
    path = tmp_path / "landscape.jpg"
    path.write_bytes(jpeg_with_orientation(1))

    surface = load_surface(gio_file(path))

    assert (surface.get_width(), surface.get_height()) == (40, 20)
    assert is_red(pixel_at(surface, 3, 3))


def write_png(path: Path, width: int, height: int) -> None:
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
    pixbuf.fill(0xFFFFFFFF)
    pixbuf.savev(str(path), "png", [], [])


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def test_load_surface_accepts_the_largest_canvas_size(tmp_path):
    path = tmp_path / "wide.png"
    write_png(path, MAX_SIZE, 1)
    assert load_surface(gio_file(path)).get_width() == MAX_SIZE


def test_load_surface_refuses_an_image_wider_than_a_canvas_can_be(tmp_path):
    path = tmp_path / "too-wide.png"
    write_png(path, MAX_SIZE + 1, 1)
    with pytest.raises(GLib.Error, match=f"{MAX_SIZE + 1} × 1 px"):
        load_surface(gio_file(path))


def test_load_surface_refuses_a_decompression_bomb_without_decoding_it(tmp_path):
    # A few kilobytes of PNG declaring 60000 × 60000 pixels: about 14 GB decoded.
    side = 60000
    header = struct.pack(">IIBBBBB", side, side, 8, 6, 0, 0, 0)
    rows = zlib.compress(b"\0" * (side * 4 + 1) * 64, 9)
    path = tmp_path / "bomb.png"
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", rows)
        + png_chunk(b"IEND", b"")
    )

    peak_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    with pytest.raises(GLib.Error, match="60000 × 60000 px"):
        load_surface(gio_file(path))
    peak_growth_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - peak_before
    assert peak_growth_kib < 256 * 1024


def test_load_surface_refuses_a_file_that_is_not_local():
    with pytest.raises(GLib.Error, match="not a file on this computer"):
        load_surface(Gio.File.new_for_uri("https://example.com/picture.png"))


def test_load_surface_raises_for_a_missing_file(tmp_path):
    with pytest.raises(GLib.Error):
        load_surface(gio_file(tmp_path / "missing.png"))


def test_load_surface_raises_for_a_file_that_is_not_an_image(tmp_path):
    path = tmp_path / "notes.png"
    path.write_text("not really a picture")
    with pytest.raises(GLib.Error):
        load_surface(gio_file(path))


# save_document


def test_save_and_load_png_round_trips_alpha(tmp_path):
    document = Document(new_surface(2, 2, WHITE))
    paint_pixel(document.surface, 1, 0, RED)
    paint_pixel(document.surface, 0, 1, TRANSPARENT)

    file = gio_file(tmp_path / "out.png")
    save_document(document, file)

    reloaded = load_document(file)
    assert pixel_at(reloaded.surface, 0, 0) == (255, 255, 255, 255)
    assert pixel_at(reloaded.surface, 1, 0) == (255, 0, 0, 255)
    assert pixel_at(reloaded.surface, 0, 1) == (0, 0, 0, 0)


def test_save_document_updates_document_state(tmp_path):
    document = Document(new_surface(1, 1, WHITE))
    document.modified = True
    seen = []
    document.connect("state-changed", lambda *_args: seen.append(True))

    file = gio_file(tmp_path / "out.png")
    save_document(document, file)

    assert document.file == file
    assert document.modified is False
    assert seen == [True]


def test_save_document_jpeg_quality_affects_file_size(tmp_path):
    document = Document(new_surface(64, 64, WHITE))
    for x in range(64):
        for y in range(64):
            paint_pixel(document.surface, x, y, RED if (x + y) % 2 else WHITE)

    low = tmp_path / "low.jpg"
    high = tmp_path / "high.jpg"
    save_document(document, gio_file(low), quality=10)
    save_document(document, gio_file(high), quality=95)

    assert low.stat().st_size < high.stat().st_size
    # Still a readable image at either quality.
    reloaded = load_document(gio_file(high))
    assert (reloaded.width, reloaded.height) == (64, 64)


def test_save_document_flattens_transparency_onto_white_for_bmp(tmp_path):
    document = Document(new_surface(2, 1, WHITE))
    paint_pixel(document.surface, 0, 0, TRANSPARENT)
    paint_pixel(document.surface, 1, 0, RED)

    file = gio_file(tmp_path / "out.bmp")
    save_document(document, file)

    reloaded = load_document(file)
    # BMP has no alpha channel: the transparent pixel composites onto white,
    # and the opaque one round-trips losslessly.
    assert pixel_at(reloaded.surface, 0, 0) == (255, 255, 255, 255)
    assert pixel_at(reloaded.surface, 1, 0) == (255, 0, 0, 255)


def test_a_failed_save_leaves_the_existing_file_untouched(tmp_path):
    path = tmp_path / "icon.ico"
    path.write_bytes(b"the original icon")
    document = Document(new_surface(ICO_MAX_SIZE + 1, 16, WHITE))
    document.modified = True

    with pytest.raises(GLib.Error, match=f"at most {ICO_MAX_SIZE}"):
        save_document(document, gio_file(path))

    assert path.read_bytes() == b"the original icon"
    assert document.file is None
    assert document.modified is True


def test_save_document_refuses_a_format_it_cannot_write(tmp_path):
    path = tmp_path / "animation.gif"
    path.write_bytes(b"the original animation")
    document = Document(new_surface(2, 2, WHITE))

    with pytest.raises(GLib.Error, match=r"Cannot save images as \.gif"):
        save_document(document, gio_file(path))

    assert path.read_bytes() == b"the original animation"
    assert document.file is None


def test_save_document_raises_rather_than_crashing_for_a_missing_folder(tmp_path):
    with pytest.raises(GLib.Error):
        save_document(Document(new_surface(1, 1, WHITE)), gio_file(tmp_path / "gone" / "out.png"))


def test_save_document_writes_through_a_symlink(tmp_path):
    target = tmp_path / "real.png"
    write_png(target, 1, 1)
    link = tmp_path / "link.png"
    link.symlink_to(target)
    document = Document(new_surface(3, 2, WHITE))

    save_document(document, gio_file(link))

    assert link.is_symlink()
    reloaded = load_document(gio_file(target))
    assert (reloaded.width, reloaded.height) == (3, 2)


# files that are not ordinary images


def test_load_surface_refuses_a_named_pipe(tmp_path):
    path = tmp_path / "pipe.png"
    os.mkfifo(path)
    # Reading one would block for as long as nothing writes to it.
    with pytest.raises(GLib.Error, match="not an ordinary file"):
        load_surface(gio_file(path))


def test_load_surface_refuses_a_directory(tmp_path):
    with pytest.raises(GLib.Error, match="not an ordinary file"):
        load_surface(gio_file(tmp_path))


def test_load_surface_refuses_a_file_far_too_big_to_be_an_image(tmp_path, monkeypatch):
    path = tmp_path / "huge.png"
    write_png(path, 2, 2)
    monkeypatch.setattr("tempera.file_io.MAX_FILE_BYTES", 8)
    with pytest.raises(GLib.Error, match="the limit is"):
        load_surface(gio_file(path))


def test_the_file_size_limit_leaves_room_for_the_largest_image():
    # An uncompressed RGBA image of the largest canvas, and then some.
    assert MAX_FILE_BYTES > MAX_SIZE * MAX_SIZE * 4


def encoded(image_format: str) -> bytes:
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, image_format == "png", 8, 16, 16)
    pixbuf.fill(0x3366CCFF)
    _ok, data = pixbuf.save_to_bufferv(image_format, [], [])
    return data


@pytest.mark.parametrize("image_format", ["png", "jpeg", "bmp", "tiff"])
def test_a_damaged_file_is_refused_or_read_but_never_crashes(tmp_path, image_format):
    """Decoders see files from anywhere, so they must fail politely, not take the app down."""
    good = encoded(image_format)
    path = tmp_path / f"damaged.{image_format}"
    for broken in (good[: len(good) // 2], good[:8], good[::-1], bytes(len(good))):
        path.write_bytes(broken)
        try:
            surface = load_surface(gio_file(path))
        except GLib.Error:
            continue
        # Whatever it made of it still has to be a sane image.
        assert 0 < surface.get_width() <= MAX_SIZE
        assert 0 < surface.get_height() <= MAX_SIZE


def test_saving_writes_no_camera_metadata(tmp_path):
    """Photos carry EXIF, including where they were taken; a saved copy must not."""
    source = tmp_path / "photo.jpg"
    source.write_bytes(jpeg_with_orientation(6))
    document = Document(load_surface(gio_file(source)))

    saved = tmp_path / "copy.jpg"
    save_document(document, gio_file(saved))

    written = saved.read_bytes()
    assert b"Exif" not in written
    assert b"\xff\xe1" not in written[:4096]


# OpenRaster: the layers kept


def layered_document() -> Document:
    document = Document(new_surface(6, 5, WHITE))
    document.add_layer()
    paint_pixel(document.surface, 2, 3, RED)
    document.rename_layer(1, "Ink")
    document.set_layer_opacity(1, 0.5)
    return document


def wait(condition, seconds: float = 5.0) -> None:
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        context.iteration(False)
    assert condition()


def test_saving_as_openraster_keeps_the_layers(tmp_path):
    document = layered_document()
    file = gio_file(tmp_path / "picture.ora")
    save_document(document, file)
    assert not document.modified
    assert document.file.equal(file)

    reloaded = load_document(file)
    assert [layer.name for layer in reloaded.layers] == ["Background", "Ink"]
    assert reloaded.layers[1].opacity == 0.5
    assert pixel_at(reloaded.layers[1].surface, 2, 3) == (255, 0, 0, 255)
    assert reloaded.file.equal(file)


def test_a_layered_picture_saved_flat_is_the_picture_as_it_shows(tmp_path):
    document = layered_document()
    document.set_layer_opacity(1, 1.0)
    path = tmp_path / "picture.png"
    save_document(document, gio_file(path))
    reloaded = load_document(gio_file(path))
    assert len(reloaded.layers) == 1
    assert pixel_at(reloaded.surface, 2, 3) == (255, 0, 0, 255)
    assert pixel_at(reloaded.surface, 0, 0) == (255, 255, 255, 255)


def test_openraster_is_told_by_its_first_bytes_whatever_its_name(tmp_path):
    save_document(layered_document(), gio_file(tmp_path / "picture.ora"))
    renamed = tmp_path / "picture.dat"
    (tmp_path / "picture.ora").rename(renamed)
    assert len(load_document(gio_file(renamed)).layers) == 2


def test_dropping_an_openraster_file_brings_the_picture_as_it_shows(tmp_path):
    document = layered_document()
    document.set_layer_opacity(1, 1.0)
    save_document(document, gio_file(tmp_path / "picture.ora"))
    surface = load_surface(gio_file(tmp_path / "picture.ora"))
    assert pixel_at(surface, 2, 3) == (255, 0, 0, 255)
    assert pixel_at(surface, 0, 0) == (255, 255, 255, 255)


def test_a_damaged_openraster_file_says_why_it_cannot_be_opened(tmp_path):
    path = tmp_path / "broken.ora"
    path.write_bytes(b"PK\x03\x04 not really a zip")
    with pytest.raises(GLib.Error) as raised:
        load_document(gio_file(path))
    assert "OpenRaster" in raised.value.message


def test_openraster_opens_in_the_background_too(tmp_path):
    save_document(layered_document(), gio_file(tmp_path / "picture.ora"))
    opened = []
    load_document_async(gio_file(tmp_path / "picture.ora"), opened.append, pytest.fail)
    wait(lambda: opened)
    assert len(opened[0].layers) == 2


def test_openraster_saves_in_the_background_too(tmp_path):
    document = layered_document()
    saved = []
    save_document_async(document, gio_file(tmp_path / "picture.ora"), lambda: saved.append(True), pytest.fail)
    wait(lambda: saved)
    assert len(load_document(gio_file(tmp_path / "picture.ora")).layers) == 2
    assert not document.modified


def test_the_desktop_file_opens_openraster():
    assert "image/openraster" in OPEN_MIME_TYPES
    assert format_for(Gio.File.new_for_path("/tmp/a.ORA")) == "ora"
