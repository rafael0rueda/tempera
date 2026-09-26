# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Turning, skewing and stretching what floats over the canvas."""

import math

import cairo
import pytest
from gi.repository import Gdk

from tempera.canvas import Canvas, FloatingPaste
from tempera.canvas.floating import ROTATE_GRIP_OFFSET
from tempera.color import ColorState
from tempera.document import Document, new_surface

from pixels import paint_pixel, pixel_at

WHITE = (1.0, 1.0, 1.0, 1.0)
RED = (1.0, 0.0, 0.0, 1.0)
BLUE = (0.0, 0.0, 1.0, 1.0)
RED_PIXEL = (255, 0, 0, 255)
BLUE_PIXEL = (0, 0, 255, 255)


def two_tone(width=4, height=2):
    """Red on the left half, blue on the right."""
    surface = new_surface(width, height, RED)
    for x in range(width // 2, width):
        for y in range(height):
            paint_pixel(surface, x, y, BLUE)
    return surface


def close(a, b):
    return all(abs(p - q) < 1e-6 for p, q in zip(a, b))


# The geometry


def test_an_upright_paste_lands_as_it_always_has():
    paste = FloatingPaste(two_tone(), 10.4, 20.6)
    assert not paste.transformed
    surface, x, y = paste.landing()
    assert (x, y) == (10, 21)
    assert surface is paste.surface
    assert paste.bounds() == (10.4, 20.6, 4, 2)


def test_the_box_s_frame_and_the_image_s_agree():
    paste = FloatingPaste(two_tone(), 10, 20, angle=0.7, shear_x=0.3)
    for point in ((0, 0), (4, 2), (1.5, 0.25)):
        assert close(paste.to_box(*paste.to_image(*point)), point)
    # It turns about its middle.
    assert close(paste.to_image(2, 1), (12, 21))


def test_a_quarter_turn_lands_pixel_for_pixel():
    paste = FloatingPaste(two_tone(), 10, 10, angle=math.pi / 2)
    surface, x, y = paste.landing()
    # Clockwise: what was on the right is now at the bottom.
    assert (x, y) == (11, 9)
    assert (surface.get_width(), surface.get_height()) == (2, 4)
    assert pixel_at(surface, 0, 0) == RED_PIXEL and pixel_at(surface, 1, 1) == RED_PIXEL
    assert pixel_at(surface, 0, 3) == BLUE_PIXEL and pixel_at(surface, 1, 2) == BLUE_PIXEL


def test_turning_follows_the_pointer_around_the_middle():
    grabbed = FloatingPaste(new_surface(10, 10, RED), 0, 0)
    paste = FloatingPaste(new_surface(10, 10, RED), 0, 0)
    # From straight above the middle to straight right of it: a quarter turn.
    paste.rotate_from(grabbed, (5, -10), (20, 5), snap=False)
    assert paste.angle == pytest.approx(math.pi / 2)
    paste.rotate_from(grabbed, (5, -10), (5 + math.cos(math.radians(-50)) * 10, 5 + math.sin(math.radians(-50)) * 10), snap=True)
    assert math.degrees(paste.angle) == pytest.approx(45)
    # Right round again is upright, exactly.
    paste.rotate_from(grabbed, (5, -10), (5, -20), snap=False)
    assert paste.angle == 0 and not paste.transformed


def test_skewing_by_the_top_leaves_the_bottom_where_it_was():
    grabbed = FloatingPaste(new_surface(10, 20, RED), 30, 30)
    paste = FloatingPaste(new_surface(10, 20, RED), 30, 30)
    paste.skew_from(grabbed, "n", (35, 30), (45, 30))
    corners = paste.corners()
    assert close(corners[0], (40, 30)) and close(corners[1], (50, 30))
    assert close(corners[3], (30, 50)) and close(corners[2], (40, 50))


def test_skewing_by_the_right_leaves_the_left_where_it_was():
    grabbed = FloatingPaste(new_surface(10, 20, RED), 30, 30)
    paste = FloatingPaste(new_surface(10, 20, RED), 30, 30)
    paste.skew_from(grabbed, "e", (40, 40), (40, 45))
    corners = paste.corners()
    assert close(corners[0], (30, 30)) and close(corners[3], (30, 50))
    assert close(corners[1], (40, 35)) and close(corners[2], (40, 55))


def test_skewing_both_ways_stops_short_of_folding_flat():
    grabbed = FloatingPaste(new_surface(10, 10, RED), 30, 30, shear_x=0.9)
    paste = FloatingPaste(new_surface(10, 10, RED), 30, 30, shear_x=0.9)
    paste.skew_from(grabbed, "e", (40, 35), (40, 45))
    assert paste.shear_y == 0.0


def test_a_turned_paste_stretches_along_its_own_sides():
    grabbed = FloatingPaste(new_surface(10, 10, RED), 30, 30, angle=math.pi / 2)
    paste = FloatingPaste(new_surface(10, 10, RED), 30, 30, angle=math.pi / 2)
    # Turned a quarter, its own right side faces down: pulling the "e" grip
    # down 5 more makes it 15 wide, its "w" side staying put.
    west_before = grabbed.handles()["w"]
    east = grabbed.handles()["e"]
    paste.resize_from(grabbed, "e", (east[0], east[1] + 5))
    assert paste.box_size == pytest.approx((15, 10))
    assert close(paste.handles()["w"], west_before)


def test_the_grip_that_turns_sits_above_or_else_below():
    high = FloatingPaste(new_surface(10, 10, RED), 5, 2)
    grip, anchor = high.rotate_grip()
    assert anchor == (10, 12) and grip[1] > 12
    low = FloatingPaste(new_surface(10, 10, RED), 5, 50)
    grip, anchor = low.rotate_grip()
    assert anchor == (10, 50) and grip == (10, 50 - ROTATE_GRIP_OFFSET)


# On the canvas


class FakeGesture:
    def __init__(self, state=Gdk.ModifierType(0)):
        self.state = state

    def get_current_button(self):
        return Gdk.BUTTON_PRIMARY

    def get_current_event_state(self):
        return self.state


@pytest.fixture
def canvas():
    """A red-and-blue block at (40, 40)-(80, 60) on white, selected."""
    surface = new_surface(120, 120, WHITE)
    cr = cairo.Context(surface)
    cr.set_source_surface(two_tone(40, 20), 40, 40)
    cr.paint()
    canvas = Canvas(Document(surface), ColorState())
    canvas.select_tool("select")
    canvas.select_region(40, 40, 40, 20)
    return canvas


def drag(canvas, start, end, state=Gdk.ModifierType(0)):
    gesture = FakeGesture(state)
    canvas._on_drag_begin(gesture, *start)
    canvas._on_drag_update(gesture, end[0] - start[0], end[1] - start[1])
    canvas._on_drag_end(gesture, end[0] - start[0], end[1] - start[1])


def test_a_selection_has_a_grip_to_turn_it_by(canvas):
    assert canvas._handles()["rotate"] == (60, 40 - ROTATE_GRIP_OFFSET)


def test_turning_a_selection_lifts_it_and_lands_as_one_step(canvas):
    grip = canvas._handles()["rotate"]
    # Round to the right of the middle: a quarter turn clockwise.
    drag(canvas, grip, (60 + 40, 50))
    paste = canvas._paste
    assert paste.angle == pytest.approx(math.pi / 2, abs=0.05)
    canvas._paste.angle = math.pi / 2
    canvas.commit_paste()
    surface = canvas.document.surface
    # Upright it was 40 × 20 about (60, 50); turned, 20 × 40, blue below.
    assert pixel_at(surface, 60, 35) == RED_PIXEL
    assert pixel_at(surface, 60, 65) == BLUE_PIXEL
    assert pixel_at(surface, 45, 50) == (255, 255, 255, 255)
    canvas.document.undo()
    assert pixel_at(surface, 45, 50) == RED_PIXEL


def test_ctrl_on_a_side_grip_skews_what_floats(canvas):
    drag(canvas, (60, 50), (60, 50))  # lift it without moving it
    assert canvas._paste is not None
    drag(canvas, (60, 40), (70, 40), Gdk.ModifierType.CONTROL_MASK)
    assert canvas._paste.shear_x == pytest.approx(-0.5)
    assert canvas._paste.box_size == (40, 20)


def test_ctrl_on_a_selection_s_grip_still_copies_rather_than_skews(canvas):
    drag(canvas, (80, 50), (100, 50), Gdk.ModifierType.CONTROL_MASK)
    paste = canvas._paste
    assert paste.shear_x == 0 and paste.shear_y == 0
    assert paste.width == 60
    assert paste.source is None  # a copy: nothing is emptied where it was


def test_a_turned_paste_s_grips_point_the_way_they_face(canvas):
    drag(canvas, (60, 50), (60, 50))
    canvas._paste.angle = math.pi / 2
    cursors = []
    canvas.set_cursor = lambda cursor: cursors.append(cursor.get_name())
    canvas._set_cursor("e")
    canvas._set_cursor("n")
    assert cursors == ["ns-resize", "ew-resize"]


def test_a_turned_paste_off_the_top_left_lands_what_is_on_the_canvas(canvas):
    canvas.begin_paste(two_tone(40, 20), 0, 0)
    canvas._paste.angle = math.radians(30)
    surface, x, y = canvas._paste.landing()
    assert (x, y) == (0, 0)
    canvas.commit_paste()


def test_the_canvas_keeps_room_for_a_grip_below_the_image():
    canvas = Canvas(Document(new_surface(50, 50, WHITE)), ColorState())
    canvas.select_tool("select")
    canvas.select_region(0, 0, 50, 50)
    grip = canvas._handles()["rotate"]
    assert grip[1] > 50
    assert canvas._content_size[1] > grip[1]
