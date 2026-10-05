# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Export As: a copy in another format, leaving the picture its own file."""


import cairo
from gi.repository import Adw, Gio, GLib

from tempera import shortcuts
from tempera.document import Document, new_surface
from tempera.file_io import export_name, load_document, save_document

from driving import wait_until
from pixels import paint_pixel, pixel_at

WHITE = (1.0, 1.0, 1.0, 1.0)
RED = (1.0, 0.0, 0.0, 1.0)


def layered_ora(tmp_path) -> Document:
    """A picture with a red dot on a second layer, saved as OpenRaster."""
    document = Document(new_surface(8, 8, WHITE))
    document.add_layer()
    paint_pixel(document.surface, 3, 3, RED)
    save_document(document, Gio.File.new_for_path(str(tmp_path / "art.ora")))
    return load_document(Gio.File.new_for_path(str(tmp_path / "art.ora")))


def wait_until_idle(window):
    assert wait_until(lambda: not window._busy)


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


# A file that cannot be read must not leave the window stuck


def test_a_damaged_file_leaves_the_window_able_to_save(window, tmp_path, monkeypatch):
    from tempera import file_io

    def broken(_file, _lost=None):
        raise RuntimeError("damaged beyond telling")

    monkeypatch.setattr(file_io, "load_layers", broken)
    failures = []
    window.show_failure = lambda heading, message, **_more: failures.append(message)
    window._open_file(Gio.File.new_for_path(str(tmp_path / "bad.ora")))
    assert window.canvas.frozen
    wait_until_idle(window)
    assert failures == ["damaged beyond telling"]
    assert not window.canvas.frozen


def test_the_picture_is_left_alone_while_another_is_read(window, tmp_path):
    layered_ora(tmp_path)
    old = window.canvas.document
    window._open_file(Gio.File.new_for_path(str(tmp_path / "art.ora")))
    assert window.canvas.is_dragging
    wait_until_idle(window)
    assert not window.canvas.is_dragging
    assert window.canvas.document is not old


def test_a_stroke_finished_while_saving_stays_unsaved(window, tmp_path):
    document = window.canvas.document
    for _each in range(60):
        document.begin_change()
        paint_pixel(document.surface, 0, 0, RED)
        document.commit_change()
    window._write_now(Gio.File.new_for_path(str(tmp_path / "busy.png")), None, None)
    document.begin_change()
    paint_pixel(document.surface, 1, 1, RED)
    document.commit_change()
    wait_until_idle(window)
    assert document.modified


# A file from another program is not written over without asking where


def foreign_ora(tmp_path):
    import io
    import zipfile

    stream = io.BytesIO()
    surface = new_surface(4, 4, RED)
    data = io.BytesIO()
    surface.write_to_png(data)
    with zipfile.ZipFile(stream, "w") as ora:
        ora.writestr("mimetype", "image/openraster")
        ora.writestr(
            "stack.xml",
            "<image w='4' h='4'><stack><layer src='a.png' composite-op='svg:multiply'/></stack></image>",
        )
        ora.writestr("a.png", data.getvalue())
    path = tmp_path / "krita.ora"
    path.write_bytes(stream.getvalue())
    return path


def test_a_file_holding_more_than_tempera_shows_is_saved_under_a_new_name(window, tmp_path, monkeypatch):
    path = foreign_ora(tmp_path)
    original = path.read_bytes()
    toasts = []
    window.show_toast = toasts.append
    window._open_file(Gio.File.new_for_path(str(path)))
    wait_until_idle(window)
    document = window.canvas.document
    assert document.lost == ("blending",)
    assert toasts and "how its layers blend" in toasts[-1]

    asked = []
    monkeypatch.setattr(window, "_save_as", lambda then=None, keep_layers=False: asked.append(True))
    window.activate_action("win.save", None)
    assert asked == [True]
    assert path.read_bytes() == original

    # Once saved by Tempera, the file is its own, and Ctrl+S writes straight to it.
    monkeypatch.undo()
    window.show_toast = toasts.append
    window._write_now(Gio.File.new_for_path(str(tmp_path / "mine.ora")), None, None)
    wait_until_idle(window)
    assert document.lost == ()


def test_a_save_that_fails_says_so_in_a_dialog_offering_another_place(window, tmp_path):
    failures = []
    window.show_failure = lambda heading, message, save_as=False: failures.append((heading, save_as))
    window._write_now(Gio.File.new_for_path(str(tmp_path / "no-such-folder" / "x.png")), None, None)
    wait_until_idle(window)
    assert failures == [("Could Not Save “x.png”", True)]
    assert window.canvas.document.file is None


def test_the_window_does_not_keep_a_replaced_picture_alive(window, tmp_path):
    import gc
    import weakref

    document = window.canvas.document
    window._export_now(Gio.File.new_for_path(str(tmp_path / "copy.png")), None)
    wait_until_idle(window)
    gone = weakref.ref(document)
    window._set_document(Document(new_surface(4, 4, WHITE)))
    del document
    gc.collect()
    assert gone() is None
