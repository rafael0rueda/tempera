# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The recent colours are the ones painted with, counted when the paint lands."""

import pytest
from gi.repository import Gdk

from tempera.canvas import Canvas
from tempera.color import ColorState, rgba
from tempera.document import Document, new_surface

WHITE = (1.0, 1.0, 1.0, 1.0)


class FakeGesture:
    def get_current_button(self):
        return Gdk.BUTTON_PRIMARY

    def get_current_event_state(self):
        return Gdk.ModifierType(0)


def drag(canvas, start, end):
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, *start)
    canvas._on_drag_update(gesture, end[0] - start[0], end[1] - start[1])
    canvas._on_drag_end(gesture, end[0] - start[0], end[1] - start[1])


def recent(canvas):
    return [color.to_string() for color in canvas.colors.recent]


@pytest.fixture
def canvas():
    colors = ColorState()
    colors.primary = rgba("#c01c28")
    colors.secondary = rgba("#3584e4")
    return Canvas(Document(new_surface(60, 60, WHITE)), colors)


def test_a_brush_stroke_remembers_its_colour(canvas):
    canvas.select_tool("brush")
    drag(canvas, (5, 5), (30, 30))
    assert recent(canvas) == [rgba("#c01c28").to_string()]


def test_the_eraser_remembers_nothing(canvas):
    canvas.select_tool("eraser")
    drag(canvas, (5, 5), (30, 30))
    assert recent(canvas) == []


def test_a_shape_counts_once_it_lands_with_both_its_colours(canvas):
    canvas.select_tool("shapes")
    canvas.select_shape("rectangle")
    canvas.fill_shapes = True
    drag(canvas, (5, 5), (40, 40))
    assert recent(canvas) == []

    canvas.finish_shape()
    assert recent(canvas) == [rgba("#c01c28").to_string(), rgba("#3584e4").to_string()]


def test_a_filled_shape_without_an_outline_leaves_out_the_outline_colour(canvas):
    canvas.select_tool("shapes")
    canvas.select_shape("ellipse")
    canvas.fill_shapes = True
    canvas.outline_shapes = False
    drag(canvas, (5, 5), (40, 40))
    canvas.finish_shape()
    assert recent(canvas) == [rgba("#3584e4").to_string()]


def test_landed_text_remembers_its_colour(canvas):
    canvas.begin_text(5, 5, rgba("#26a269"))
    canvas._text.insert("Hi")
    canvas.commit_text()
    assert recent(canvas) == [rgba("#26a269").to_string()]
