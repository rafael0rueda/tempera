# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The canvas draws the image as tiles of texture, uploading again only what changed."""

import pytest
from gi.repository import Gdk, Gsk, Gtk

from tempera.canvas import Canvas, pointer
from tempera.canvas.tiles import TILE_SIZE
from tempera.color import ColorState, rgba
from tempera.document import Document, new_surface

from pixels import pixel_at, render_widget

WHITE = (1.0, 1.0, 1.0, 1.0)
WHITE_PIXEL = (255, 255, 255, 255)
BLACK_PIXEL = (0, 0, 0, 255)


class FakeGesture:
    def get_current_button(self):
        return Gdk.BUTTON_PRIMARY

    def get_current_event_state(self):
        return Gdk.ModifierType(0)


@pytest.fixture
def canvas():
    colors = ColorState()
    colors.primary = rgba("#000000")
    # Two tiles across, so there are tiles a change does not touch.
    return Canvas(Document(new_surface(TILE_SIZE + 100, 60, WHITE)), colors)


def screen_pixel(canvas, x, y):
    screen = render_widget(canvas, TILE_SIZE + 100, 60)
    return pixel_at(screen, x, y)


def texture_nodes(canvas):
    snapshot = Gtk.Snapshot()
    canvas.do_snapshot(snapshot)
    found = []

    def walk(node):
        kind = node.get_node_type()
        if kind == Gsk.RenderNodeType.TEXTURE_SCALE_NODE:
            found.append(node)
        elif kind == Gsk.RenderNodeType.CONTAINER_NODE:
            for index in range(node.get_n_children()):
                walk(node.get_child(index))
        elif kind == Gsk.RenderNodeType.REPEAT_NODE:
            return  # the checkerboard

    walk(snapshot.to_node())
    return found


def test_a_stroke_shows_while_it_is_still_being_drawn(canvas):
    assert screen_pixel(canvas, 30, 30) == WHITE_PIXEL
    canvas.select_tool("brush")
    canvas.brush_size = 8
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 10, 30)
    canvas._on_drag_update(gesture, 40, 0)

    # Nothing has landed yet, but what is painted so far is on screen.
    assert not canvas.document.can_undo
    assert screen_pixel(canvas, 30, 30) == BLACK_PIXEL
    canvas._on_drag_end(gesture, 40, 0)


def test_undo_shows_the_image_as_it_was(canvas):
    canvas.select_tool("brush")
    canvas.brush_size = 8
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 10, 30)
    canvas._on_drag_update(gesture, 40, 0)
    canvas._on_drag_end(gesture, 40, 0)
    assert screen_pixel(canvas, 30, 30) == BLACK_PIXEL

    canvas.document.undo()
    assert screen_pixel(canvas, 30, 30) == WHITE_PIXEL
    canvas.document.redo()
    assert screen_pixel(canvas, 30, 30) == BLACK_PIXEL


def test_a_fill_shows_once_it_is_done(canvas, monkeypatch):
    jobs = []
    monkeypatch.setattr(pointer, "run_in_background", lambda work, done: jobs.append((work, done)))
    assert screen_pixel(canvas, 30, 30) == WHITE_PIXEL
    canvas.select_tool("fill")
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 30, 30)
    canvas._on_drag_end(gesture, 0, 0)
    work, done = jobs.pop()
    done(work())

    assert screen_pixel(canvas, 30, 30) == BLACK_PIXEL
    assert screen_pixel(canvas, TILE_SIZE + 50, 30) == BLACK_PIXEL


def test_a_change_uploads_only_the_tiles_it_touched(canvas):
    before = texture_nodes(canvas)
    assert len(before) == 2
    canvas.select_tool("pencil")
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 10, 10)
    canvas._on_drag_update(gesture, 5, 5)
    canvas._on_drag_end(gesture, 5, 5)

    after = texture_nodes(canvas)
    # The left tile was painted on, the right one was not.
    assert after[0].get_texture() is not before[0].get_texture()
    assert after[1].get_texture() is before[1].get_texture()


def test_a_new_image_replaces_every_tile(canvas):
    before = texture_nodes(canvas)
    canvas.document = Document(new_surface(TILE_SIZE + 100, 60, WHITE))
    after = texture_nodes(canvas)
    assert not {id(node.get_texture()) for node in before} & {id(node.get_texture()) for node in after}


@pytest.mark.parametrize("zoom", [0.1, 0.37, 1.0, 2.37])
def test_tiles_meet_on_whole_pixels(zoom):
    # Tile edges falling between two pixels would each half cover them, and
    # leave a faint seam; so every edge is put on a pixel, shared with the next.
    canvas = Canvas(Document(new_surface(3 * TILE_SIZE - 7, 2 * TILE_SIZE - 5, WHITE)), ColorState())
    canvas.set_zoom(zoom)
    rects = [node.get_bounds() for node in texture_nodes(canvas)]
    assert len(rects) == 6
    columns, rows = set(), set()
    for rect in rects:
        for value in (rect.get_x(), rect.get_y(), rect.get_width(), rect.get_height()):
            assert value == round(value)
        columns.add((round(rect.get_x()), round(rect.get_x() + rect.get_width())))
        rows.add((round(rect.get_y()), round(rect.get_y() + rect.get_height())))
    for spans in (columns, rows):
        # Each tile starts where the one before it ends.
        starts = sorted(start for start, _end in spans)
        ends = sorted(end for _start, end in spans)
        assert starts[1:] == ends[:-1]


def test_nothing_is_drawn_over_the_image_when_nothing_is_there(canvas):
    # Previews and outlines are drawn with cairo, but only when there are any:
    # a plain image is just its textures and the grips.
    snapshot = Gtk.Snapshot()
    canvas.do_snapshot(snapshot)
    node = snapshot.to_node()
    kinds = {node.get_child(index).get_node_type() for index in range(node.get_n_children())}
    assert Gsk.RenderNodeType.CAIRO_NODE not in kinds
