# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import time

import pytest
from gi.repository import Adw, Gio, GLib, Gtk

from tempera import interface_size, recent_files, settings
from tempera.preferences import PreferencesDialog, size_label
from tempera.window import PALETTE_BAR_HEIGHT, SIDEBAR_WIDTH, TemperaWindow


@pytest.fixture(autouse=True)
def default_size():
    """Every test starts, and leaves the display, at the default size."""
    interface_size.apply(interface_size.DEFAULT_SIZE)
    yield
    interface_size.apply(interface_size.DEFAULT_SIZE)


@pytest.fixture(scope="module")
def application():
    app = Adw.Application(
        application_id="io.github.rafael0rueda.Tempera.SizeTests",
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


def dpi() -> int:
    return Gtk.Settings.get_default().props.gtk_xft_dpi


@pytest.mark.parametrize(
    "text, size",
    [("150", 150), ("200", 200), ("", 100), ("big", 100), ("175", 100), ("-1", 100)],
)
def test_only_offered_sizes_are_taken_from_settings(text, size):
    assert interface_size.parse(text) == size


def test_lengths_scale_with_the_size():
    assert interface_size.scaled(40) == 40
    assert interface_size.scaled(40, 150) == 60
    interface_size.apply(200)
    assert interface_size.scaled(10) == 20


def test_the_default_size_leaves_the_theme_alone():
    assert interface_size.icon_stylesheet(100) == ""
    assert interface_size.control_stylesheet(100) == ""


def test_bigger_sizes_grow_icons_and_controls():
    assert "-gtk-icon-size: 32px" in interface_size.icon_stylesheet(200)
    controls = interface_size.control_stylesheet(200)
    assert ".tempera-tool { min-width: 76px; min-height: 76px; }" in controls
    # The slider knob stays centred on its trough as it grows.
    assert "min-width: 40px; min-height: 40px; margin: -18px;" in controls


@pytest.mark.parametrize("size", interface_size.SIZES)
def test_every_stylesheet_parses(size):
    errors = []
    for stylesheet in (interface_size.icon_stylesheet(size), interface_size.control_stylesheet(size)):
        provider = Gtk.CssProvider()
        provider.connect("parsing-error", lambda _provider, _section, error: errors.append(error))
        provider.load_from_string(stylesheet)
    assert errors == []


def test_text_follows_the_size_without_compounding():
    system = dpi()
    interface_size.apply(200)
    assert dpi() == 2 * system
    interface_size.apply(150)
    assert dpi() == round(1.5 * system)
    interface_size.apply(100)
    assert dpi() == system


def test_an_unknown_size_falls_back_to_the_default():
    system = dpi()
    interface_size.apply(175)
    assert interface_size.current() == 100
    assert dpi() == system


def wait_for(condition, seconds: float = 3.0) -> bool:
    """Let GTK restyle and lay out until the condition holds, or give up."""
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    # Wakes the loop now and then, so it waits for GTK instead of spinning.
    tick = GLib.timeout_add(20, lambda: GLib.SOURCE_CONTINUE)
    try:
        while not condition():
            if time.monotonic() > deadline:
                return False
            context.iteration(True)
        return True
    finally:
        GLib.source_remove(tick)


def width(widget: Gtk.Widget) -> int:
    return widget.measure(Gtk.Orientation.HORIZONTAL, -1)[0]


def test_tool_buttons_and_swatches_are_drawn_bigger(window):
    window.present()
    tool = window._sidebar.get_first_child().get_first_child()
    swatch = window._color_bar._palette_swatches[0]
    current = window._color_bar._primary_swatch

    window._set_interface_size(200)

    # The tool from the stylesheet, the palette (on the right) from the code.
    assert wait_for(lambda: width(tool) >= 76)
    assert width(swatch) >= 44
    assert width(current) >= 56


def test_preferences_open_from_the_menu_action(window):
    window.present()
    window.activate_action("win.preferences", None)
    dialog = window.get_visible_dialog()
    assert isinstance(dialog, PreferencesDialog)
    assert dialog.size_row.get_selected() == interface_size.SIZES.index(100)
    dialog.force_close()


def test_choosing_a_size_resizes_every_window_and_is_remembered(application, window):
    other = TemperaWindow(application)
    try:
        dialog = PreferencesDialog(window._set_interface_size)
        dialog.size_row.set_selected(interface_size.SIZES.index(150))

        assert interface_size.current() == 150
        assert settings.load_setting("interface-size") == "150"
        for each in (window, other):
            assert each._sidebar.get_size_request() == (round(SIDEBAR_WIDTH * 1.5), -1)
            assert each._palette_bar.get_size_request() == (-1, round(PALETTE_BAR_HEIGHT * 1.5))
        assert dialog.get_content_width() == 960
    finally:
        other.destroy()


def test_a_new_window_opens_at_the_chosen_size(application, window):
    interface_size.apply(200)
    other = TemperaWindow(application)
    try:
        assert other._sidebar.get_size_request() == (2 * SIDEBAR_WIDTH, -1)
    finally:
        other.destroy()


def test_resize_grips_grow_with_the_size(window):
    canvas = window.canvas
    # Just outside the grab distance at the default size, inside it at 200%.
    point = (canvas.document.width + 15, canvas.document.height + 15)
    assert canvas._handle_at(*point) is None

    window._set_interface_size(200)
    assert canvas._handle_at(*point) == "se"


def test_the_default_size_is_labelled():
    assert size_label(100) == "100% (Default)"
    assert size_label(150) == "150%"


def test_preferences_has_a_shortcut():
    from tempera.shortcuts import SHORTCUTS

    assert SHORTCUTS["win.preferences"].defaults == ("<Control>comma",)


def test_the_saved_size_is_applied_at_startup(monkeypatch, tmp_path):
    from tempera.main import TemperaApplication

    monkeypatch.setattr(settings, "_settings_path", lambda: tmp_path / "settings.ini")
    settings.save_settings({"interface-size": "125"})
    applied = []
    monkeypatch.setattr(interface_size, "apply", applied.append)

    app = TemperaApplication()
    app.set_application_id("io.github.rafael0rueda.Tempera.StartupSizeTest")
    app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    app.register(None)

    assert applied == [125]
