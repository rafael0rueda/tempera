# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from dataclasses import replace

from gi.repository import Gdk

from tempera.canvas import CUT_OFF_MESSAGE, Canvas, FloatingPaste
from tempera.selection import Selection
from tempera.color import ColorState
from tempera.document import MAX_SIZE, Document, new_surface

from driving import FakeGesture
from pixels import paint_pixel, pixel_at

RED = (1.0, 0.0, 0.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)


def make_canvas(width=4, height=4) -> Canvas:
    return Canvas(Document(new_surface(width, height, WHITE)), ColorState())


# select_all


def test_select_all_selects_the_whole_document():
    canvas = make_canvas(5, 3)
    canvas.select_all()
    assert canvas._selection.rect == (0, 0, 5, 3)


def test_select_all_commits_a_floating_paste_first():
    canvas = make_canvas()
    canvas.begin_paste(new_surface(2, 2, RED), 0, 0)
    canvas.select_all()
    assert not canvas.has_floating
    assert pixel_at(canvas.document.surface, 0, 0) == (255, 0, 0, 255)


# _nudge_delta


def test_nudge_delta_for_each_arrow_key():
    canvas = make_canvas()
    none = Gdk.ModifierType(0)
    assert canvas._nudge_delta(Gdk.KEY_Left, none) == (-1, 0)
    assert canvas._nudge_delta(Gdk.KEY_Right, none) == (1, 0)
    assert canvas._nudge_delta(Gdk.KEY_Up, none) == (0, -1)
    assert canvas._nudge_delta(Gdk.KEY_Down, none) == (0, 1)


def test_nudge_delta_steps_further_with_shift():
    canvas = make_canvas()
    assert canvas._nudge_delta(Gdk.KEY_Right, Gdk.ModifierType.SHIFT_MASK) == (10, 0)


def test_nudge_delta_is_none_for_other_keys():
    canvas = make_canvas()
    assert canvas._nudge_delta(Gdk.KEY_a, Gdk.ModifierType(0)) is None


# Nudging through the key handler


def test_nudging_a_selection_lifts_it_and_moves_it():
    canvas = make_canvas()
    canvas.set_selection(Selection(1, 1, 2, 2))
    handled = canvas._on_key_pressed(None, Gdk.KEY_Right, 0, Gdk.ModifierType(0))
    assert handled
    assert not canvas.has_selection
    assert canvas._paste is not None
    assert (canvas._paste.x, canvas._paste.y) == (2, 1)


def test_nudging_a_floating_paste_moves_it_further_each_time():
    canvas = make_canvas()
    canvas.begin_paste(new_surface(2, 2, RED), 1, 1)
    canvas._on_key_pressed(None, Gdk.KEY_Down, 0, Gdk.ModifierType(0))
    assert (canvas._paste.x, canvas._paste.y) == (1, 2)
    canvas._on_key_pressed(None, Gdk.KEY_Down, 0, Gdk.ModifierType.SHIFT_MASK)
    assert (canvas._paste.x, canvas._paste.y) == (1, 12)


def test_nudge_never_moves_a_paste_past_the_top_left():
    canvas = make_canvas()
    canvas.begin_paste(new_surface(2, 2, RED), 0, 0)
    canvas._on_key_pressed(None, Gdk.KEY_Left, 0, Gdk.ModifierType(0))
    assert (canvas._paste.x, canvas._paste.y) == (0, 0)


# FloatingPaste.rendered()


def test_rendered_returns_the_same_surface_when_unscaled():
    paste = FloatingPaste(new_surface(2, 2, RED))
    assert paste.rendered() is paste.surface


def test_rendered_resamples_to_the_scaled_size():
    surface = new_surface(2, 2, WHITE)
    paint_pixel(surface, 0, 0, RED)
    paste = FloatingPaste(surface, scale_x=2.0, scale_y=2.0)
    rendered = paste.rendered()
    assert (rendered.get_width(), rendered.get_height()) == (4, 4)
    assert pixel_at(rendered, 0, 0) == (255, 0, 0, 255)
    assert pixel_at(rendered, 3, 3) == (255, 255, 255, 255)


# Stretching an upright paste by one of its grips


def _resized(handle, origin, x, y):
    """The box (x, y, width, height) of an upright paste after dragging one grip to a point."""
    paste = FloatingPaste(new_surface(origin[2], origin[3], RED), x=origin[0], y=origin[1])
    paste.resize_from(replace(paste), handle, (x, y))
    return paste.x, paste.y, *paste.box_size


def test_paste_resized_se_drags_the_bottom_right_corner():
    assert _resized("se", (2, 3, 10, 10), 8, 5) == (2, 3, 6, 2)


def test_paste_resized_nw_drags_the_top_left_corner():
    assert _resized("nw", (2, 3, 10, 10), 1, 1) == (1, 1, 11, 12)


def test_paste_resized_clamps_to_zero_at_the_top_left():
    assert _resized("nw", (2, 3, 10, 10), -5, -5) == (0.0, 0.0, 12.0, 13.0)


def test_paste_resized_e_only_changes_width():
    assert _resized("e", (2, 3, 10, 10), 20, 999) == (2, 3, 18, 10)


def test_paste_resized_never_collapses_to_zero_or_negative():
    x, y, width, height = _resized("se", (2, 3, 10, 10), -100, -100)
    assert width >= 1
    assert height >= 1


def test_paste_resized_stops_at_the_largest_canvas():
    x, y, width, height = _resized("se", (2, 3, 10, 10), 20000, 20000)
    assert (x, y) == (2, 3)
    assert (width, height) == (MAX_SIZE, MAX_SIZE)


# _handle_at picking the closest handle, not the first one in range


def test_handle_at_picks_the_closest_handle_on_a_small_selection():
    # All 8 handles of a 2x2 selection sit within HANDLE_GRAB of each other,
    # so this only works if the nearest one wins rather than nw (the first
    # one rect_handles happens to list).
    canvas = make_canvas(8, 8)
    canvas.select_tool("select")
    canvas.set_selection(Selection(1, 1, 2, 2))
    assert canvas._handle_at(3, 3) == "se"
    assert canvas._handle_at(1, 1) == "nw"
    assert canvas._handle_at(2, 1) == "n"


# Swapping the document


def test_a_new_document_drops_the_selection():
    canvas = make_canvas(8, 8)
    canvas.select_region(6, 6, 2, 2)
    canvas.document = Document(new_surface(2, 2, WHITE))
    assert not canvas.has_selection


def test_a_new_document_does_not_receive_the_old_floating_paste():
    canvas = make_canvas()
    canvas.begin_paste(new_surface(2, 2, RED), 0, 0)
    replacement = Document(new_surface(4, 4, WHITE))
    canvas.document = replacement
    assert not canvas.has_floating
    assert pixel_at(replacement.surface, 0, 0) == (255, 255, 255, 255)
    assert not replacement.can_undo


# messages and pending changes


def test_a_paste_cut_off_at_the_size_limit_says_so():
    canvas = make_canvas()
    messages = []
    canvas.connect("message", lambda _canvas, message: messages.append(message))

    canvas.begin_paste(new_surface(2, 2, RED), 0, 0)
    canvas.commit_paste()
    assert messages == []

    canvas.begin_paste(new_surface(20, 2, RED), MAX_SIZE - 10, 0)
    canvas.commit_paste()
    assert messages == [CUT_OFF_MESSAGE]


def test_pending_floating_counts_a_paste_and_typed_text_only():
    canvas = make_canvas()
    assert not canvas.has_pending_floating

    canvas.begin_text(0, 0, Gdk.RGBA())
    assert canvas.has_floating
    assert not canvas.has_pending_floating
    canvas._text.insert("hi")
    assert canvas.has_pending_floating
    canvas.cancel_text()

    canvas.begin_paste(new_surface(2, 2, RED), 0, 0)
    assert canvas.has_pending_floating


# What floats over the picture is the selection, as in Paint


def lifted(canvas=None):
    """A canvas with a red block at (4, 4)-(16, 16) picked up and moved 10 px right."""
    canvas = canvas or make_canvas(60, 50)
    document = canvas.document
    for x in range(4, 16):
        for y in range(4, 16):
            paint_pixel(document.surface, x, y, RED)
    document.modified = False
    canvas.select_tool("select")
    canvas.select_region(4, 4, 12, 12)
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 10, 10)
    canvas._on_drag_update(gesture, 10, 0)
    canvas._on_drag_end(gesture, 10, 0)
    assert canvas.has_floating_paste
    return canvas


def press(canvas, keyval):
    return canvas._on_key_pressed(None, keyval, 0, Gdk.ModifierType(0))


def test_what_floats_can_be_copied_without_putting_it_down():
    canvas = lifted()
    pixels = canvas.floating_pixels()
    assert (pixels.get_width(), pixels.get_height()) == (12, 12)
    assert pixel_at(pixels, 0, 0) == (255, 0, 0, 255)
    assert canvas.has_floating_paste


def test_delete_throws_away_what_floats_for_good():
    canvas = lifted()
    document = canvas.document
    assert press(canvas, Gdk.KEY_Delete)
    assert not canvas.has_floating_paste
    # Gone from where it was lifted, and not landed where it was carried to.
    assert pixel_at(document.surface, 5, 5) == (255, 255, 255, 255)
    assert pixel_at(document.surface, 20, 5) == (255, 255, 255, 255)
    document.undo()
    assert pixel_at(document.surface, 5, 5) == (255, 0, 0, 255)


def test_escape_still_puts_what_was_lifted_back():
    canvas = lifted()
    assert press(canvas, Gdk.KEY_Escape)
    assert pixel_at(canvas.document.surface, 5, 5) == (255, 0, 0, 255)
    assert not canvas.document.can_undo


def test_delete_on_something_pasted_just_drops_it():
    canvas = make_canvas(20, 20)
    canvas.begin_paste(new_surface(4, 4, RED), 2, 2)
    assert press(canvas, Gdk.KEY_BackSpace)
    assert not canvas.has_floating_paste and not canvas.document.can_undo


def test_landing_with_enter_keeps_it_selected_and_clicking_away_lets_go():
    canvas = lifted()
    assert press(canvas, Gdk.KEY_Return)
    assert canvas._selection.rect == (14, 4, 12, 12)
    assert pixel_at(canvas.document.surface, 20, 5) == (255, 0, 0, 255)

    canvas = lifted()
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 50, 40)
    canvas._on_drag_end(gesture, 0, 0)
    assert not canvas.has_floating_paste and canvas._selection is None


def test_cropping_to_what_floats_lands_it_and_crops_to_it():
    canvas = lifted()
    assert canvas.crop_to_selection()
    document = canvas.document
    assert (document.width, document.height) == (12, 12)
    assert pixel_at(document.surface, 1, 1) == (255, 0, 0, 255)


def test_text_put_in_at_the_caret_as_pasting_does():
    canvas = make_canvas(60, 40)
    assert not canvas.insert_text("nowhere to go")
    canvas.begin_text(5, 5, Gdk.RGBA(0, 0, 0, 1))
    canvas.insert_text("ac")
    canvas._text.caret = 1
    assert canvas.insert_text("b")
    assert canvas._text.text == "abc"
