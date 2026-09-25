# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The shapes behind the Shapes tool, and the canvas placing them over several clicks."""

import pytest
from gi.repository import Gdk

from tempera import interface_size
from tempera.canvas import Canvas
from tempera.color import ColorState
from tempera.document import Document, new_surface
from tempera.tools.arrow import ArrowTool, head_length
from tempera.tools.base import ToolContext
from tempera.tools.curve import CurveTool
from tempera.tools.line import LineTool
from tempera.tools.polygon import PolygonTool
from tempera.tools.rectangle import RectangleTool
from tempera.tools.rounded_rectangle import RoundedRectangleTool
from tempera.tools.shapes import SHAPE_CLASSES, ShapesTool
from tempera.tools.star import StarTool, star_points
from tempera.tools.triangle import TriangleTool

from pixels import pixel_at

WHITE = (1.0, 1.0, 1.0, 1.0)
BLACK_PIXEL = (0, 0, 0, 255)
WHITE_PIXEL = (255, 255, 255, 255)
RED_PIXEL = (255, 0, 0, 255)


def rgba(spec: str) -> Gdk.RGBA:
    color = Gdk.RGBA()
    color.parse(spec)
    return color


def context(
    surface, size: int = 1, fill: bool = False, constrain: bool = False, outline: bool = True
) -> ToolContext:
    return ToolContext(
        surface=surface,
        primary=rgba("#000000"),
        secondary=rgba("#ff0000"),
        button=Gdk.BUTTON_PRIMARY,
        size=size,
        fill_shapes=fill,
        outline_shapes=outline,
        pick_color=lambda color, btn: None,
        begin_text=lambda x, y, color: None,
        select_region=lambda x, y, width, height: None,
        constrain=constrain,
    )


def drag(tool, ctx, start, end) -> None:
    tool.press(ctx, *start)
    tool.motion(ctx, *end)
    tool.release(ctx, *end)


def click(tool, ctx, point) -> None:
    drag(tool, ctx, point, point)


def draw(tool, ctx, start, end) -> None:
    """Drag a shape out and land it, which a shape now waits to be told to do."""
    drag(tool, ctx, start, end)
    tool.finish(ctx)


# The shape set


def test_every_shape_has_a_name_an_icon_and_its_own_id():
    ids = [shape.id for shape in SHAPE_CLASSES]
    assert len(ids) == len(set(ids)) == 9
    for shape in SHAPE_CLASSES:
        assert shape.label and shape.icon_name.startswith("tempera-")


def test_only_closed_shapes_can_be_filled():
    fillable = {shape.id for shape in SHAPE_CLASSES if shape.fillable}
    assert fillable == {"rectangle", "rounded-rectangle", "ellipse", "triangle", "star", "polygon"}


def test_the_shapes_tool_draws_with_the_shape_in_hand():
    tool = ShapesTool()
    tool.select("triangle")
    assert isinstance(tool.shape, TriangleTool)
    surface = new_surface(20, 20, WHITE)
    draw(tool, context(surface, fill=True), (0, 0), (20, 20))
    assert pixel_at(surface, 10, 15) == RED_PIXEL
    assert pixel_at(surface, 1, 1) == WHITE_PIXEL


# Shapes dragged out in one go


def test_a_filled_triangle_stands_on_its_base():
    surface = new_surface(40, 40, WHITE)
    draw(TriangleTool(), context(surface, fill=True), (0, 0), (40, 40))
    assert pixel_at(surface, 20, 35) == RED_PIXEL  # inside, near the base
    assert pixel_at(surface, 3, 5) == WHITE_PIXEL  # beside the apex


def test_a_shape_can_be_all_fill():
    surface = new_surface(40, 40, WHITE)
    draw(RectangleTool(), context(surface, size=4, fill=True, outline=False), (4, 4), (36, 36))
    assert pixel_at(surface, 20, 4) == RED_PIXEL  # the edge is the fill, not an outline
    assert pixel_at(surface, 20, 20) == RED_PIXEL
    assert pixel_at(surface, 2, 2) == WHITE_PIXEL


def test_a_shape_with_neither_outline_nor_fill_still_gets_its_outline():
    surface = new_surface(40, 40, WHITE)
    draw(RectangleTool(), context(surface, size=2, fill=False, outline=False), (4, 4), (36, 36))
    assert pixel_at(surface, 20, 4) == BLACK_PIXEL


def test_a_rounded_rectangle_leaves_its_corners_empty():
    surface = new_surface(40, 40, WHITE)
    draw(RoundedRectangleTool(), context(surface, size=2), (0, 0), (40, 40))
    assert pixel_at(surface, 0, 0) == WHITE_PIXEL
    assert pixel_at(surface, 20, 0) == BLACK_PIXEL  # the middle of the top edge


def test_star_points_alternate_between_the_tips_and_the_inner_corners():
    points = star_points(0, 0, 100, 100)
    assert len(points) == 10
    assert points[0] == pytest.approx((50, 0))  # the top tip
    distances = [((x - 50) ** 2 + (y - 50) ** 2) ** 0.5 for x, y in points]
    assert distances[0::2] == pytest.approx([50] * 5)
    assert all(inner < 25 for inner in distances[1::2])


def test_a_filled_star_is_filled_in_the_middle_and_not_between_its_points():
    surface = new_surface(40, 40, WHITE)
    draw(StarTool(), context(surface, fill=True), (0, 0), (40, 40))
    assert pixel_at(surface, 20, 20) == RED_PIXEL
    assert pixel_at(surface, 2, 2) == WHITE_PIXEL


def test_shift_squares_up_a_star():
    tool = StarTool()
    tool._start = (0, 0)
    assert tool._constrain((30, 10)) == (30, 30)


def test_an_arrow_has_a_head_wider_than_its_shaft():
    surface = new_surface(100, 40, WHITE)
    draw(ArrowTool(), context(surface, size=2), (5, 20), (95, 20))
    assert pixel_at(surface, 30, 20) == BLACK_PIXEL
    assert pixel_at(surface, 30, 24) == WHITE_PIXEL  # beside the thin shaft
    head_base = 95 - head_length(2) + 1
    assert pixel_at(surface, round(head_base), 24) == BLACK_PIXEL  # the head is wider
    assert pixel_at(surface, 92, 20) == BLACK_PIXEL  # up to the tip


def test_a_short_arrow_is_all_head():
    surface = new_surface(40, 40, WHITE)
    draw(ArrowTool(), context(surface, size=4), (10, 20), (16, 20))
    assert pixel_at(surface, 12, 20) == BLACK_PIXEL
    assert pixel_at(surface, 5, 20) == WHITE_PIXEL


def test_shift_snaps_an_arrow_like_a_line():
    tool = ArrowTool()
    tool._start = (0, 0)
    x, y = tool._constrain((10, 1))
    assert (round(x), round(y)) == (10, 0)


# The polygon


def test_a_polygon_closes_when_its_first_corner_is_clicked_again():
    surface = new_surface(40, 40, WHITE)
    tool, ctx = PolygonTool(), context(surface, fill=True)
    drag(tool, ctx, (5, 5), (35, 5))
    click(tool, ctx, (35, 35))
    assert not tool.adjustable
    assert pixel_at(surface, 30, 12) == WHITE_PIXEL  # nothing drawn yet

    click(tool, ctx, (6, 6))  # within reach of the first corner

    # Closed, and waiting with its corners adjustable until it is landed.
    assert tool.adjustable
    assert pixel_at(surface, 30, 12) == WHITE_PIXEL

    tool.finish(ctx)
    assert not tool.in_progress
    assert pixel_at(surface, 30, 12) == RED_PIXEL  # inside the triangle
    assert pixel_at(surface, 10, 30) == WHITE_PIXEL  # outside it


def test_clicking_the_last_corner_twice_closes_the_polygon():
    surface = new_surface(40, 40, WHITE)
    tool, ctx = PolygonTool(), context(surface, fill=True)
    click(tool, ctx, (5, 5))
    click(tool, ctx, (35, 5))
    click(tool, ctx, (35, 35))
    click(tool, ctx, (35, 35))
    assert tool.adjustable
    tool.finish(ctx)
    assert not tool.in_progress
    assert pixel_at(surface, 30, 12) == RED_PIXEL


def test_a_click_places_one_corner_and_the_next_click_the_second():
    tool, ctx = PolygonTool(), context(new_surface(40, 40, WHITE))
    click(tool, ctx, (5, 5))
    assert tool.points == [(5, 5)]
    click(tool, ctx, (20, 5))
    assert tool.points == [(5, 5), (20, 5)]


def test_shift_snaps_each_side_to_45_degrees():
    tool = PolygonTool()
    drag(tool, context(new_surface(40, 40, WHITE), constrain=True), (5, 5), (30, 7))
    (x, y) = tool.points[-1]
    assert round(y) == 5


def test_finishing_a_polygon_with_two_corners_draws_a_side():
    surface = new_surface(40, 40, WHITE)
    tool, ctx = PolygonTool(), context(surface, size=2)
    drag(tool, ctx, (5, 20), (35, 20))
    tool.finish(ctx)
    assert pixel_at(surface, 20, 20) == BLACK_PIXEL


def test_a_polygon_that_never_got_a_second_corner_draws_nothing():
    surface = new_surface(40, 40, WHITE)
    tool, ctx = PolygonTool(), context(surface, size=4)
    click(tool, ctx, (20, 20))
    tool.finish(ctx)
    assert pixel_at(surface, 20, 20) == WHITE_PIXEL


def test_a_cancelled_polygon_leaves_the_image_alone():
    surface = new_surface(40, 40, WHITE)
    tool, ctx = PolygonTool(), context(surface)
    drag(tool, ctx, (5, 5), (35, 5))
    tool.cancel()
    assert not tool.in_progress
    assert pixel_at(surface, 20, 5) == WHITE_PIXEL


# The curve


def test_a_curve_is_adjustable_after_its_second_bend():
    surface = new_surface(60, 60, WHITE)
    tool, ctx = CurveTool(), context(surface, size=2)
    drag(tool, ctx, (5, 30), (55, 30))
    assert not tool.adjustable
    drag(tool, ctx, (30, 5), (30, 5))
    assert not tool.adjustable
    drag(tool, ctx, (30, 5), (30, 5))
    assert tool.adjustable
    tool.finish(ctx)
    assert not tool.in_progress
    # Bent up, towards where the drags went, and no longer through the middle.
    assert pixel_at(surface, 30, 30) == WHITE_PIXEL
    assert BLACK_PIXEL in {pixel_at(surface, 30, y) for y in range(10, 25)}


def test_enter_after_one_bend_lands_the_curve_as_it_is():
    surface = new_surface(60, 60, WHITE)
    tool, ctx = CurveTool(), context(surface, size=2)
    drag(tool, ctx, (5, 30), (55, 30))
    drag(tool, ctx, (30, 55), (30, 55))
    tool.finish(ctx)
    assert not tool.in_progress
    assert BLACK_PIXEL in {pixel_at(surface, 30, y) for y in range(35, 50)}


def test_a_click_is_no_curve():
    tool = CurveTool()
    click(tool, context(new_surface(20, 20, WHITE)), (10, 10))
    assert not tool.in_progress


# Adjusting a shape before it lands


def test_a_shape_waits_to_be_adjusted_instead_of_landing():
    surface = new_surface(40, 40, WHITE)
    tool, ctx = RectangleTool(), context(surface, size=2)
    drag(tool, ctx, (5, 5), (25, 25))
    assert tool.adjustable
    assert pixel_at(surface, 5, 15) == WHITE_PIXEL  # nothing drawn yet
    assert set(tool.handles()) == {"nw", "n", "ne", "w", "e", "sw", "s", "se"}
    assert tool.handles()["se"] == (25, 25)
    assert tool.frame() == (5, 5, 20, 20)


def test_dragging_a_corner_grip_resizes_the_shape():
    surface = new_surface(40, 40, WHITE)
    tool, ctx = RectangleTool(), context(surface, size=2)
    drag(tool, ctx, (5, 5), (15, 15))
    tool.grab("se", 15, 15)
    tool.drag_to(35, 35)
    tool.finish(ctx)
    assert pixel_at(surface, 35, 20) == BLACK_PIXEL  # the right edge, where it was let go
    assert pixel_at(surface, 15, 20) == WHITE_PIXEL  # and not where it used to be


def test_an_edge_grip_changes_one_side_on_its_own():
    tool = RectangleTool()
    drag(tool, context(new_surface(40, 40, WHITE)), (5, 5), (15, 15))
    tool.grab("e", 15, 10)
    tool.drag_to(30, 40)
    assert tool.frame() == (5, 5, 25, 10)


def test_shift_on_a_grip_squares_the_shape_up():
    tool = RectangleTool()
    drag(tool, context(new_surface(40, 40, WHITE)), (5, 5), (15, 15))
    tool.grab("se", 15, 15)
    tool.drag_to(35, 20, constrain=True)
    assert tool.frame() == (5, 5, 30, 30)


def test_dragging_inside_moves_the_whole_shape():
    tool = RectangleTool()
    drag(tool, context(new_surface(40, 40, WHITE)), (5, 5), (15, 15))
    assert tool.contains(10, 10, 1)
    tool.grab(None, 10, 10)
    tool.drag_to(20, 25)
    assert tool.frame() == (15, 20, 10, 10)


def test_a_shape_can_be_nudged_a_pixel_at_a_time():
    tool = RectangleTool()
    drag(tool, context(new_surface(40, 40, WHITE)), (5, 5), (15, 15))
    tool.move_by(0, -3)
    assert tool.frame() == (5, 2, 10, 10)


def test_a_press_that_never_moves_places_no_shape():
    surface = new_surface(20, 20, WHITE)
    tool, ctx = RectangleTool(), context(surface, size=2)
    click(tool, ctx, (10, 10))
    assert not tool.in_progress
    tool.finish(ctx)
    assert pixel_at(surface, 10, 10) == WHITE_PIXEL


def test_a_line_is_adjusted_by_the_grips_on_its_ends():
    tool = LineTool()
    drag(tool, context(new_surface(40, 40, WHITE)), (5, 5), (35, 5))
    assert tool.handles() == {"start": (5, 5), "end": (35, 5)}
    assert tool.frame() is None  # no box to draw around a line
    tool.grab("end", 35, 5)
    tool.drag_to(35, 25)
    assert tool.handles() == {"start": (5, 5), "end": (35, 25)}


def test_shift_on_a_line_grip_snaps_it_to_45_degrees():
    tool = LineTool()
    drag(tool, context(new_surface(40, 40, WHITE)), (5, 5), (35, 5))
    tool.grab("end", 35, 5)
    tool.drag_to(25, 24, constrain=True)
    x, y = tool.handles()["end"]
    assert round(x - 5) == round(y - 5)  # on the diagonal from the end left alone


def test_a_closed_polygon_has_a_grip_on_every_corner():
    tool, ctx = PolygonTool(), context(new_surface(40, 40, WHITE))
    drag(tool, ctx, (5, 5), (35, 5))
    click(tool, ctx, (35, 35))
    click(tool, ctx, (6, 6))  # closes it
    assert list(tool.handles().values()) == tool.points
    assert tool.contains(25, 12, 1)  # the inside is what moves it

    tool.grab("corner-1", 35, 5)
    tool.drag_to(20, 2)
    assert tool.points[1] == (20, 2)


def test_a_curve_has_a_grip_on_each_end_and_each_bend():
    tool, ctx = CurveTool(), context(new_surface(60, 60, WHITE))
    drag(tool, ctx, (5, 30), (55, 30))
    drag(tool, ctx, (20, 5), (20, 5))
    drag(tool, ctx, (40, 55), (40, 55))
    assert set(tool.handles()) == {"start", "end", "bend1", "bend2"}
    tool.grab("bend1", 20, 5)
    tool.drag_to(20, 15)
    assert tool.handles()["bend1"] == (20, 15)


# The canvas, placing a shape over several clicks


class FakeGesture:
    def __init__(self, button=Gdk.BUTTON_PRIMARY, state=Gdk.ModifierType(0)):
        self.button = button
        self.state = state

    def get_current_button(self):
        return self.button

    def get_current_event_state(self):
        return self.state


def canvas_drag(canvas, start, end, button=Gdk.BUTTON_PRIMARY):
    gesture = FakeGesture(button)
    canvas._on_drag_begin(gesture, *start)
    offset = (end[0] - start[0], end[1] - start[1])
    canvas._on_drag_update(gesture, *offset)
    canvas._on_drag_end(gesture, *offset)


@pytest.fixture
def canvas():
    canvas = Canvas(Document(new_surface(60, 60, WHITE)), ColorState())
    canvas.select_tool("shapes")
    canvas.select_shape("polygon")
    return canvas


def test_a_polygon_placed_on_the_canvas_is_one_step_to_undo(canvas):
    document = canvas.document
    canvas_drag(canvas, (10, 10), (50, 10))
    canvas_drag(canvas, (50, 50), (50, 50))
    assert canvas.shape_in_progress
    assert not document.can_undo  # the clicks so far drew nothing

    assert canvas.finish_shape()
    assert pixel_at(document.surface, 50, 30) == BLACK_PIXEL

    document.undo()
    assert pixel_at(document.surface, 50, 30) == WHITE_PIXEL
    assert not document.can_undo


def test_the_colour_of_the_first_click_carries_through(canvas):
    canvas.colors.secondary = rgba("#ff0000")
    canvas_drag(canvas, (10, 10), (50, 10), button=Gdk.BUTTON_SECONDARY)
    # A later click with the other button still draws the same shape.
    canvas_drag(canvas, (50, 50), (50, 50))
    canvas.finish_shape()
    assert pixel_at(canvas.document.surface, 30, 10) == RED_PIXEL


def test_esc_drops_the_shape_and_enter_lands_it(canvas):
    canvas_drag(canvas, (10, 10), (50, 10))
    assert canvas._on_key_pressed(None, Gdk.KEY_Escape, 0, Gdk.ModifierType(0))
    assert not canvas.shape_in_progress
    assert pixel_at(canvas.document.surface, 30, 10) == WHITE_PIXEL

    canvas_drag(canvas, (10, 10), (50, 10))
    assert canvas._on_key_pressed(None, Gdk.KEY_Return, 0, Gdk.ModifierType(0))
    assert not canvas.shape_in_progress
    assert pixel_at(canvas.document.surface, 30, 10) == BLACK_PIXEL


def test_changing_tool_or_shape_lands_the_shape_being_placed(canvas):
    canvas_drag(canvas, (10, 10), (50, 10))
    canvas.select_shape("rectangle")
    assert pixel_at(canvas.document.surface, 30, 10) == BLACK_PIXEL

    canvas.select_shape("polygon")
    canvas_drag(canvas, (10, 30), (50, 30))
    canvas.select_tool("pencil")
    assert pixel_at(canvas.document.surface, 30, 30) == BLACK_PIXEL


def test_cancelling_what_floats_drops_a_shape_being_placed(canvas):
    canvas_drag(canvas, (10, 10), (50, 10))
    assert canvas.cancel_floating()
    assert not canvas.shape_in_progress


def test_a_shape_being_placed_takes_clicks_on_the_resize_grips(canvas):
    width, height = canvas.document.width, canvas.document.height
    assert canvas._handle_at(width, height) == "se"
    canvas_drag(canvas, (10, 10), (50, 10))
    assert canvas._handle_at(width, height) is None


def test_the_reach_for_closing_a_polygon_is_measured_on_screen(canvas):
    reach = canvas._make_context(Gdk.BUTTON_PRIMARY).reach
    canvas.set_zoom(2.0)
    assert canvas._make_context(Gdk.BUTTON_PRIMARY).reach == pytest.approx(reach / 2)
    interface_size.apply(200)
    try:
        assert canvas._make_context(Gdk.BUTTON_PRIMARY).reach == pytest.approx(reach)
    finally:
        interface_size.apply(interface_size.DEFAULT_SIZE)


def test_the_pointer_between_clicks_is_the_side_still_to_come(canvas):
    canvas_drag(canvas, (10, 10), (50, 10))
    canvas._on_motion(None, 50, 50)
    assert canvas.active_tool.shape._hover == (50, 50)


def test_a_shape_waits_on_the_canvas_until_it_is_landed(canvas):
    canvas.select_shape("rectangle")
    document = canvas.document
    canvas_drag(canvas, (10, 10), (40, 40))
    assert canvas.shape_in_progress
    assert not document.can_undo  # the drag drew nothing

    assert canvas.finish_shape()
    assert pixel_at(document.surface, 10, 25) == BLACK_PIXEL
    document.undo()
    assert pixel_at(document.surface, 10, 25) == WHITE_PIXEL


def test_dragging_a_grip_on_the_canvas_resizes_the_shape(canvas):
    canvas.select_shape("rectangle")
    canvas_drag(canvas, (10, 10), (30, 30))
    assert canvas._handle_at(30, 30) == "se"

    canvas_drag(canvas, (30, 30), (50, 50))
    canvas.finish_shape()
    assert pixel_at(canvas.document.surface, 50, 30) == BLACK_PIXEL  # the edge, dragged out
    assert pixel_at(canvas.document.surface, 30, 20) == WHITE_PIXEL  # inside, where it was


def test_clicking_away_from_a_shape_lands_it_and_draws_nothing(canvas):
    canvas.select_shape("rectangle")
    canvas_drag(canvas, (5, 5), (25, 25))
    canvas_drag(canvas, (55, 55), (55, 55))
    assert not canvas.shape_in_progress
    assert pixel_at(canvas.document.surface, 5, 15) == BLACK_PIXEL
    assert pixel_at(canvas.document.surface, 55, 55) == WHITE_PIXEL


def test_dragging_away_from_a_shape_lands_it_and_draws_the_next(canvas):
    canvas.select_shape("rectangle")
    canvas_drag(canvas, (5, 5), (25, 25))
    # Well clear of the grips around the first one, which a press would grab.
    canvas_drag(canvas, (45, 45), (57, 57))
    # The first one landed, and the second is the one now waiting.
    assert canvas.shape_in_progress
    assert pixel_at(canvas.document.surface, 5, 15) == BLACK_PIXEL
    assert pixel_at(canvas.document.surface, 45, 50) == WHITE_PIXEL

    canvas.finish_shape()
    assert pixel_at(canvas.document.surface, 45, 50) == BLACK_PIXEL
    canvas.document.undo()
    # Two shapes, two steps to undo.
    assert pixel_at(canvas.document.surface, 45, 50) == WHITE_PIXEL
    assert pixel_at(canvas.document.surface, 5, 15) == BLACK_PIXEL


def test_the_arrow_keys_nudge_a_shape_that_has_not_landed(canvas):
    canvas.select_shape("rectangle")
    canvas_drag(canvas, (10, 10), (30, 30))
    for _ in range(5):
        assert canvas._on_key_pressed(None, Gdk.KEY_Right, 0, Gdk.ModifierType(0))
    canvas.finish_shape()
    assert pixel_at(canvas.document.surface, 15, 20) == BLACK_PIXEL  # the left edge, five on
    assert pixel_at(canvas.document.surface, 10, 20) == WHITE_PIXEL


def test_a_colour_picked_while_a_shape_waits_lands_with_it(canvas):
    canvas.select_shape("rectangle")
    canvas_drag(canvas, (10, 10), (40, 40))
    canvas.colors.primary = rgba("#ff0000")
    canvas.finish_shape()
    assert pixel_at(canvas.document.surface, 10, 25) == RED_PIXEL
