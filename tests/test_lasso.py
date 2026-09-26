# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hand-drawn selections: the outline, and every edit following it rather than its box."""

import cairo
import pytest
from gi.repository import Gdk

from tempera.canvas import Canvas
from tempera.color import ColorState
from tempera.document import Document, new_surface
from tempera.selection import Selection

from pixels import paint_pixel, pixel_at, render_widget

RED = (1.0, 0.0, 0.0, 1.0)
WHITE_PIXEL = (255, 255, 255, 255)
RED_PIXEL = (255, 0, 0, 255)
CLEAR_PIXEL = (0, 0, 0, 0)

# A right triangle filling the lower left half of the square (10, 10)-(30, 30).
# Only pixels whose middle lies inside count, which leaves out the top row.
TRIANGLE = [(10, 10), (10, 30), (30, 30)]
TRIANGLE_BOX = (10, 11, 19, 19)
INSIDE = (12, 27)
OUTSIDE = (27, 12)  # inside the box around it, but above the slanted side


def local(point):
    """A point of the image, in the triangle's box."""
    return point[0] - TRIANGLE_BOX[0], point[1] - TRIANGLE_BOX[1]


def red_canvas(size=40) -> Canvas:
    return Canvas(Document(new_surface(size, size, RED)), ColorState())


# The outline


def test_an_outline_selects_its_box_and_what_is_inside_it():
    selection = Selection.from_outline(TRIANGLE, 40, 40)
    assert selection.rect == TRIANGLE_BOX
    assert selection.contains(*INSIDE)
    assert not selection.contains(*OUTSIDE)
    assert not selection.contains(5, 5)


def test_an_outline_is_clipped_to_the_image():
    selection = Selection.from_outline([(-10, -10), (20, -10), (-10, 20)], 40, 40)
    # Only the corner of the image inside the outline, not the box around it.
    assert selection.rect == (0, 0, 10, 10)
    assert selection.contains(1, 1)


@pytest.mark.parametrize(
    "outline",
    [
        [],
        [(5, 5)],
        [(5, 5), (20, 20)],  # a stroke with nothing inside
        [(50, 50), (60, 50), (60, 60)],  # off the image
    ],
)
def test_an_outline_around_nothing_is_no_selection(outline):
    assert Selection.from_outline(outline, 40, 40) is None


def test_both_loops_of_a_crossed_outline_are_inside():
    figure_eight = [(0, 0), (20, 20), (20, 0), (0, 20)]
    selection = Selection.from_outline(figure_eight, 40, 40)
    assert selection.contains(4, 10)
    assert selection.contains(16, 10)


def test_the_pixels_outside_the_outline_come_out_transparent():
    selection = Selection.from_outline(TRIANGLE, 40, 40)
    pixels = selection.pixels(new_surface(40, 40, RED))
    assert pixel_at(pixels, *local(INSIDE)) == RED_PIXEL
    assert pixel_at(pixels, *local(OUTSIDE)) == CLEAR_PIXEL


def test_a_selection_on_a_shrunken_image_keeps_its_outline_where_it_can():
    selection = Selection.from_outline(TRIANGLE, 40, 40)
    assert selection.clamped(40, 40) is selection

    smaller = selection.clamped(20, 40)
    assert smaller.rect == (10, 11, 10, 19)
    assert smaller.contains(*INSIDE)
    assert not smaller.contains(19, 11)

    # Only the empty corner of the box is left on an image cut down to it.
    assert Selection.from_outline([(10, 10), (10, 30), (30, 30)], 40, 40).clamped(40, 11) is None


def test_a_new_outline_counts_as_a_different_selection():
    first = Selection.from_outline(TRIANGLE, 40, 40)
    second = Selection.from_outline(TRIANGLE, 40, 40)
    assert first == first
    assert first != second
    assert Selection(1, 1, 2, 2) == Selection(1, 1, 2, 2)


# Drawing it on the canvas


class FakeGesture:
    def __init__(self, state=Gdk.ModifierType(0)):
        self.state = state

    def get_current_button(self):
        return Gdk.BUTTON_PRIMARY

    def get_current_event_state(self):
        return self.state


def lasso(canvas, outline):
    gesture = FakeGesture()
    start = outline[0]
    canvas._on_drag_begin(gesture, *start)
    for x, y in outline[1:]:
        canvas._on_drag_update(gesture, x - start[0], y - start[1])
    last = outline[-1]
    canvas._on_drag_end(gesture, last[0] - start[0], last[1] - start[1])


@pytest.fixture
def canvas():
    canvas = red_canvas()
    canvas.select_tool("lasso")
    return canvas


def test_dragging_the_lasso_selects_what_it_went_round(canvas):
    lasso(canvas, TRIANGLE)
    assert canvas.has_selection
    assert canvas.selection_size == TRIANGLE_BOX[2:]
    assert canvas._selection.mask is not None


def test_a_click_with_the_lasso_drops_the_selection(canvas):
    lasso(canvas, TRIANGLE)
    lasso(canvas, [(5, 5), (5, 5)])
    assert not canvas.has_selection


def test_the_lasso_can_grab_its_selection_but_only_inside_the_outline(canvas):
    lasso(canvas, TRIANGLE)
    assert canvas._selection_at(*INSIDE) is not None
    assert canvas._selection_at(*OUTSIDE) is None


# Editing what it picked out


def test_delete_clears_only_inside_the_outline(canvas):
    lasso(canvas, TRIANGLE)
    canvas.delete_selection()
    surface = canvas.document.surface
    assert pixel_at(surface, *INSIDE) == WHITE_PIXEL
    assert pixel_at(surface, *OUTSIDE) == RED_PIXEL

    canvas.document.undo()
    assert pixel_at(canvas.document.surface, *INSIDE) == RED_PIXEL


def test_copying_takes_only_the_inside(canvas):
    lasso(canvas, TRIANGLE)
    copied = canvas.selection_surface()
    assert (copied.get_width(), copied.get_height()) == TRIANGLE_BOX[2:]
    assert pixel_at(copied, *local(OUTSIDE)) == CLEAR_PIXEL


def test_cropping_to_an_outline_keeps_its_box_and_clears_the_rest(canvas):
    lasso(canvas, TRIANGLE)
    canvas.crop_to_selection()
    document = canvas.document
    assert (document.width, document.height) == TRIANGLE_BOX[2:]
    assert pixel_at(document.surface, *local(INSIDE)) == RED_PIXEL
    assert pixel_at(document.surface, *local(OUTSIDE)) == CLEAR_PIXEL

    document.undo()
    assert (document.width, document.height) == (40, 40)


def test_moving_it_carries_the_inside_and_leaves_the_rest():
    canvas = red_canvas(80)
    canvas.select_tool("lasso")
    document = canvas.document
    # A marker just outside the outline, which must neither move nor be erased.
    paint_pixel(document.surface, 60, 20, (0.0, 0.0, 1.0, 1.0))
    lasso(canvas, [(10, 10), (10, 70), (70, 70)])

    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 25, 50)  # inside, clear of the grips
    assert canvas._paste is not None and canvas._paste_resize_handle is None
    canvas._on_drag_update(gesture, 5, 0)
    canvas._on_drag_end(gesture, 5, 0)
    canvas.commit_paste()

    surface = document.surface
    assert pixel_at(surface, 11, 69) == WHITE_PIXEL  # vacated
    assert pixel_at(surface, 60, 20) == (0, 0, 255, 255)  # untouched
    assert pixel_at(surface, 16, 69) == RED_PIXEL  # landed

    document.undo()
    assert pixel_at(document.surface, 11, 69) == RED_PIXEL


def test_a_grip_reaches_further_from_outside_a_selection_than_from_inside():
    canvas = red_canvas(80)
    canvas.select_tool("select")
    canvas.set_selection(Selection(20, 20, 20, 20))
    assert canvas._handle_at(14, 14) == "nw"  # outside the corner, within reach
    assert canvas._handle_at(26, 26) is None  # inside, off the grip: moves it
    assert canvas._handle_at(22, 22) == "nw"  # on the grip as drawn


def test_the_hole_a_moving_outline_leaves_follows_it(canvas):
    lasso(canvas, TRIANGLE)
    canvas._lift_selection(copy=False)
    paste = canvas._paste
    assert paste.source == TRIANGLE_BOX
    assert paste.source_mask is not None
    # A copy (Ctrl+drag) leaves no hole at all.
    canvas.cancel_paste()
    lasso(canvas, TRIANGLE)
    canvas._lift_selection(copy=True)
    assert canvas._paste.source is None and canvas._paste.source_mask is None


def test_nudging_lifts_the_outline_not_the_box(canvas):
    lasso(canvas, TRIANGLE)
    canvas._on_key_pressed(None, Gdk.KEY_Right, 0, Gdk.ModifierType(0))
    canvas.commit_paste()
    surface = canvas.document.surface
    assert pixel_at(surface, 10, 29) == WHITE_PIXEL
    assert pixel_at(surface, *OUTSIDE) == RED_PIXEL


def test_the_outline_is_drawn_while_selected(canvas):
    lasso(canvas, TRIANGLE)
    surface = render_widget(canvas, 40, 40)
    # The marching ants run along the left edge of the triangle.
    assert pixel_at(surface, 10, 20) != RED_PIXEL


# The document, through a mask


def test_erasing_through_a_mask_keeps_what_is_outside_it():
    document = Document(new_surface(4, 4, RED))
    mask = cairo.ImageSurface(cairo.FORMAT_A8, 2, 2)
    cr = cairo.Context(mask)
    cr.rectangle(0, 0, 1, 1)
    cr.fill()
    document.erase((1, 1, 2, 2), mask=mask)
    assert pixel_at(document.surface, 1, 1) == WHITE_PIXEL
    assert pixel_at(document.surface, 2, 2) == RED_PIXEL


def test_the_lasso_has_a_shortcut():
    from tempera import shortcuts

    assert shortcuts.keys_for("win.tool::lasso") == ["<Shift>s"]
