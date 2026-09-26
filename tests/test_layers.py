# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The picture as a stack of layers: what each operation does, and taking it back."""

import cairo
import pytest
from gi.repository import Gio

from tempera import document as document_module
from tempera.document import MAX_LAYERS, Document, new_surface, surface_bytes
from tempera.file_io import save_document

from pixels import paint_pixel, pixel_at

RED = (1.0, 0.0, 0.0, 1.0)
BLUE = (0.0, 0.0, 1.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)
CLEAR_PIXEL = (0, 0, 0, 0)
WHITE_PIXEL = (255, 255, 255, 255)
RED_PIXEL = (255, 0, 0, 255)
BLUE_PIXEL = (0, 0, 255, 255)


def paint(document, x, y, color):
    """A one-pixel edit to the current layer, as one step of the history."""
    document.begin_change()
    paint_pixel(document.surface, x, y, color)
    document.finish_change()


def names(document):
    return [layer.name for layer in document.layers]


@pytest.fixture
def document():
    return Document(new_surface(10, 10, WHITE))


def test_a_new_picture_is_one_background_layer(document):
    assert names(document) == ["Background"]
    assert document.current == 0
    assert document.surface is document.layers[0].surface


def test_a_new_layer_is_empty_and_goes_above_the_current_one(document):
    assert document.add_layer()
    assert names(document) == ["Background", "Layer 2"]
    assert document.current == 1
    assert pixel_at(document.surface, 3, 3) == CLEAR_PIXEL
    assert document.modified

    document.undo()
    assert names(document) == ["Background"]
    assert document.current == 0
    assert not document.modified
    document.redo()
    assert names(document) == ["Background", "Layer 2"]


def test_new_layer_names_do_not_repeat(document):
    document.add_layer()
    document.rename_layer(1, "Layer 3")
    document.add_layer()
    assert names(document) == ["Background", "Layer 3", "Layer 4"]


def test_the_tools_paint_on_the_current_layer_only(document):
    document.add_layer()
    paint(document, 2, 2, RED)
    assert pixel_at(document.layers[1].surface, 2, 2) == RED_PIXEL
    assert pixel_at(document.layers[0].surface, 2, 2) == WHITE_PIXEL


def test_undo_puts_back_the_layer_that_was_painted_whichever_is_current(document):
    document.add_layer()
    paint(document, 2, 2, RED)
    document.select_layer(0)
    document.undo()
    assert pixel_at(document.layers[1].surface, 2, 2) == CLEAR_PIXEL
    assert pixel_at(document.layers[0].surface, 2, 2) == WHITE_PIXEL


def test_choosing_a_layer_is_not_a_change(document):
    document.add_layer()
    document.modified = False
    seen = []
    document.connect("layers-changed", lambda *_args: seen.append(True))
    depth = len(document._undo)
    document.select_layer(0)
    assert document.current == 0 and seen
    assert len(document._undo) == depth
    assert not document.modified


def test_the_picture_shows_the_visible_layers_at_their_opacity(document):
    document.add_layer()
    paint(document, 2, 2, RED)
    assert pixel_at(document.flattened(), 2, 2) == RED_PIXEL

    document.set_layer_opacity(1, 0.5)
    red, green, blue, alpha = pixel_at(document.flattened(), 2, 2)
    assert alpha == 255 and red == 255 and 120 <= green <= 135 and 120 <= blue <= 135

    document.set_layer_visible(1, False)
    assert pixel_at(document.flattened(), 2, 2) == WHITE_PIXEL
    # Only a rectangle of it, too.
    document.set_layer_visible(1, True)
    document.set_layer_opacity(1, 1.0)
    corner = document.flattened(2, 2, 3, 3)
    assert (corner.get_width(), corner.get_height()) == (3, 3)
    assert pixel_at(corner, 0, 0) == RED_PIXEL


def test_the_settings_of_a_layer_are_steps_of_the_history(document):
    document.add_layer()
    document.rename_layer(1, "Ink")
    document.set_layer_visible(1, False)
    document.undo()
    assert document.layers[1].visible
    document.undo()
    assert document.layers[1].name == "Layer 2"
    # Setting what is already set changes nothing.
    depth = len(document._undo)
    assert not document.rename_layer(1, "Layer 2")
    assert len(document._undo) == depth


def test_dragging_the_opacity_is_one_step(document):
    document.add_layer()
    for value in (0.9, 0.7, 0.5, 0.3):
        document.set_layer_opacity(1, value)
    assert document.layers[1].opacity == 0.3
    document.undo()
    assert document.layers[1].opacity == 1.0
    assert names(document) == ["Background", "Layer 2"]


def test_an_opacity_change_after_something_else_is_a_step_of_its_own(document):
    document.add_layer()
    document.set_layer_opacity(1, 0.5)
    paint(document, 1, 1, RED)
    document.set_layer_opacity(1, 0.25)
    document.undo()
    assert document.layers[1].opacity == 0.5


def test_an_opacity_change_after_saving_is_a_step_of_its_own(document):
    # Otherwise it would be folded into the step that was saved, and the
    # picture would look saved when it is not.
    document.add_layer()
    document.set_layer_opacity(1, 0.5)
    document.modified = False
    document.set_layer_opacity(1, 0.25)
    assert document.modified
    document.undo()
    assert not document.modified
    assert document.layers[1].opacity == 0.5


def test_the_last_layer_cannot_be_deleted(document):
    assert not document.delete_layer()
    assert names(document) == ["Background"]


def test_deleting_a_layer_can_be_undone_with_its_pixels(document):
    document.add_layer()
    paint(document, 2, 2, RED)
    assert document.delete_layer()
    assert names(document) == ["Background"]
    assert document.current == 0
    assert pixel_at(document.flattened(), 2, 2) == WHITE_PIXEL

    document.undo()
    assert names(document) == ["Background", "Layer 2"]
    assert document.current == 1
    assert pixel_at(document.surface, 2, 2) == RED_PIXEL


def test_duplicating_a_layer_copies_its_pixels(document):
    document.add_layer()
    paint(document, 2, 2, RED)
    document.set_layer_opacity(1, 0.5)
    assert document.duplicate_layer()
    assert names(document) == ["Background", "Layer 2", "Layer 2 copy"]
    assert document.current == 2
    assert document.layers[2].opacity == 0.5
    assert document.layers[2].surface is not document.layers[1].surface
    paint(document, 2, 2, BLUE)
    assert pixel_at(document.layers[1].surface, 2, 2) == RED_PIXEL


def test_moving_a_layer_keeps_the_current_one_current(document):
    document.add_layer()
    document.add_layer()
    ink = document.layers[1]
    document.select_layer(1)
    assert document.move_layer(1, 2)
    assert document.layers[2] is ink and document.current == 2
    assert document.move_layer(0, 1)
    assert document.layers[2] is ink and document.current == 2
    document.undo()
    document.undo()
    assert document.layers[1] is ink
    assert not document.move_layer(0, 5)


def test_merging_down_paints_the_layer_onto_the_one_beneath(document):
    document.add_layer()
    paint(document, 2, 2, RED)
    document.set_layer_opacity(1, 0.5)
    assert document.merge_down()
    assert names(document) == ["Background"]
    red, green, blue, alpha = pixel_at(document.surface, 2, 2)
    assert red == 255 and 120 <= green <= 135 and alpha == 255
    assert pixel_at(document.surface, 5, 5) == WHITE_PIXEL

    document.undo()
    assert names(document) == ["Background", "Layer 2"]
    assert pixel_at(document.layers[0].surface, 2, 2) == WHITE_PIXEL
    assert pixel_at(document.layers[1].surface, 2, 2) == RED_PIXEL
    assert not Document().merge_down()


def test_flattening_keeps_what_shows_and_drops_hidden_layers(document):
    document.add_layer()
    paint(document, 2, 2, RED)
    document.add_layer()
    paint(document, 3, 3, BLUE)
    document.set_layer_visible(2, False)
    assert document.flatten()
    assert len(document.layers) == 1
    assert pixel_at(document.surface, 2, 2) == RED_PIXEL
    assert pixel_at(document.surface, 3, 3) == WHITE_PIXEL
    document.undo()
    assert len(document.layers) == 3


def test_there_is_a_limit_to_the_layers(document, monkeypatch):
    monkeypatch.setattr(document_module, "MAX_LAYERS", 3)
    assert document.add_layer() and document.add_layer()
    assert not document.add_layer()
    assert not document.duplicate_layer()
    assert MAX_LAYERS >= 100


# Edits to the whole picture reach every layer


def test_growing_the_canvas_fills_the_bottom_with_white_and_the_rest_with_nothing(document):
    document.add_layer()
    document.resize(12, 12)
    assert pixel_at(document.layers[0].surface, 11, 11) == WHITE_PIXEL
    assert pixel_at(document.layers[1].surface, 11, 11) == CLEAR_PIXEL
    document.undo()
    assert all(layer.surface.get_width() == 10 for layer in document.layers)


@pytest.mark.parametrize(
    "edit, size",
    [
        (lambda document: document.rotate(True), (6, 10)),
        (lambda document: document.flip(True), (10, 6)),
        (lambda document: document.scale(20, 12), (20, 12)),
        (lambda document: document.crop_to(1, 1, 4, 3), (4, 3)),
    ],
)
def test_turning_scaling_and_cropping_reach_every_layer(edit, size):
    document = Document(new_surface(10, 6, WHITE))
    document.add_layer()
    paint(document, 1, 1, RED)
    edit(document)
    assert all(
        (layer.surface.get_width(), layer.surface.get_height()) == size for layer in document.layers
    )
    assert len(document.layers) == 2 and document.current == 1
    document.undo()
    assert all(layer.surface.get_width() == 10 for layer in document.layers)


def test_emptying_a_part_of_the_bottom_layer_leaves_white_and_of_another_nothing(document):
    document.add_layer()
    paint(document, 2, 2, RED)
    document.erase((0, 0, 5, 5))
    assert pixel_at(document.layers[1].surface, 2, 2) == CLEAR_PIXEL
    document.select_layer(0)
    paint(document, 2, 2, RED)
    document.erase((0, 0, 5, 5))
    assert pixel_at(document.layers[0].surface, 2, 2) == WHITE_PIXEL


def test_a_paste_that_grows_the_canvas_grows_every_layer_in_one_step(document):
    document.add_layer()
    document.select_layer(0)
    document.paste(new_surface(4, 4, RED), 8, 8)
    assert all(layer.surface.get_width() == 12 for layer in document.layers)
    assert pixel_at(document.layers[0].surface, 9, 9) == RED_PIXEL
    assert pixel_at(document.layers[1].surface, 11, 1) == CLEAR_PIXEL
    assert pixel_at(document.layers[0].surface, 11, 1) == WHITE_PIXEL
    document.undo()
    assert all(layer.surface.get_width() == 10 for layer in document.layers)
    assert pixel_at(document.layers[0].surface, 9, 9) == WHITE_PIXEL


def test_undo_and_redo_through_layers_and_pixels_come_back_the_same(document):
    document.add_layer()
    paint(document, 2, 2, RED)
    document.rotate(True)
    paint(document, 0, 0, BLUE)
    for _step in range(4):
        document.undo()
    assert names(document) == ["Background"]
    for _step in range(4):
        document.redo()
    assert pixel_at(document.layers[1].surface, 0, 0) == BLUE_PIXEL
    # A quarter turn clockwise takes (2, 2) of a 10 × 10 picture to (7, 2).
    assert pixel_at(document.layers[1].surface, 7, 2) == RED_PIXEL


# Memory


def test_changing_a_layer_s_settings_keeps_no_pixels_alive(document):
    document.add_layer()
    document.set_layer_visible(1, False)
    assert document._undo[-1].nbytes == 0


def test_a_deleted_layer_counts_against_the_history_s_memory(document):
    document.add_layer()
    size = surface_bytes(document.surface)
    document.delete_layer()
    assert document._undo[-1].nbytes == size


def test_a_turn_counts_every_layer_it_replaced(document):
    document.add_layer()
    document.rotate(True)
    assert document._undo[-1].nbytes == 2 * surface_bytes(document.surface)


def test_a_picture_with_layers_saves_as_it_shows(document, tmp_path):
    document.add_layer()
    paint(document, 2, 2, RED)
    path = tmp_path / "picture.png"
    save_document(document, Gio.File.new_for_path(str(path)))
    saved = cairo.ImageSurface.create_from_png(str(path))
    assert pixel_at(saved, 2, 2) == RED_PIXEL
    assert pixel_at(saved, 5, 5) == WHITE_PIXEL
