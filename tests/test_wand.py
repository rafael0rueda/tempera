# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The magic wand: selecting the pixels of a colour joined to the one clicked."""

import pytest
from gi.repository import GLib

from tempera.canvas import Canvas, pointer
from tempera.color import ColorState
from tempera.document import Document, new_surface
from tempera.selection import Selection
from tempera.tools.wand import WandTool
from tempera.window import TemperaWindow

from driving import FakeGesture
from pixels import paint_pixel, pixel_at, render_widget

WHITE = (1.0, 1.0, 1.0, 1.0)
RED = (1.0, 0.0, 0.0, 1.0)
PINK = (1.0, 0.1, 0.1, 1.0)


def red_l(surface):
    """An L of red pixels at (2, 2), (3, 2) and (2, 3)."""
    for x, y in ((2, 2), (3, 2), (2, 3)):
        paint_pixel(surface, x, y, RED)


def test_the_wand_takes_the_pixels_joined_to_the_one_clicked():
    surface = new_surface(8, 8, WHITE)
    red_l(surface)
    paint_pixel(surface, 6, 6, RED)  # red, but not joined to the L
    selection = Selection.from_color(surface, 2, 2, 0)
    assert selection.rect == (2, 2, 2, 2)
    assert selection.contains(2.5, 3.5) and not selection.contains(3.5, 3.5)
    assert not selection.contains(6.5, 6.5)


def test_tolerance_widens_what_the_wand_takes():
    surface = new_surface(8, 8, WHITE)
    red_l(surface)
    paint_pixel(surface, 3, 3, PINK)
    assert Selection.from_color(surface, 2, 2, 0).rect == (2, 2, 2, 2)
    assert not Selection.from_color(surface, 2, 2, 0).contains(3.5, 3.5)
    assert Selection.from_color(surface, 2, 2, 40).contains(3.5, 3.5)


def test_a_whole_rectangle_needs_no_mask():
    selection = Selection.from_color(new_surface(5, 4, WHITE), 1, 1, 0)
    assert selection.rect == (0, 0, 5, 4) and selection.mask is None


def test_off_the_image_takes_nothing():
    assert Selection.from_color(new_surface(5, 4, WHITE), 7, 1, 0) is None


def test_the_ants_follow_the_edges_of_the_pixels():
    surface = new_surface(8, 8, WHITE)
    red_l(surface)
    edges = Selection.from_color(surface, 2, 2, 0).edges
    assert sorted(edges) == [
        (2, 2, 2, 4), (2, 2, 4, 2), (2, 4, 3, 4), (3, 3, 3, 4), (3, 3, 4, 3), (4, 2, 4, 3),
    ]
    # Each border line is walked once, however long.
    ring = new_surface(10, 10, RED)
    for x in range(3, 7):
        for y in range(3, 7):
            paint_pixel(ring, x, y, WHITE)
    around = Selection.from_color(ring, 0, 0, 0)
    assert len(around.edges) == 8


# On the canvas


@pytest.fixture
def canvas(monkeypatch):
    # The search runs as soon as it is asked for, rather than on a thread.
    monkeypatch.setattr(pointer, "run_in_background", lambda work, done: done(work()))
    # A red square at (20, 20)-(40, 40), well clear of the grips at the
    # image's edges, and with a middle clear of its own.
    surface = new_surface(60, 60, WHITE)
    for x in range(20, 40):
        for y in range(20, 40):
            paint_pixel(surface, x, y, RED)
    canvas = Canvas(Document(surface), ColorState())
    canvas.select_tool("wand")
    return canvas


def click(canvas, x, y):
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, x, y)
    canvas._on_drag_end(gesture, 0, 0)


def test_a_click_with_the_wand_selects(canvas):
    click(canvas, 30, 30)
    assert canvas.selection_size == (20, 20)
    click(canvas, 55, 5)  # outside it, on the white around, out of reach of its grips
    assert canvas._selection.rect == (0, 0, 60, 60)
    assert canvas._selection.mask is not None


def test_the_wand_looks_at_the_current_layer(canvas):
    canvas.document.add_layer()
    click(canvas, 30, 30)
    # The new layer is empty all over.
    assert canvas._selection.rect == (0, 0, 60, 60)
    assert canvas._selection.mask is None


def test_what_the_wand_picked_moves_and_deletes_like_any_selection(canvas):
    click(canvas, 50, 50)
    canvas.delete_selection()
    surface = canvas.document.surface
    assert pixel_at(surface, 30, 30) == (255, 0, 0, 255)
    # The background was emptied, to white, which it already was.
    click(canvas, 30, 30)
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 30, 30)
    canvas._on_drag_update(gesture, 15, 0)
    canvas._on_drag_end(gesture, 15, 0)
    canvas.commit_paste()
    assert pixel_at(surface, 25, 30) == (255, 255, 255, 255)
    assert pixel_at(surface, 50, 30) == (255, 0, 0, 255)


def test_the_ants_are_drawn_along_the_pixels_edges(canvas):
    before = render_widget(canvas, 60, 60)
    click(canvas, 50, 50)
    after = render_widget(canvas, 60, 60)
    # The white around the red square is selected: ants run along its edge,
    # and not through the middle of either.
    assert pixel_at(after, 20, 25) != pixel_at(before, 20, 25)
    assert pixel_at(after, 30, 30) == pixel_at(before, 30, 30)
    assert pixel_at(after, 45, 45) == pixel_at(before, 45, 45)


# In the window


def use(window, tool):
    window.lookup_action("tool").change_state(GLib.Variant.new_string(tool))


def test_one_sidebar_button_serves_both_selection_shapes(window):
    button = window._selection_button
    use(window, "lasso")
    assert button.get_action_target_value().get_string() == "lasso"
    assert "Free Select" in button.get_tooltip_text()
    use(window, "pencil")
    # It keeps the shape last used, to take up again.
    assert button.get_action_target_value().get_string() == "lasso"
    use(window, "select")
    assert button.get_action_target_value().get_string() == "select"


def test_the_selection_tools_show_their_options(window):
    use(window, "select")
    assert window._tool_options.get_visible_child_name() == "select"
    use(window, "lasso")
    assert window._tool_options.get_visible_child_name() == "select"
    use(window, "wand")
    assert window._tool_options.get_visible_child_name() == "wand"


def test_the_wand_s_tolerance_is_its_own_and_remembered(window, application):
    window._wand_tolerance_scale.set_value(70)
    assert window.canvas.wand_tolerance == 70
    assert window.canvas.fill_tolerance != 70
    window._save_preferences()
    other = TemperaWindow(application)
    try:
        assert other.canvas.wand_tolerance == 70
    finally:
        other.destroy()


def test_the_wand_has_a_key():
    from tempera import shortcuts

    assert shortcuts.keys_for("win.tool::wand") == ["m"]


# Only the edges in view are drawn: a pick on a photo can have a million


def speckled_pick():
    import random

    rng = random.Random(5)
    surface = new_surface(300, 400, WHITE)
    for _each in range(900):
        paint_pixel(surface, rng.randrange(300), rng.randrange(400), (0.0, 0.0, 0.0, 1.0))
    return Selection.from_color(surface, 0, 0, 0)


def covered(edges):
    """Every unit step of some edges, so that cutting one in two changes nothing."""
    steps = set()
    for x1, y1, x2, y2 in edges:
        if y1 == y2:
            steps.update(("across", x, y1) for x in range(x1, x2))
        else:
            steps.update(("down", x1, y) for y in range(y1, y2))
    return steps


def test_the_edges_in_view_are_all_of_those_that_reach_into_it():
    selection = speckled_pick()
    assert len(selection.edges) > 1000
    for view in ((0, 0, 300, 400), (40, 130, 90, 260), (250, 0, 300, 10), (0, 399, 300, 400)):
        left, top, right, bottom = view
        expected = {
            step for step in covered(selection.edges)
            if left <= step[1] <= right and top <= step[2] <= bottom
        }
        found = covered(selection.edges_within(*view))
        # Nothing in view is missed, and little outside it is drawn.
        assert expected <= found
        assert len(found) <= len(covered(selection.edges))
    whole = selection.edges_within(0, 0, 300, 400)
    assert covered(whole) == covered(selection.edges)
    assert len(selection.edges_within(40, 130, 90, 260)) < len(whole) / 4


def test_a_view_off_the_selection_draws_nothing():
    selection = Selection(10, 10, 20, 20)
    assert selection.edges_within(100, 100, 200, 200) == []
    assert len(selection.edges_within(0, 0, 50, 50)) == 4


def test_the_wand_works_out_the_edges_before_it_hands_the_selection_over():
    tool = WandTool()
    surface = new_surface(40, 40, WHITE)
    paint_pixel(surface, 20, 20, (0.0, 0.0, 0.0, 1.0))

    class Context:
        tolerance = 0
        select_pixels = None

    Context.surface = surface
    tool.press(Context, 0, 0)
    # Already there, so the first frame that draws them does not stall working them out.
    assert "_edge_bands" in tool._found.__dict__
