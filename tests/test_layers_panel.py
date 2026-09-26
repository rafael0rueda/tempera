# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The layers panel, and the layer actions in the window."""

import pytest
from gi.repository import Adw, Gio, GLib

from tempera import recent_files, settings
from tempera import document as document_module
from tempera.document import Document, new_surface
from tempera.file_io import save_as_name, with_default_extension
from tempera.window import TemperaWindow
from tempera.window import layers as layers_module
from tempera.window.layers_panel import LayerDrag

from pixels import paint_pixel, pixel_at

RED = (1.0, 0.0, 0.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)


@pytest.fixture(scope="module")
def application():
    app = Adw.Application(
        application_id="io.github.rafael0rueda.Tempera.LayerTests",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )
    app.register(None)
    return app


@pytest.fixture
def window(application, monkeypatch, tmp_path):
    monkeypatch.setattr(recent_files, "_recent_file_path", lambda: tmp_path / "recent-files.txt")
    monkeypatch.setattr(settings, "_settings_path", lambda: tmp_path / "settings.ini")
    window = TemperaWindow(application, Document(new_surface(20, 20, WHITE)))
    yield window
    window.destroy()


def act(window, name, parameter=None):
    window.activate_action(f"win.{name}", parameter)


def enabled(window, name) -> bool:
    return window.lookup_action(name).get_enabled()


def rows(window):
    panel = window._layers_panel
    return [(row.layer.name, row.index) for row in panel._rows]


def selected(window) -> int:
    return window._layers_panel.list.get_selected_row().index


def test_the_panel_starts_hidden_and_the_header_shows_it(window):
    assert not window._layers_strip.get_visible()
    act(window, "layers-panel")
    assert window._layers_strip.get_visible()


def test_a_new_layer_goes_above_and_brings_the_panel_up(window):
    act(window, "add-layer")
    document = window.canvas.document
    assert [layer.name for layer in document.layers] == ["Background", "Layer 2"]
    assert window._layers_strip.get_visible()
    # Top first, as they stack, with the current one selected.
    assert rows(window) == [("Layer 2", 1), ("Background", 0)]
    assert selected(window) == 1


def test_what_the_layers_allow_is_all_that_is_offered(window):
    assert not enabled(window, "delete-layer")
    assert not enabled(window, "merge-layer-down")
    assert not enabled(window, "flatten-image")
    assert not enabled(window, "raise-layer") and not enabled(window, "lower-layer")
    act(window, "add-layer")
    assert enabled(window, "delete-layer") and enabled(window, "merge-layer-down")
    assert not enabled(window, "raise-layer") and enabled(window, "lower-layer")
    act(window, "lower-layer")
    assert enabled(window, "raise-layer") and not enabled(window, "lower-layer")
    assert not enabled(window, "merge-layer-down")


def test_moving_choosing_merging_and_flattening(window):
    document = window.canvas.document
    act(window, "add-layer")
    top = document.layer
    act(window, "lower-layer")
    assert document.layers[0] is top and document.current == 0
    act(window, "layer-above")
    assert document.current == 1
    act(window, "layer-below")
    assert document.current == 0
    act(window, "raise-layer")
    act(window, "merge-layer-down")
    assert len(document.layers) == 1
    act(window, "add-layer")
    act(window, "add-layer")
    act(window, "flatten-image")
    assert len(document.layers) == 1


def test_the_layer_actions_wait_while_a_stroke_is_under_way(window):
    window.canvas._drag_origin = (0.0, 0.0)
    act(window, "add-layer")
    assert len(window.canvas.document.layers) == 1
    window.canvas._drag_origin = None


def test_a_paste_lands_on_its_layer_before_the_layers_change(window):
    document = window.canvas.document
    window.canvas.begin_paste(new_surface(3, 3, RED), 5, 5)
    act(window, "add-layer")
    assert not window.canvas.has_floating
    assert pixel_at(document.layers[0].surface, 6, 6) == (255, 0, 0, 255)
    assert pixel_at(document.layers[1].surface, 6, 6)[3] == 0


def test_the_limit_on_layers_is_said(window, monkeypatch):
    monkeypatch.setattr(document_module, "MAX_LAYERS", 1)
    monkeypatch.setattr(layers_module, "MAX_LAYERS", 1)
    toasts = []
    window.show_toast = toasts.append
    window._sync_layer_actions()
    assert not enabled(window, "add-layer")
    window._arrange(lambda document: document.add_layer())
    assert toasts and "1" in toasts[0]


def test_clicking_a_row_makes_its_layer_current(window):
    act(window, "add-layer")
    panel = window._layers_panel
    panel.list.select_row(panel._rows[1])
    assert window.canvas.document.current == 0


def test_the_eye_hides_and_shows_a_layer(window):
    act(window, "add-layer")
    row = window._layers_panel._rows[0]
    row.eye.set_active(False)
    assert not window.canvas.document.layers[1].visible
    assert window._layers_panel._rows[0].eye.get_icon_name() == "view-conceal-symbolic"
    window.canvas.document.undo()
    assert window._layers_panel._rows[0].eye.get_active()


def test_the_opacity_slider_is_one_step_to_undo(window):
    act(window, "add-layer")
    panel = window._layers_panel
    for value in (90, 60, 30):
        panel.opacity_scale.set_value(value)
    document = window.canvas.document
    assert document.layer.opacity == pytest.approx(0.3)
    assert panel.opacity_value.get_label() == "30%"
    assert panel._rows[0].opacity.get_visible()
    document.undo()
    assert document.layer.opacity == 1.0
    assert panel.opacity_scale.get_value() == 100


def test_renaming_a_layer(window):
    act(window, "rename-layer")
    dialog = window.get_visible_dialog()
    assert isinstance(dialog, Adw.AlertDialog)
    dialog.get_extra_child().set_text("  Sky  ")
    dialog.emit("response", "rename")
    assert window.canvas.document.layer.name == "Sky"
    assert rows(window) == [("Sky", 0)]


def test_a_blank_name_is_not_taken(window):
    act(window, "rename-layer")
    dialog = window.get_visible_dialog()
    dialog.get_extra_child().set_text("   ")
    dialog.emit("response", "rename")
    assert window.canvas.document.layer.name == "Background"


def test_a_row_dropped_on_another_takes_its_place(window):
    for _each in range(2):
        act(window, "add-layer")
    document = window.canvas.document
    bottom = document.layers[0]
    target = window._layers_panel._rows[0]  # the top layer's row
    assert target._on_drop(None, LayerDrag(0), 0, 0)
    assert document.layers[2] is bottom
    assert not target._on_drop(None, LayerDrag(target.index), 0, 0)


def test_thumbnails_follow_the_layers(window):
    act(window, "add-layer")
    panel = window._layers_panel
    panel._refresh_thumbnails()
    before = [row.thumbnail.texture for row in panel._rows]
    assert all(before)
    document = window.canvas.document
    document.begin_change()
    paint_pixel(document.surface, 3, 3, RED)
    document.finish_change()
    panel._refresh_thumbnails()
    after = [row.thumbnail.texture for row in panel._rows]
    # Only the layer painted on is drawn again.
    assert after[0] is not before[0] and after[1] is before[1]
    document.rotate(True)
    panel._refresh_thumbnails()
    assert all(row.thumbnail.texture is not old for row, old in zip(panel._rows, after))


def test_a_picture_with_layers_opens_with_the_panel_showing(window):
    document = Document(new_surface(5, 5, WHITE))
    document.add_layer()
    window._set_document(document)
    assert window._layers_strip.get_visible()
    assert rows(window) == [("Layer 2", 1), ("Background", 0)]


def test_the_panel_is_remembered(window, application):
    act(window, "layers-panel")
    window._save_preferences()
    other = TemperaWindow(application)
    try:
        assert other._layers_strip.get_visible()
    finally:
        other.destroy()


def test_saving_a_picture_with_layers_flat_says_so_once(window, tmp_path):
    document = window.canvas.document
    document.add_layer()
    toasts = []
    window.toasts.add_toast = toasts.append
    for _time in range(2):
        window._write_now(Gio.File.new_for_path(str(tmp_path / "flat.png")), None, None)
        context = GLib.MainContext.default()
        while window._busy:
            context.iteration(True)
    assert "merged" in toasts[0].get_title()
    assert toasts[0].get_action_name() == "win.save-as"
    assert "merged" not in toasts[1].get_title()


def test_save_as_suggests_openraster_for_a_picture_with_layers():
    png = Gio.File.new_for_path("/tmp/cat.png")
    assert save_as_name(png, layered=True) == "cat.ora"
    assert save_as_name(png) == "cat.png"
    assert save_as_name(None, layered=True) == "Untitled.ora"
    assert save_as_name(None) == "Untitled.png"
    bare = Gio.File.new_for_path("/tmp/cat")
    assert with_default_extension(bare, layered=True).get_basename() == "cat.ora"
    assert with_default_extension(bare).get_basename() == "cat.png"


def test_the_menu_can_show_the_layers_too(window):
    model = window._main_menu.get_menu_model()
    actions = set()
    for section in range(model.get_n_items()):
        items = model.get_item_link(section, "section")
        for index in range(items.get_n_items()):
            action = items.get_item_attribute_value(index, "action", None)
            if action is not None:
                actions.add(action.get_string())
    assert "win.layers-panel" in actions
