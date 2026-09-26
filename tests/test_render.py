# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The canvas draws the image as tiles of texture, uploading again only what changed."""

import cairo
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


# Layers


RED_PIXEL = (255, 0, 0, 255)
BLUE_PIXEL = (0, 0, 255, 255)


def paint_rect(surface, x, y, width, height, color):
    cr = cairo.Context(surface)
    cr.set_source_rgba(*color)
    cr.rectangle(x, y, width, height)
    cr.fill()


@pytest.fixture
def layered():
    """A white background, and above it a layer with a red square at (10, 10)-(30, 30)."""
    colors = ColorState()
    colors.primary = rgba("#0000ff")
    document = Document(new_surface(60, 60, WHITE))
    document.add_layer()
    paint_rect(document.surface, 10, 10, 20, 20, (1.0, 0.0, 0.0, 1.0))
    return Canvas(document, colors)


def shown(canvas, x, y):
    return pixel_at(render_widget(canvas, 60, 60), x, y)


def test_the_layers_show_one_over_another(layered):
    assert shown(layered, 20, 20) == RED_PIXEL
    assert shown(layered, 40, 40) == WHITE_PIXEL


def test_a_hidden_layer_does_not_show(layered):
    layered.document.set_layer_visible(1, False)
    assert shown(layered, 20, 20) == WHITE_PIXEL


def test_a_see_through_layer_lets_the_one_beneath_show(layered):
    layered.document.set_layer_opacity(1, 0.5)
    red, green, blue, _alpha = shown(layered, 20, 20)
    assert red == 255 and 110 <= green <= 145 and 110 <= blue <= 145


def test_painting_goes_on_the_current_layer(layered):
    layered.document.select_layer(0)
    layered.select_tool("brush")
    layered.brush_size = 6
    gesture = FakeGesture()
    layered._on_drag_begin(gesture, 5, 20)
    layered._on_drag_update(gesture, 50, 0)
    layered._on_drag_end(gesture, 50, 0)
    # Under the red square, the stroke on the background is hidden.
    assert shown(layered, 20, 20) == RED_PIXEL
    assert shown(layered, 40, 20) == BLUE_PIXEL
    assert pixel_at(layered.document.layers[1].surface, 40, 20)[3] == 0


def test_a_selection_moved_on_an_upper_layer_leaves_the_one_beneath_showing(layered):
    layered.select_tool("select")
    layered.select_region(10, 10, 20, 20)
    gesture = FakeGesture()
    # Drag the red square 25 pixels right, by grabbing it in the middle.
    layered._on_drag_begin(gesture, 20, 20)
    layered._on_drag_update(gesture, 25, 0)
    layered._on_drag_end(gesture, 25, 0)
    # While it floats, where it was shows the background, not white paint.
    layered.document.layers[0].surface.flush()
    paint_rect(layered.document.layers[0].surface, 0, 0, 60, 60, (0.0, 0.0, 1.0, 1.0))
    layered._invalidate(None)
    assert shown(layered, 15, 20) == BLUE_PIXEL
    assert shown(layered, 45, 20) == RED_PIXEL

    layered.commit_paste()
    assert pixel_at(layered.document.layers[1].surface, 15, 20)[3] == 0
    assert shown(layered, 15, 20) == BLUE_PIXEL


def test_a_selection_moved_on_the_bottom_layer_leaves_white(layered):
    document = layered.document
    document.select_layer(0)
    paint_rect(document.surface, 36, 36, 20, 20, (0.0, 0.0, 1.0, 1.0))
    layered._invalidate(None)
    layered.select_tool("select")
    layered.select_region(36, 36, 20, 20)
    gesture = FakeGesture()
    # Grabbed in the middle, clear of its grips, and moved up.
    layered._on_drag_begin(gesture, 46, 46)
    layered._on_drag_update(gesture, 0, -30)
    assert shown(layered, 46, 50) == WHITE_PIXEL
    # The middle of where it floats now, clear of its grips.
    assert shown(layered, 46, 16) == BLUE_PIXEL
    layered._on_drag_end(gesture, 0, -30)
    layered.commit_paste()
    assert pixel_at(document.surface, 46, 50) == WHITE_PIXEL


def test_a_paste_shows_at_the_depth_of_the_layer_it_will_land_on(layered):
    # Pasted onto the background, under the red square: hidden there, as it
    # will be once it lands.
    layered.document.select_layer(0)
    layered.begin_paste(new_surface(50, 50, (0.0, 0.0, 1.0, 1.0)), 5, 5)
    assert shown(layered, 20, 20) == RED_PIXEL
    assert shown(layered, 40, 40) == BLUE_PIXEL
    layered.commit_paste()
    assert shown(layered, 20, 20) == RED_PIXEL


def test_the_picker_takes_the_colour_that_shows(layered):
    picked = []
    layered.connect("color-picked", lambda _canvas, color, _button: picked.append(color.copy()))
    layered.document.select_layer(0)
    layered.select_tool("picker")
    gesture = FakeGesture()
    layered._on_drag_begin(gesture, 20, 20)
    layered._on_drag_end(gesture, 0, 0)
    assert picked and picked[0].to_string() == "rgb(255,0,0)"


def test_undo_on_another_layer_than_the_current_one_shows(layered):
    document = layered.document
    layered.select_tool("pencil")
    gesture = FakeGesture()
    layered._on_drag_begin(gesture, 40, 40)
    layered._on_drag_update(gesture, 5, 0)
    layered._on_drag_end(gesture, 5, 0)
    assert shown(layered, 42, 40) == BLUE_PIXEL
    document.select_layer(0)
    document.undo()
    assert shown(layered, 42, 40) == WHITE_PIXEL


def test_a_deleted_layer_lets_go_of_its_textures(layered):
    render_widget(layered, 60, 60)
    upper = layered.document.layers[1]
    assert upper in layered._tiles
    layered.document.delete_layer()
    render_widget(layered, 60, 60)
    assert upper not in layered._tiles
    layered.document.undo()
    assert shown(layered, 20, 20) == RED_PIXEL


def test_changing_layer_lands_what_floats_on_the_layer_it_was_placed_on(layered):
    layered.begin_paste(new_surface(5, 5, (0.0, 0.0, 1.0, 1.0)), 40, 40)
    layered.select_layer(0)
    assert not layered.has_floating
    assert layered.document.current == 0
    assert pixel_at(layered.document.layers[1].surface, 42, 42) == BLUE_PIXEL
    assert pixel_at(layered.document.layers[0].surface, 42, 42) == WHITE_PIXEL
