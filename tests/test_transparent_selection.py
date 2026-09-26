# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transparent selection: the secondary colour is left out of what is moved or pasted."""

import pytest
from gi.repository import Adw, Gdk, Gio, GLib

from tempera import recent_files, settings
from tempera.canvas import Canvas
from tempera.color import ColorState, rgba
from tempera.document import Document, new_surface
from tempera.regions import without_color
from tempera.window import TemperaWindow

from pixels import paint_pixel, pixel_at

WHITE = (1.0, 1.0, 1.0, 1.0)
RED = (1.0, 0.0, 0.0, 1.0)
RED_PIXEL = (255, 0, 0, 255)
WHITE_PIXEL = (255, 255, 255, 255)


class FakeGesture:
    def get_current_button(self):
        return Gdk.BUTTON_PRIMARY

    def get_current_event_state(self):
        return Gdk.ModifierType(0)


def test_one_colour_is_left_out_exactly():
    surface = new_surface(3, 1, WHITE)
    paint_pixel(surface, 1, 0, RED)
    paint_pixel(surface, 2, 0, (0.99, 0.99, 0.99, 1.0))
    result = without_color(surface, rgba("#ffffff"))
    assert pixel_at(result, 0, 0)[3] == 0
    assert pixel_at(result, 1, 0) == RED_PIXEL
    # Near white is not white.
    assert pixel_at(result, 2, 0)[3] == 255
    # The surface it was made from is untouched.
    assert pixel_at(surface, 0, 0) == WHITE_PIXEL


@pytest.fixture
def canvas():
    """A red dot on white, the secondary colour."""
    surface = new_surface(60, 60, WHITE)
    for x in range(24, 28):
        for y in range(24, 28):
            paint_pixel(surface, x, y, RED)
    colors = ColorState()
    colors.secondary = rgba("#ffffff")
    canvas = Canvas(Document(surface), colors)
    canvas.select_tool("select")
    return canvas


def move(canvas, selection, grab, by):
    canvas.select_region(*selection)
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, *grab)
    canvas._on_drag_update(gesture, *by)
    canvas._on_drag_end(gesture, *by)
    canvas.commit_paste()


def test_moving_a_selection_normally_carries_its_background_along(canvas):
    document = canvas.document
    paint_pixel(document.surface, 30, 42, (0.0, 0.0, 1.0, 1.0))
    move(canvas, (16, 16, 20, 20), (26, 26), (0, 10))
    # The white around the dot came along and covers the blue pixel.
    assert pixel_at(document.surface, 30, 42) == WHITE_PIXEL
    assert pixel_at(document.surface, 26, 36) == RED_PIXEL


def test_a_transparent_selection_leaves_the_secondary_colour_behind(canvas):
    document = canvas.document
    paint_pixel(document.surface, 30, 42, (0.0, 0.0, 1.0, 1.0))
    canvas.transparent_selection = True
    # Moved down over the blue pixel: the white around the dot does not cover it.
    move(canvas, (16, 16, 20, 20), (26, 26), (0, 10))
    assert pixel_at(document.surface, 30, 42) == (0, 0, 255, 255)
    assert pixel_at(document.surface, 26, 36) == RED_PIXEL


def test_turning_it_on_or_changing_colour_while_floating_shows_at_once(canvas):
    canvas.select_region(16, 16, 20, 20)
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 26, 26)
    canvas._on_drag_update(gesture, 0, 10)
    paste = canvas._paste
    assert pixel_at(paste.surface, 0, 0) == WHITE_PIXEL
    canvas.transparent_selection = True
    assert pixel_at(paste.surface, 0, 0)[3] == 0
    canvas.colors.secondary = rgba("#ff0000")
    assert pixel_at(paste.surface, 0, 0) == WHITE_PIXEL
    assert pixel_at(paste.surface, 10, 10)[3] == 0
    canvas.transparent_selection = False
    assert pixel_at(paste.surface, 10, 10) == RED_PIXEL
    canvas._on_drag_end(gesture, 0, 10)


def test_a_paste_leaves_it_out_too(canvas):
    canvas.transparent_selection = True
    canvas.begin_paste(new_surface(4, 4, WHITE), 40, 40)
    assert pixel_at(canvas._paste.surface, 1, 1)[3] == 0


# In the window


@pytest.fixture(scope="module")
def application():
    app = Adw.Application(
        application_id="io.github.rafael0rueda.Tempera.TransparentTests",
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


def test_the_option_is_shared_by_the_selection_tools_and_remembered(window, application):
    window.lookup_action("transparent-selection").change_state(GLib.Variant.new_boolean(True))
    assert window.canvas.transparent_selection
    window._save_preferences()
    other = TemperaWindow(application)
    try:
        assert other.canvas.transparent_selection
    finally:
        other.destroy()


def test_its_toggles_wear_the_secondary_colour(window):
    window.colors.secondary = rgba("#3584e4")
    assert len(window._left_out_chips) == 2
    assert all(chip.color.equal(rgba("#3584e4")) for chip in window._left_out_chips)
