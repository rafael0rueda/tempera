# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""A held button holds on to what it took, whatever else happens meanwhile."""

from gi.repository import Gdk

from tempera.canvas import Canvas, FloatingPaste
from tempera.canvas.drags import CanvasResize, PasteGrab, PasteMove, Stroke
from tempera.color import ColorState
from tempera.document import Document, new_surface
from tempera.text import TextBox, TextStyle

from driving import FakeGesture
from pixels import pixel_at

RED = (1.0, 0.0, 0.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)
NO_KEYS = Gdk.ModifierType(0)


def make_canvas(size=100) -> Canvas:
    return Canvas(Document(new_surface(size, size, WHITE)), ColorState())


def key(canvas, keyval) -> bool:
    return canvas._on_key_pressed(None, keyval, 0, NO_KEYS)


def floating(canvas) -> FloatingPaste:
    canvas.begin_paste(new_surface(20, 20, RED), 40, 40)
    return canvas._paste


# Keys and actions that arrive while a grip is held


def test_escape_is_ignored_while_a_grip_is_held():
    canvas = make_canvas()
    paste = floating(canvas)
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 60, 60)
    assert isinstance(canvas._drag, PasteGrab)

    assert not key(canvas, Gdk.KEY_Escape)
    assert not key(canvas, Gdk.KEY_Return)
    assert canvas._paste is paste

    canvas._on_drag_update(gesture, 10, 10)
    canvas._on_drag_end(gesture, 10, 10)
    assert not canvas.is_dragging
    assert (paste.width, paste.height) == (30, 30)
    assert key(canvas, Gdk.KEY_Escape)
    assert canvas._paste is None


def test_a_paste_that_lands_while_its_grip_is_held_leaves_the_canvas_working():
    canvas = make_canvas()
    floating(canvas)
    gesture = FakeGesture()
    for press in ((60, 60), (50, 40 - 24)):
        canvas._on_drag_begin(gesture, *press)
        assert isinstance(canvas._drag, PasteGrab)
        # Something lands it behind the drag's back, as saving does.
        canvas.commit_floating()
        canvas._on_drag_update(gesture, 5, 5)
        canvas._on_drag_end(gesture, 5, 5)
        assert not canvas.is_dragging
        floating(canvas)
    canvas.cancel_floating()

    # The canvas still paints, and what it paints can be undone.
    canvas.select_tool("pencil")
    undo_steps = len(canvas.document._undo)
    canvas._on_drag_begin(gesture, 5, 5)
    canvas._on_drag_end(gesture, 0, 0)
    assert len(canvas.document._undo) == undo_steps + 1
    assert canvas.document.modified


def test_a_paste_that_lands_while_it_is_carried_stays_where_it_landed():
    canvas = make_canvas()
    floating(canvas)
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 50, 50)
    assert isinstance(canvas._drag, PasteMove)
    canvas.commit_floating()
    canvas._on_drag_update(gesture, 30, 30)
    canvas._on_drag_end(gesture, 30, 30)
    assert not canvas.is_dragging and canvas._paste is None
    assert pixel_at(canvas.document.surface, 45, 45) == (255, 0, 0, 255)
    assert pixel_at(canvas.document.surface, 75, 75) == (255, 255, 255, 255)


def test_a_drag_that_fails_still_lets_go():
    canvas = make_canvas()
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 5, 5)

    def broken(*_args):
        raise RuntimeError("the tool broke")

    canvas._drag.end = broken
    try:
        canvas._on_drag_end(gesture, 0, 0)
    except RuntimeError:
        pass
    assert canvas._drag is None and canvas._drag_origin is None


# A paste or a key that arrives in the middle of a stroke


def test_a_paste_that_arrives_during_a_stroke_waits_for_it_to_end():
    canvas = make_canvas()
    document = canvas.document
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 10, 10)
    assert isinstance(canvas._drag, Stroke)
    canvas._on_drag_update(gesture, 10, 0)

    # The clipboard answers only now.
    canvas.begin_paste(new_surface(8, 8, RED), 60, 60)
    assert canvas._paste is None

    canvas._on_drag_update(gesture, 20, 0)
    canvas._on_drag_end(gesture, 20, 0)
    # The stroke is whole, one step that undo takes back, and then the paste floats.
    assert canvas._paste is not None and canvas._paste.x == 60
    assert len(document._undo) == 1 and document.modified
    assert pixel_at(document.surface, 28, 10) != (255, 255, 255, 255)
    canvas.cancel_floating()
    document.undo()
    assert pixel_at(document.surface, 12, 10) == (255, 255, 255, 255)
    assert pixel_at(document.surface, 28, 10) == (255, 255, 255, 255)


def test_delete_is_ignored_in_the_middle_of_a_stroke():
    canvas = make_canvas()
    canvas.select_all()
    canvas.select_tool("pencil")
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 10, 10)
    assert not key(canvas, Gdk.KEY_Delete)
    assert not key(canvas, Gdk.KEY_Left)
    canvas._on_drag_end(gesture, 5, 0)
    assert len(canvas.document._undo) == 1


def test_a_drag_taken_away_ends_where_it_got_to():
    canvas = make_canvas()
    document = canvas.document
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 10, 10)
    canvas._on_drag_update(gesture, 10, 0)
    canvas._on_drag_cancel(gesture, None)
    assert not canvas.is_dragging
    assert len(document._undo) == 1 and document.modified
    # A release that follows all the same changes nothing.
    canvas._on_drag_end(gesture, 10, 0)
    assert len(document._undo) == 1


def test_pulling_the_canvas_larger_is_a_drag_of_its_own():
    canvas = make_canvas()
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 100, 100)
    assert isinstance(canvas._drag, CanvasResize)
    canvas._on_drag_update(gesture, 20, 10)
    assert canvas._resize_size == (120, 110)
    canvas._on_drag_end(gesture, 20, 10)
    assert canvas._resize_size is None
    assert (canvas.document.width, canvas.document.height) == (120, 110)


# Landing what has gone past the top-left


def test_a_paste_stretched_past_the_corner_while_turned_lands_where_it_shows():
    surface = new_surface(40, 20, RED)
    paste = FloatingPaste(surface, x=10, y=10)
    # As turning it, pulling its left side out and setting it upright again leaves it.
    paste.x = -20.0
    paste.scale_x = 1.75
    assert not paste.transformed
    pixels, x, y = paste.landing()
    assert (x, y) == (0, 10)
    # What was left of the canvas is cut off, rather than everything shifted right.
    assert pixels.get_width() == 70 - 20


def test_an_upright_paste_cannot_be_stretched_past_the_corner():
    canvas = make_canvas()
    paste = floating(canvas)
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 40, 40)
    canvas._on_drag_update(gesture, -90, -90)
    canvas._on_drag_end(gesture, -90, -90)
    assert (paste.x, paste.y) == (0, 0)
    assert (paste.width, paste.height) == (60, 60)


def test_a_line_of_text_too_long_for_any_canvas_still_lands():
    box = TextBox(10, 10, Gdk.RGBA(0, 0, 0, 1), "Sans 200", TextStyle())
    box.insert("W" * 300)
    surface, x, y = box.landing()
    assert x + surface.get_width() <= 8192
