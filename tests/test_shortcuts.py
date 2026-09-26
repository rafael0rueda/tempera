# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest
from gi.repository import Adw, Gdk, Gio

from tempera import settings, shortcuts

SHIFT = Gdk.ModifierType.SHIFT_MASK
CONTROL = Gdk.ModifierType.CONTROL_MASK
NONE = Gdk.ModifierType(0)


@pytest.fixture(scope="module")
def application():
    app = Adw.Application(
        application_id="io.github.rafael0rueda.Tempera.ShortcutTests",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )
    app.register(None)
    return app


@pytest.fixture(autouse=True)
def settings_file(monkeypatch, tmp_path):
    path = tmp_path / "settings.ini"
    monkeypatch.setattr(settings, "_settings_path", lambda: path)
    return path


def test_defaults_keep_the_keys_tempera_has_always_had():
    expected = {
        "win.new": ["<Control>n"],
        "win.open": ["<Control>o"],
        "win.save": ["<Control>s"],
        "win.save-as": ["<Control><Shift>s"],
        "win.select-all": ["<Control>a"],
        "win.cut": ["<Control>x"],
        "win.copy": ["<Control>c"],
        "win.paste": ["<Control>v"],
        "win.undo": ["<Control>z"],
        "win.redo": ["<Control><Shift>z", "<Control>y"],
        "win.swap-colors": ["x"],
        "win.resize": ["<Control>e"],
        "win.zoom-in": ["<Control>plus", "<Control>equal", "<Control>KP_Add"],
        "win.zoom-out": ["<Control>minus", "<Control>KP_Subtract"],
        "win.zoom-reset": ["<Control>0", "<Control>KP_0"],
        "app.quit": ["<Control>q"],
        "win.tool::pencil": ["p"],
        "win.tool::brush": ["b"],
        "win.tool::eraser": ["e"],
        "win.shape::line": ["l"],
        "win.shape::rectangle": ["r"],
        "win.shape::ellipse": ["o"],
        "win.tool::text": ["t"],
        "win.tool::fill": ["f"],
        "win.tool::picker": ["k"],
        "win.tool::select": ["s"],
    }
    for action, keys in expected.items():
        assert shortcuts.keys_for(action) == keys


def test_default_keys_are_unique_and_usable():
    seen = set()
    for shortcut in shortcuts.SHORTCUTS.values():
        for key in shortcut.defaults:
            assert shortcuts.problem_with(key) is None, key
            assert shortcuts.normalize(key) not in seen, key
            seen.add(shortcuts.normalize(key))


def test_bare_keys_are_the_ones_that_type():
    assert shortcuts.is_bare("p")
    assert shortcuts.is_bare("<Shift>p")
    assert not shortcuts.is_bare("<Control>p")
    assert not shortcuts.is_bare("<Alt>p")


@pytest.mark.parametrize(
    "accel", ["Left", "<Shift>Up", "Return", "<Control>Return", "Tab", "Escape", "Delete", "BackSpace"]
)
def test_keys_the_canvas_uses_are_refused(accel):
    assert "kept for the canvas" in shortcuts.problem_with(accel)


def test_unparseable_accelerator_is_refused():
    assert shortcuts.problem_with("<Control>") is not None
    assert shortcuts.problem_with("not-a-key") is not None


def test_shift_letter_is_recorded_as_shift_plus_the_letter():
    accel = shortcuts.accelerator_from_key(Gdk.KEY_S, SHIFT, SHIFT)
    assert accel == shortcuts.normalize("<Shift>s")


def test_shifted_symbol_drops_the_shift_it_used():
    accel = shortcuts.accelerator_from_key(Gdk.KEY_question, SHIFT | CONTROL, SHIFT)
    assert accel == shortcuts.normalize("<Control>question")


def test_shift_on_a_key_without_case_is_kept():
    accel = shortcuts.accelerator_from_key(Gdk.KEY_F5, SHIFT, NONE)
    assert accel == shortcuts.normalize("<Shift>F5")


def test_assigning_a_key_is_saved_and_applied(application):
    shortcuts.assign(application, "win.crop", "<Control><Shift>x")

    assert shortcuts.keys_for("win.crop") == ["<Shift><Control>x"]
    assert shortcuts.is_customized("win.crop")
    assert application.get_accels_for_action("win.crop") == ["<Shift><Control>x"]


def test_assigning_the_default_key_clears_the_override(application):
    shortcuts.assign(application, "win.new", "<Control>F11")
    shortcuts.assign(application, "win.new", "<Control>n")
    assert not shortcuts.any_customized()


def test_disabling_a_shortcut(application):
    shortcuts.assign(application, "win.save", None)
    assert shortcuts.keys_for("win.save") == []
    assert application.get_accels_for_action("win.save") == []


def test_assigning_a_taken_key_moves_it(application):
    assert shortcuts.find_conflict("<Control>e", "win.crop").action == "win.resize"

    shortcuts.assign(application, "win.crop", "<Control>e")

    assert shortcuts.keys_for("win.crop") == ["<Control>e"]
    assert shortcuts.keys_for("win.resize") == []


def test_taking_one_of_several_keys_leaves_the_others(application):
    shortcuts.assign(application, "win.crop", "<Control>y")
    assert shortcuts.keys_for("win.redo") == ["<Shift><Control>z"]


def test_reset_restores_the_default(application):
    shortcuts.assign(application, "win.new", "<Control>F11")
    shortcuts.reset(application, "win.new")
    assert shortcuts.keys_for("win.new") == ["<Control>n"]
    assert not shortcuts.is_customized("win.new")


def test_reset_leaves_out_a_default_key_now_used_elsewhere(application):
    shortcuts.assign(application, "win.crop", "<Control>e")
    shortcuts.reset(application, "win.resize")
    assert shortcuts.keys_for("win.crop") == ["<Control>e"]
    assert shortcuts.keys_for("win.resize") == []


def test_reset_all(application):
    shortcuts.assign(application, "win.crop", "<Control>e")
    shortcuts.assign(application, "win.tool::pencil", "<Shift>p")
    shortcuts.reset(application)
    assert not shortcuts.any_customized()
    assert shortcuts.keys_for("win.resize") == ["<Control>e"]
    assert application.get_accels_for_action("win.tool::pencil") == ["p"]


def test_damaged_or_unknown_entries_are_ignored(settings_file):
    settings_file.write_text(
        "[shortcuts]\n"
        "win.new = <Control>m\n"
        "win.open = not<a>key\n"
        "win.save = Left\n"
        "win.gone = <Control>g\n",
        encoding="utf-8",
    )
    assert shortcuts.keys_for("win.new") == ["<Control>m"]
    assert shortcuts.keys_for("win.open") == ["<Control>o"]
    assert shortcuts.keys_for("win.save") == ["<Control>s"]


def test_nothing_fires_while_suspended(application):
    shortcuts.suspend(application, True)
    try:
        assert application.get_accels_for_action("win.new") == []
    finally:
        shortcuts.suspend(application, False)
    assert application.get_accels_for_action("win.new") == ["<Control>n"]


def test_every_shape_has_its_own_key():
    from tempera.tools import SHAPE_IDS

    for shape in SHAPE_IDS:
        assert shortcuts.keys_for(f"win.shape::{shape}"), shape


def test_a_shape_key_changed_in_tempera_1_0_carries_over(settings_file):
    settings_file.write_text("[shortcuts]\nwin.tool::rectangle = <Shift>r\n", encoding="utf-8")
    assert shortcuts.keys_for("win.shape::rectangle") == ["<Shift>r"]
