# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export As: a copy in another format, leaving the picture its own file."""

import time

import cairo
import pytest
from gi.repository import Adw, Gio, GLib

from tempera import recent_files, settings, shortcuts
from tempera.document import Document, new_surface
from tempera.file_io import export_name, load_document, save_document
from tempera.window import TemperaWindow

from pixels import paint_pixel, pixel_at

WHITE = (1.0, 1.0, 1.0, 1.0)
RED = (1.0, 0.0, 0.0, 1.0)


@pytest.fixture(scope="module")
def application():
    app = Adw.Application(
        application_id="io.github.rafael0rueda.Tempera.ExportTests",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )
    app.register(None)
    return app


@pytest.fixture
def window(application, monkeypatch, tmp_path):
    monkeypatch.setattr(recent_files, "_recent_file_path", lambda: tmp_path / "recent-files.txt")
    monkeypatch.setattr(settings, "_settings_path", lambda: tmp_path / "settings.ini")
    window = TemperaWindow(application)
    yield window
    window.destroy()


def layered_ora(tmp_path) -> Document:
    """A picture with a red dot on a second layer, saved as OpenRaster."""
    document = Document(new_surface(8, 8, WHITE))
    document.add_layer()
    paint_pixel(document.surface, 3, 3, RED)
    save_document(document, Gio.File.new_for_path(str(tmp_path / "art.ora")))
    return load_document(Gio.File.new_for_path(str(tmp_path / "art.ora")))


def wait_until_idle(window):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + 5
    while window._busy and time.monotonic() < deadline:
        context.iteration(False)
    assert not window._busy


def test_exporting_writes_the_picture_as_it_shows_and_keeps_its_own_file(window, tmp_path):
    document = layered_ora(tmp_path)
    window._set_document(document)
    document.begin_change()
    paint_pixel(document.surface, 5, 5, RED)
    document.finish_change()
    assert document.modified
    toasts = []
    window.show_toast = toasts.append

    exported = Gio.File.new_for_path(str(tmp_path / "art.png"))
    window._export(exported)
    wait_until_idle(window)

    copy = cairo.ImageSurface.create_from_png(str(tmp_path / "art.png"))
    assert pixel_at(copy, 3, 3) == (255, 0, 0, 255)
    assert pixel_at(copy, 5, 5) == (255, 0, 0, 255)
    assert pixel_at(copy, 0, 0) == (255, 255, 255, 255)
    # Still the OpenRaster picture, with its changes still to save.
    assert document.file.get_basename() == "art.ora"
    assert document.modified
    assert len(document.layers) == 2
    assert toasts == ["Exported art.png"]


def test_saving_after_an_export_still_saves_the_picture_s_own_file(window, tmp_path):
    document = layered_ora(tmp_path)
    window._set_document(document)
    window._export(Gio.File.new_for_path(str(tmp_path / "art.png")))
    wait_until_idle(window)
    window._save()
    wait_until_idle(window)
    assert not document.modified
    assert len(load_document(Gio.File.new_for_path(str(tmp_path / "art.ora"))).layers) == 2


def test_exporting_as_jpeg_asks_for_the_quality(window, tmp_path):
    window._export(Gio.File.new_for_path(str(tmp_path / "art.jpg")))
    dialog = window.get_visible_dialog()
    assert isinstance(dialog, Adw.AlertDialog)
    assert dialog.get_response_label("save") == "Export"
    dialog.emit("response", "save")
    wait_until_idle(window)
    assert (tmp_path / "art.jpg").is_file()


def test_the_next_export_starts_where_the_last_one_went(window, tmp_path):
    document = layered_ora(tmp_path)
    window._set_document(document)
    folder, name = window._export_start(document)
    assert folder.get_path() == str(tmp_path) and name == "art.png"

    elsewhere = tmp_path / "exports"
    elsewhere.mkdir()
    window._export(Gio.File.new_for_path(str(elsewhere / "shared.png")))
    wait_until_idle(window)
    folder, name = window._export_start(document)
    assert folder.get_path() == str(elsewhere) and name == "shared.png"
    # Another picture starts afresh.
    folder, name = window._export_start(Document())
    assert folder is None and name == "Untitled.png"


def test_export_names_come_from_the_picture_s_own():
    assert export_name(Gio.File.new_for_path("/tmp/art.ora")) == "art.png"
    assert export_name(None) == "Untitled.png"


def test_export_has_a_key_and_a_place_in_the_menu(window):
    assert shortcuts.keys_for("win.export-as") == ["<Control><Shift>e"]
    model = window._main_menu.get_menu_model()
    actions = set()
    for section in range(model.get_n_items()):
        items = model.get_item_link(section, "section")
        for index in range(items.get_n_items()):
            action = items.get_item_attribute_value(index, "action", None)
            if action is not None:
                actions.add(action.get_string())
    assert "win.export-as" in actions
