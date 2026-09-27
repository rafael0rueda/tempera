# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The size beside the slider: typed in, or chosen from the usual ones."""

import pytest
from gi.repository import Adw, Gio, GLib

from tempera import recent_files, settings
from tempera.text import font_size
from tempera.window import TemperaWindow
from tempera.window.options_bar import BRUSH_SIZE_PRESETS, FONT_SIZE_PRESETS


@pytest.fixture(scope="module")
def application():
    app = Adw.Application(
        application_id="io.github.rafael0rueda.Tempera.SizeFieldTests",
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


def use(window, tool):
    window.lookup_action("tool").change_state(GLib.Variant.new_string(tool))


def type_size(window, text):
    window._size_entry.set_text(text)
    window._size_entry.emit("activate")


def test_a_brush_size_can_be_typed(window):
    use(window, "brush")
    type_size(window, "17")
    assert window.canvas.brush_size == 17
    assert window._size_scale.get_value() == 17


def test_a_font_size_can_be_typed_with_or_without_its_unit(window):
    use(window, "text")
    type_size(window, "86 pt")
    assert font_size(window.canvas.font) == 86
    assert window._size_entry.get_text() == "86"
    assert window._size_unit.get_label() == "pt"


def test_a_size_past_the_slider_s_reach_is_kept_within_it(window):
    use(window, "brush")
    type_size(window, "500")
    assert window.canvas.brush_size == 64
    assert window._size_entry.get_text() == "64"
    type_size(window, "0")
    assert window.canvas.brush_size == 1


def test_what_is_not_a_number_puts_the_size_back(window):
    use(window, "brush")
    type_size(window, "12")
    type_size(window, "big")
    assert window.canvas.brush_size == 12
    assert window._size_entry.get_text() == "12"


def test_the_usual_sizes_are_offered_for_what_the_slider_serves(window):
    use(window, "brush")
    assert window._size_choices == BRUSH_SIZE_PRESETS
    use(window, "text")
    assert window._size_choices == FONT_SIZE_PRESETS
    row = window._size_list.get_row_at_index(FONT_SIZE_PRESETS.index(72))
    window._size_list.emit("row-activated", row)
    assert font_size(window.canvas.font) == 72


def test_the_size_now_is_picked_out_in_the_list(window):
    use(window, "text")
    type_size(window, "36")
    window._select_size_preset()
    assert window._size_list.get_selected_row().get_index() == FONT_SIZE_PRESETS.index(36)
    type_size(window, "37")
    window._select_size_preset()
    assert window._size_list.get_selected_row() is None


def test_typing_into_a_field_keeps_the_one_key_shortcuts_out_of_the_way(window, application):
    # GTK hands the window's shortcuts a key before the field with the focus.
    assert application.get_accels_for_action("win.tool::pencil") == ["p"]
    window.set_focus(window._size_entry)
    assert application.get_accels_for_action("win.tool::pencil") == []
    # Shortcuts with Ctrl still work.
    assert application.get_accels_for_action("win.undo") == ["<Control>z"]
    window.set_focus(None)
    assert application.get_accels_for_action("win.tool::pencil") == ["p"]
