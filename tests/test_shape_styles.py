# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""How shapes are drawn: dashed or dotted outlines, arrowheads, and crisp edges."""

from gi.repository import Gdk, GLib

from tempera.canvas import Canvas
from tempera.color import ColorState, rgba
from tempera.document import Document, new_surface
from tempera.tools import ToolContext
from tempera.tools.arrow import ArrowTool
from tempera.tools.curve import CurveTool
from tempera.tools.ellipse import EllipseTool
from tempera.tools.line import LineTool
from tempera.tools.polygon import PolygonTool
from tempera.tools.rectangle import RectangleTool
from tempera.window import TemperaWindow

from pixels import pixel_at

CLEAR = (0.0, 0.0, 0.0, 0.0)


def context(surface, size=4, **style) -> ToolContext:
    return ToolContext(
        surface=surface,
        primary=rgba("#000000"),
        secondary=rgba("#ff0000"),
        button=Gdk.BUTTON_PRIMARY,
        size=size,
        fill_shapes=False,
        pick_color=lambda color, button: None,
        begin_text=lambda *args: None,
        select_region=lambda *args: None,
        **style,
    )


def draw(tool, surface, start, end, **style):
    ctx = context(surface, **style)
    tool.press(ctx, *start)
    tool.motion(ctx, *end)
    tool.release(ctx, *end)
    tool.finish(ctx)


def inked(surface, y, x_range):
    return [pixel_at(surface, x, y)[3] > 128 for x in x_range]


def runs(flags):
    """The lengths of the runs of ink and of gaps, in order."""
    lengths, current, count = [], None, 0
    for flag in flags:
        if flag == current:
            count += 1
        else:
            if current is not None:
                lengths.append((current, count))
            current, count = flag, 1
    lengths.append((current, count))
    return lengths


def test_a_solid_line_has_no_gaps():
    surface = new_surface(120, 20, CLEAR)
    draw(LineTool(), surface, (10, 10), (110, 10))
    assert all(inked(surface, 10, range(10, 110)))


def test_dashes_are_three_widths_long_with_gaps_of_two():
    surface = new_surface(120, 20, CLEAR)
    draw(LineTool(), surface, (10, 10), (110, 10), line_style="dashed")
    inner = runs(inked(surface, 10, range(10, 110)))
    assert inner[0] == (True, 12)
    assert inner[1] == (False, 8)
    assert inner[2] == (True, 12)


def test_dots_are_one_width_across_two_apart():
    surface = new_surface(120, 20, CLEAR)
    draw(LineTool(), surface, (10, 10), (110, 10), size=6, line_style="dotted")
    inner = runs(inked(surface, 10, range(10, 110)))
    # Round dots every twelve pixels, each about six across.
    dots = [length for ink, length in inner if ink]
    assert len(dots) >= 8
    assert all(4 <= length <= 7 for length in dots[1:-1])


def test_crisp_edges_leave_no_pixel_half_covered():
    smooth = new_surface(60, 60, CLEAR)
    crisp = new_surface(60, 60, CLEAR)
    draw(EllipseTool(), smooth, (5, 5), (55, 45), size=3)
    draw(EllipseTool(), crisp, (5, 5), (55, 45), size=3, antialias=False)

    def partly_covered(surface):
        surface.flush()
        return sum(1 for alpha in surface.get_data()[3::4] if 0 < alpha < 255)

    assert partly_covered(smooth) > 0
    assert partly_covered(crisp) == 0


def test_a_dashed_rectangle_is_dashed_all_round():
    surface = new_surface(80, 80, CLEAR)
    draw(RectangleTool(), surface, (10, 10), (70, 70), line_style="dashed")
    top = runs(inked(surface, 10, range(12, 68)))
    assert any(not ink for ink, _length in top)


def test_an_arrow_can_have_a_head_at_both_ends():
    one = new_surface(120, 60, CLEAR)
    two = new_surface(120, 60, CLEAR)
    draw(ArrowTool(), one, (10, 30), (110, 30))
    draw(ArrowTool(), two, (10, 30), (110, 30), arrow_ends="both")
    # Seven pixels to the side of the shaft, 16 in from a tip: only a head,
    # which is 9.6 wide either side there, reaches that far.
    assert pixel_at(one, 26, 37)[3] == 0
    assert pixel_at(two, 26, 37)[3] > 0
    # Both have the head at the end.
    assert pixel_at(one, 94, 37)[3] > 0 and pixel_at(two, 94, 37)[3] > 0


def test_a_short_arrow_with_two_heads_is_all_heads():
    surface = new_surface(40, 40, CLEAR)
    draw(ArrowTool(), surface, (15, 20), (25, 20), arrow_ends="both")
    assert pixel_at(surface, 20, 20)[3] > 0


def test_a_dashed_arrow_keeps_solid_heads():
    surface = new_surface(160, 60, CLEAR)
    draw(ArrowTool(), surface, (10, 30), (150, 30), line_style="dashed")
    assert any(not ink for ink in inked(surface, 30, range(12, 100)))
    assert all(inked(surface, 30, range(135, 148)))


def test_curves_and_polygons_take_the_style_too():
    curve = CurveTool()
    surface = new_surface(160, 40, CLEAR)
    ctx = context(surface, line_style="dashed")
    curve.press(ctx, 10, 20)
    curve.release(ctx, 150, 20)
    curve.finish(ctx)
    assert any(not ink for ink in inked(surface, 20, range(12, 148)))

    polygon = PolygonTool()
    surface = new_surface(100, 100, CLEAR)
    ctx = context(surface, line_style="dotted")
    for point in ((10, 10), (90, 10), (90, 90)):
        polygon.press(ctx, *point)
        polygon.release(ctx, *point)
    polygon.finish(ctx)
    assert any(not ink for ink in inked(surface, 10, range(12, 88)))


# On the canvas and in the window


def test_a_shape_waiting_to_land_takes_a_new_style():
    canvas = Canvas(Document(new_surface(100, 100, (1.0, 1.0, 1.0, 1.0))), ColorState())
    canvas.select_tool("shapes")
    canvas.line_style = "dotted"
    canvas.arrow_ends = "both"
    canvas.smooth_shapes = False
    ctx = canvas._make_context(Gdk.BUTTON_PRIMARY)
    assert (ctx.line_style, ctx.arrow_ends, ctx.antialias) == ("dotted", "both", False)


def choose(window, action, value):
    window.lookup_action(action).change_state(GLib.Variant.new_string(value))


def test_the_options_set_how_shapes_are_drawn(window):
    choose(window, "line-style", "dashed")
    choose(window, "arrow-ends", "both")
    choose(window, "shape-edges", "crisp")
    canvas = window.canvas
    assert (canvas.line_style, canvas.arrow_ends, canvas.smooth_shapes) == ("dashed", "both", False)
    choose(window, "line-style", "wavy")
    assert canvas.line_style == "dashed"


def test_arrowhead_choices_show_only_for_the_arrow(window):
    choose(window, "shape", "rectangle")
    assert not window._arrow_ends_row.get_visible()
    choose(window, "shape", "arrow")
    assert window._arrow_ends_row.get_visible()


def test_the_style_of_shapes_is_remembered(window, application):
    choose(window, "line-style", "dotted")
    choose(window, "shape-edges", "crisp")
    window._save_preferences()
    other = TemperaWindow(application)
    try:
        assert other.canvas.line_style == "dotted"
        assert not other.canvas.smooth_shapes
    finally:
        other.destroy()
