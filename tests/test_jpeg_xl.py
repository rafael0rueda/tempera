# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""JPEG XL: written by the helper around libjxl, read like any other image.

Skipped where the helper has not been built (build-aux/build_native.sh builds
it, given libjxl to build against), unless TEMPERA_REQUIRE_JXL says it must be
there. What does not need it, runs without it.
"""

import os

import cairo
import pytest
from gi.repository import Adw, Gio, Gtk

from tempera import jxl
from tempera.document import Document, new_surface
from tempera.file_io import (
    OPEN_MIME_TYPES,
    format_for,
    format_of_filter,
    image_filters,
    load_document,
    save_document,
    with_default_extension,
    with_format,
)

from driving import wait_until
from pixels import paint_pixel, pixel_at

RED = (1.0, 0.0, 0.0, 1.0)
BLUE = (0.0, 0.0, 1.0, 1.0)
TRANSPARENT = (0.0, 0.0, 0.0, 0.0)

needs_helper = pytest.mark.skipif(
    not jxl.available() and not os.environ.get("TEMPERA_REQUIRE_JXL"),
    reason="the JPEG XL helper is not built",
)


def gio_file(path) -> Gio.File:
    return Gio.File.new_for_path(str(path))


def filter_names(store) -> list[str]:
    return [store.get_item(i).get_name() for i in range(store.get_n_items())]


def detailed_document(size: int = 256) -> Document:
    """A picture with something to lose: smooth colour under fine lines."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    cr = cairo.Context(surface)
    gradient = cairo.LinearGradient(0, 0, size, size)
    gradient.add_color_stop_rgb(0, 1, 0.2, 0.1)
    gradient.add_color_stop_rgb(1, 0.1, 0.3, 1)
    cr.set_source(gradient)
    cr.paint()
    cr.set_source_rgba(1, 1, 1, 0.8)
    for each in range(0, size, 3):
        cr.move_to(each, 0)
        cr.line_to(size - each, size)
        cr.set_line_width(0.5 + each % 2)
        cr.stroke()
    surface.flush()
    return Document(surface)


# Writing and reading back


@needs_helper
def test_quality_100_keeps_every_pixel_and_the_transparency(tmp_path):
    surface = new_surface(16, 16, TRANSPARENT)
    paint_pixel(surface, 3, 4, RED)
    paint_pixel(surface, 9, 9, (0.0, 0.0, 1.0, 0.5))
    path = tmp_path / "art.jxl"

    save_document(Document(surface), gio_file(path), quality=100)

    copy = load_document(gio_file(path)).surface
    assert (copy.get_width(), copy.get_height()) == (16, 16)
    assert pixel_at(copy, 3, 4) == (255, 0, 0, 255)
    assert pixel_at(copy, 0, 0)[3] == 0
    assert pixel_at(copy, 9, 9) == pixel_at(surface, 9, 9)
    assert bytes(copy.get_data()) == bytes(surface.get_data())


@needs_helper
def test_a_lower_quality_makes_a_smaller_file_that_still_opens(tmp_path):
    document = detailed_document()
    sizes = {}
    for quality in (20, 90, 100):
        path = tmp_path / f"{quality}.jxl"
        save_document(document, gio_file(path), quality=quality)
        sizes[quality] = path.stat().st_size
        copy = load_document(gio_file(path)).surface
        assert (copy.get_width(), copy.get_height()) == (256, 256)
    assert sizes[20] < sizes[90] < sizes[100]


@needs_helper
def test_a_picture_too_big_for_the_first_try_at_the_output_is_written_whole(tmp_path):
    # Far more than the room the encoder starts with, even losing nothing.
    path = tmp_path / "large.jxl"
    document = detailed_document(1024)
    save_document(document, gio_file(path), quality=100)
    assert path.stat().st_size > 64 * 1024
    copy = load_document(gio_file(path)).surface
    assert bytes(copy.get_data()) == bytes(document.surface.get_data())


# Without the helper


def test_without_the_helper_it_opens_but_is_not_offered_for_saving(monkeypatch):
    monkeypatch.setattr(jxl, "library", None)
    assert format_for(gio_file("/tmp/art.jxl")) is None
    assert "JPEG XL image" not in filter_names(image_filters(saving=True))
    assert "JPEG XL image" in filter_names(image_filters())
    assert "image/jxl" in OPEN_MIME_TYPES
    # A name typed with it gets a format that can be written.
    assert with_default_extension(gio_file("/tmp/art.jxl")).get_basename() == "art.jxl.png"


def test_a_helper_that_is_missing_broken_or_turned_off_is_done_without(monkeypatch, tmp_path):
    monkeypatch.setenv(jxl.ENVIRONMENT, "off")
    assert jxl._load() is None
    broken = tmp_path / jxl.LIBRARY_NAME
    broken.write_bytes(b"not a library")
    monkeypatch.setenv(jxl.ENVIRONMENT, str(broken))
    monkeypatch.setattr(jxl, "__file__", str(tmp_path / "jxl.py"))
    assert jxl._load() is None


@needs_helper
def test_a_helper_from_other_source_is_left_alone(monkeypatch):
    assert jxl.library.tempera_jxl_version() == jxl.VERSION
    monkeypatch.setattr(jxl, "VERSION", jxl.VERSION + 1)
    assert jxl._load() is None


# Choosing a format in the dialog


def test_a_filter_is_known_by_its_format():
    store = image_filters()
    by_name = {store.get_item(i).get_name(): store.get_item(i) for i in range(store.get_n_items())}
    assert format_of_filter(by_name["JPEG image"]) == "jpeg"
    assert format_of_filter(by_name["JPEG XL image"]) == "jxl"
    assert format_of_filter(by_name["PNG image"]) == "png"
    assert format_of_filter(by_name["OpenRaster image, with layers"]) == "ora"
    assert format_of_filter(by_name["Images"]) is None
    assert format_of_filter(by_name["All files"]) is None
    assert format_of_filter(None) is None


@pytest.mark.parametrize(
    "name, image_format, expected",
    [
        ("art.png", "jpeg", "art.jpg"),
        ("art.jpeg", "jpeg", "art.jpeg"),
        ("art.JPG", "jpeg", "art.JPG"),
        ("art.tiff", "png", "art.png"),
        ("art", "jpeg", "art.jpg"),
        ("art.v2", "ora", "art.v2.ora"),
        ("art.gif", "png", "art.gif.png"),
        ("art.png", "jxl", "art.jxl"),
    ],
)
def test_a_format_picked_in_the_dialog_renames_the_file(name, image_format, expected):
    assert with_format(gio_file(f"/tmp/{name}"), image_format).get_basename() == expected


class ChooserStandIn:
    """Gtk.FileChooserNative, answering as soon as it is shown as a person would."""

    made = []
    answer = None

    @classmethod
    def new(cls, title, parent, action, accept, cancel):
        chooser = cls()
        chooser.title, chooser.filters, chooser.name = title, [], None
        chooser.folder, chooser.handler, chooser.destroyed = None, None, False
        cls.made.append(chooser)
        return chooser

    def set_modal(self, modal):
        pass

    def add_filter(self, each):
        self.filters.append(each)

    def set_current_folder(self, folder):
        self.folder = folder

    def set_current_name(self, name):
        self.name = name

    def connect(self, _signal, handler):
        self.handler = handler

    def destroy(self):
        self.destroyed = True

    def show(self):
        file, self.filter_name = ChooserStandIn.answer
        self.file = file
        self.handler(self, Gtk.ResponseType.ACCEPT if file else Gtk.ResponseType.CANCEL)

    def get_file(self):
        return self.file

    def get_filter(self):
        return next(each for each in self.filters if each.get_name() == self.filter_name)


@pytest.fixture
def chooser(monkeypatch):
    monkeypatch.setattr(Gtk, "FileChooserNative", ChooserStandIn)
    monkeypatch.setattr(ChooserStandIn, "made", [])

    def answering(file, filter_name):
        ChooserStandIn.answer = (gio_file(file) if file else None, filter_name)

    return answering


def wait_until_idle(window):
    assert wait_until(lambda: not window._busy)


def answer(window, response="save"):
    dialog = window.get_visible_dialog()
    assert isinstance(dialog, Adw.AlertDialog)
    heading = dialog.get_heading()
    dialog.emit("response", response)
    dialog.force_close()
    return heading


def test_save_as_makes_the_format_picked_in_the_dialog(window, tmp_path, chooser):
    chooser(tmp_path / "art.png", "JPEG image")
    window._save_as()
    assert answer(window) == "JPEG Quality"
    wait_until_idle(window)
    assert (tmp_path / "art.jpg").read_bytes().startswith(b"\xff\xd8")
    assert not (tmp_path / "art.png").exists()
    assert window.canvas.document.file.get_basename() == "art.jpg"
    assert ChooserStandIn.made[-1].destroyed


def test_save_as_goes_by_the_name_when_no_single_format_was_picked(window, tmp_path, chooser):
    chooser(tmp_path / "art.bmp", "Images")
    window._save_as()
    wait_until_idle(window)
    assert (tmp_path / "art.bmp").read_bytes().startswith(b"BM")


def test_cancelling_the_dialog_saves_nothing(window, tmp_path, chooser):
    chooser(None, "Images")
    window._save_as()
    assert window.get_visible_dialog() is None
    assert not window._busy
    assert window._save_chooser is None


def test_a_name_changed_to_match_the_format_asks_before_replacing(window, tmp_path, chooser):
    (tmp_path / "art.jpg").write_bytes(b"keep me")
    chooser(tmp_path / "art.png", "JPEG image")
    window._save_as()
    assert answer(window, "cancel") == "Replace “art.jpg”?"
    assert (tmp_path / "art.jpg").read_bytes() == b"keep me"


def test_export_makes_the_format_picked_and_keeps_the_picture_s_own_file(
    window, tmp_path, chooser
):
    own = gio_file(tmp_path / "own.png")
    window.canvas.document.file = own
    chooser(tmp_path / "copy.png", "JPEG image")
    window._export_as()
    assert answer(window) == "JPEG Quality"
    wait_until_idle(window)
    assert (tmp_path / "copy.jpg").is_file()
    assert window.canvas.document.file is own
    assert ChooserStandIn.made[-1].folder.get_path() == str(tmp_path)


@needs_helper
def test_save_as_jpeg_xl_asks_starting_from_lossless(window, tmp_path, chooser):
    chooser(tmp_path / "art.png", "JPEG XL image")
    window._save_as()
    assert window._last_jxl_quality == 100
    assert answer(window) == "JPEG XL Quality"
    wait_until_idle(window)
    assert (tmp_path / "art.jxl").is_file()
    assert load_document(gio_file(tmp_path / "art.jxl")).width == window.canvas.document.width


@needs_helper
def test_ctrl_s_keeps_the_jpeg_xl_quality_without_asking(window, tmp_path):
    document = window.canvas.document
    paint_pixel(document.surface, 1, 1, BLUE)
    path = tmp_path / "art.jxl"
    document.file = gio_file(path)
    window._save()
    assert window.get_visible_dialog() is None
    wait_until_idle(window)
    copy = load_document(gio_file(path)).surface
    assert bytes(copy.get_data()) == bytes(document.flattened().get_data())


@needs_helper
def test_the_jpeg_xl_quality_is_kept_apart_from_the_jpeg_one(window, tmp_path):
    window._last_jpeg_quality = 40
    window._last_jxl_quality = 70
    window._write(gio_file(tmp_path / "art.jxl"))
    assert answer(window) == "JPEG XL Quality"
    wait_until_idle(window)
    assert window._last_jpeg_quality == 40
    assert window._last_jxl_quality == 70
