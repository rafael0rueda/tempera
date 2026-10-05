# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Transparent selection: the secondary colour is left out of what is moved or pasted."""

import cairo
import pytest
from gi.repository import Gdk, GLib

from tempera.canvas import Canvas
from tempera.color import ColorState, rgba
from tempera.document import Document, new_surface
from tempera.regions import without_color
from tempera.window import TemperaWindow

from driving import FakeGesture
from pixels import paint_pixel, pixel_at

WHITE = (1.0, 1.0, 1.0, 1.0)
RED = (1.0, 0.0, 0.0, 1.0)
RED_PIXEL = (255, 0, 0, 255)
WHITE_PIXEL = (255, 255, 255, 255)


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


# A colour mixed in the editor, which is not a whole number of 255ths


def test_a_mixed_colour_painted_with_a_brush_is_left_out(canvas):
    mixed = Gdk.RGBA()
    mixed.red, mixed.green, mixed.blue, mixed.alpha = 0.4391, 0.5527, 0.7723, 1.0
    surface = new_surface(12, 12, WHITE)
    cr = cairo.Context(surface)
    cr.set_source_rgba(mixed.red, mixed.green, mixed.blue, 1.0)
    cr.set_line_width(8)
    cr.move_to(2, 6)
    cr.line_to(10, 6)
    cr.stroke()
    assert pixel_at(without_color(surface, mixed), 6, 6)[3] == 0


# Picked up and put down


def lift_and_land(canvas, selection=(16, 16, 20, 20), grab=(26, 26)):
    canvas.select_region(*selection)
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, *grab)
    canvas._on_drag_end(gesture, 0, 0)
    assert canvas._paste is not None
    canvas.commit_paste()


@pytest.mark.parametrize("transparent", [False, True])
def test_a_selection_put_straight_back_changes_nothing(canvas, transparent):
    document = canvas.document
    canvas.colors.secondary = rgba("#ff0000")
    canvas.transparent_selection = transparent
    lift_and_land(canvas)
    assert pixel_at(document.surface, 26, 26) == RED_PIXEL
    assert pixel_at(document.surface, 18, 18) == WHITE_PIXEL
    assert not document.can_undo and not document.modified


def test_what_a_transparent_selection_leaves_out_stays_where_it_was(canvas):
    document = canvas.document
    # Red is left out, so it is the white around the dot that moves.
    canvas.colors.secondary = rgba("#ff0000")
    canvas.transparent_selection = True
    paint_pixel(document.surface, 18, 18, (0.0, 0.0, 1.0, 1.0))
    move(canvas, (16, 16, 20, 20), (26, 26), (0, 30))
    # The dot was never carried away, so it is still there, not emptied to white.
    assert pixel_at(document.surface, 26, 26) == RED_PIXEL
    # What was carried is gone from where it was and has landed below.
    assert pixel_at(document.surface, 18, 18) == WHITE_PIXEL
    assert pixel_at(document.surface, 18, 48) == (0, 0, 255, 255)
    document.undo()
    assert pixel_at(document.surface, 18, 18) == (0, 0, 255, 255)
