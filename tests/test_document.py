# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import cairo

from tempera import document as document_module
from tempera.document import (
    MAX_SIZE,
    MAX_UNDO,
    changed_rect,
    Document,
    copy_surface,
    crop_surface,
    new_surface,
    same_pixels,
)

from pixels import paint_pixel, pixel_at

RED = (1.0, 0.0, 0.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)


# new_surface / crop_surface / copy_surface


def test_new_surface_fills_with_color():
    surface = new_surface(3, 3, RED)
    assert pixel_at(surface, 0, 0) == (255, 0, 0, 255)
    assert pixel_at(surface, 2, 2) == (255, 0, 0, 255)


def test_new_surface_defaults_to_opaque_white():
    surface = new_surface(2, 2)
    assert pixel_at(surface, 0, 0) == (255, 255, 255, 255)


def test_crop_surface_extracts_the_rectangle():
    source = new_surface(4, 4, WHITE)
    paint_pixel(source, 2, 1, RED)
    cropped = crop_surface(source, 1, 1, 2, 2)
    assert cropped.get_width() == 2
    assert cropped.get_height() == 2
    assert pixel_at(cropped, 1, 0) == (255, 0, 0, 255)
    assert pixel_at(cropped, 0, 0) == (255, 255, 255, 255)


def test_copy_surface_is_independent_of_the_source():
    source = new_surface(2, 2, WHITE)
    copy = copy_surface(source)
    paint_pixel(source, 0, 0, RED)
    assert pixel_at(copy, 0, 0) == (255, 255, 255, 255)


# Undo / redo


def test_undo_redo_round_trip():
    document = Document(new_surface(2, 2, WHITE))
    assert not document.can_undo
    assert not document.can_redo

    document.begin_change()
    paint_pixel(document.surface, 0, 0, RED)
    document.commit_change()

    assert document.can_undo
    assert not document.can_redo
    assert pixel_at(document.surface, 0, 0) == (255, 0, 0, 255)

    document.undo()
    assert pixel_at(document.surface, 0, 0) == (255, 255, 255, 255)
    assert not document.can_undo
    assert document.can_redo

    document.redo()
    assert pixel_at(document.surface, 0, 0) == (255, 0, 0, 255)
    assert document.can_undo
    assert not document.can_redo


def test_undo_with_nothing_to_undo_is_a_no_op():
    document = Document(new_surface(1, 1, WHITE))
    document.undo()
    assert pixel_at(document.surface, 0, 0) == (255, 255, 255, 255)


def test_commit_change_clears_the_redo_stack():
    document = Document(new_surface(1, 1, WHITE))
    document.begin_change()
    document.commit_change()
    document.undo()
    assert document.can_redo

    document.begin_change()
    document.commit_change()
    assert not document.can_redo


def test_undo_history_is_capped_at_max_undo():
    document = Document(new_surface(1, 1, WHITE))
    for _ in range(MAX_UNDO + 5):
        document.begin_change()
        document.commit_change()
    assert len(document._undo) == MAX_UNDO


def paint_all(document, color) -> None:
    document.begin_change()
    cr = cairo.Context(document.surface)
    cr.set_source_rgba(*color)
    cr.paint()
    document.commit_change()


def test_undo_history_is_capped_by_memory(monkeypatch):
    # A step that changes all of a 10 × 10 image is 400 bytes; allow room for three.
    monkeypatch.setattr(document_module, "UNDO_BUDGET", 1200)
    document = Document(new_surface(10, 10, WHITE))
    for shade in range(5):
        paint_all(document, (shade * 51 / 255, 0.0, 0.0, 1.0))

    assert len(document._undo) == 3
    # What is left are the newest steps: undoing all of them lands on the
    # image before the third edit, not on the original white.
    while document.can_undo:
        document.undo()
    assert pixel_at(document.surface, 0, 0) == (51, 0, 0, 255)


def test_undo_history_keeps_the_newest_step_even_over_budget(monkeypatch):
    monkeypatch.setattr(document_module, "UNDO_BUDGET", 1)
    document = Document(new_surface(10, 10, WHITE))
    for shade in range(3):
        paint_all(document, (shade / 3, 0.0, 0.0, 1.0))
    assert len(document._undo) == 1


def test_a_save_point_trimmed_for_memory_stays_modified(monkeypatch):
    monkeypatch.setattr(document_module, "UNDO_BUDGET", 400)
    document = Document(new_surface(10, 10, WHITE))
    paint_change(document)
    paint_change(document, WHITE)
    document.undo()
    assert document.modified


def paint_change(document, color=RED) -> None:
    document.begin_change()
    paint_pixel(document.surface, 0, 0, color)
    document.commit_change()


# Modified, measured against the saved image


def test_a_new_document_is_unmodified_until_changed():
    document = Document(new_surface(1, 1, WHITE))
    assert not document.modified
    paint_change(document)
    assert document.modified


def test_undoing_back_to_the_saved_image_clears_modified():
    document = Document(new_surface(1, 1, WHITE))
    paint_change(document)
    document.undo()
    assert not document.modified
    document.redo()
    assert document.modified


def test_the_save_point_moves_with_saving():
    document = Document(new_surface(1, 1, WHITE))
    paint_change(document)
    document.modified = False  # what saving does
    paint_change(document, WHITE)
    assert document.modified
    document.undo()
    assert not document.modified
    document.undo()
    assert document.modified


def test_a_saved_image_dropped_from_redo_stays_modified():
    document = Document(new_surface(1, 1, WHITE))
    paint_change(document)
    document.modified = False
    document.undo()
    # A different edit replaces the redo step that led back to the saved image.
    paint_change(document, (0.0, 0.0, 1.0, 1.0))
    document.undo()
    assert document.modified


def test_a_saved_image_trimmed_from_history_stays_modified():
    document = Document(new_surface(1, 1, WHITE))
    for _ in range(MAX_UNDO + 1):
        paint_change(document)
    while document.can_undo:
        document.undo()
    assert document.modified


def test_trimming_history_keeps_a_later_save_point_in_step():
    document = Document(new_surface(1, 1, WHITE))
    paint_change(document)
    document.modified = False
    for _ in range(MAX_UNDO):
        paint_change(document, WHITE)
    for _ in range(MAX_UNDO):
        document.undo()
    assert not document.modified


# finish_change


def test_finish_change_drops_an_edit_that_changed_no_pixels():
    document = Document(new_surface(2, 2, WHITE))
    paint_change(document)
    document.undo()
    changes = []
    document.connect("content-changed", lambda *_args: changes.append(True))

    document.begin_change()
    paint_pixel(document.surface, 1, 1, WHITE)  # white over white
    document.finish_change()

    assert not document.can_undo
    assert document.can_redo  # the earlier undo can still be redone
    assert not document.modified
    assert changes == []


def test_finish_change_keeps_an_edit_that_changed_pixels():
    document = Document(new_surface(2, 2, WHITE))
    document.begin_change()
    paint_pixel(document.surface, 1, 1, RED)
    document.finish_change()
    assert document.can_undo
    assert document.modified


def test_same_pixels():
    a = new_surface(3, 2, WHITE)
    assert same_pixels(a, copy_surface(a))
    assert not same_pixels(a, new_surface(2, 3, WHITE))
    b = copy_surface(a)
    paint_pixel(b, 2, 1, RED)
    assert not same_pixels(a, b)


# Resize


def test_resize_grow_keeps_existing_pixels_anchored_top_left():
    document = Document(new_surface(2, 2, RED))
    document.resize(4, 4)
    assert (document.width, document.height) == (4, 4)
    assert pixel_at(document.surface, 0, 0) == (255, 0, 0, 255)
    assert pixel_at(document.surface, 3, 3) == (255, 255, 255, 255)
    assert document.can_undo


def test_resize_crop_discards_pixels_outside_the_new_size():
    document = Document(new_surface(4, 4, RED))
    document.resize(1, 1)
    assert (document.width, document.height) == (1, 1)
    assert pixel_at(document.surface, 0, 0) == (255, 0, 0, 255)


def test_resize_to_the_same_size_is_a_no_op():
    document = Document(new_surface(2, 2, WHITE))
    document.resize(2, 2)
    assert not document.can_undo


# Erase


def test_erase_fills_the_rect_with_the_given_color():
    document = Document(new_surface(3, 3, RED))
    document.erase((1, 1, 1, 1))
    assert pixel_at(document.surface, 1, 1) == (255, 255, 255, 255)
    assert pixel_at(document.surface, 0, 0) == (255, 0, 0, 255)
    assert document.can_undo


# Paste


def test_paste_stamps_without_growing_when_it_fits():
    document = Document(new_surface(4, 4, WHITE))
    document.paste(new_surface(2, 2, RED), 0, 0)
    assert (document.width, document.height) == (4, 4)
    assert pixel_at(document.surface, 0, 0) == (255, 0, 0, 255)
    assert pixel_at(document.surface, 3, 3) == (255, 255, 255, 255)


def test_paste_grows_the_canvas_when_it_overhangs():
    document = Document(new_surface(2, 2, WHITE))
    document.paste(new_surface(2, 2, RED), 2, 2)
    assert (document.width, document.height) == (4, 4)
    assert pixel_at(document.surface, 2, 2) == (255, 0, 0, 255)
    # The room the growth added, outside the pasted rectangle, is left white.
    assert pixel_at(document.surface, 0, 2) == (255, 255, 255, 255)


def test_paste_says_whether_it_was_cut_off_at_the_size_limit():
    document = Document(new_surface(4, 4, WHITE))
    assert document.paste(new_surface(2, 2, RED), 1, 1) is False
    assert document.paste(new_surface(20, 2, RED), MAX_SIZE - 10, 0) is True
    assert document.width == MAX_SIZE


def test_paste_erases_the_source_rect_it_moved_from():
    document = Document(new_surface(4, 4, RED))
    document.paste(new_surface(1, 1, RED), 3, 3, erase=(0, 0, 1, 1))
    assert pixel_at(document.surface, 0, 0) == (255, 255, 255, 255)
    assert pixel_at(document.surface, 3, 3) == (255, 0, 0, 255)


def test_paste_growth_and_erase_undo_in_a_single_step():
    document = Document(new_surface(2, 2, RED))
    document.paste(new_surface(1, 1, RED), 3, 3, erase=(0, 0, 1, 1))
    assert (document.width, document.height) == (4, 4)

    document.undo()
    assert (document.width, document.height) == (2, 2)
    assert pixel_at(document.surface, 0, 0) == (255, 0, 0, 255)


# Rotate / flip


def _marked_document() -> Document:
    """A 2x3 canvas with a red pixel at (0, 0), the rest white — asymmetric on
    both axes, so a rotation or flip can only land the marker in one place."""
    surface = new_surface(2, 3, WHITE)
    paint_pixel(surface, 0, 0, RED)
    return Document(surface)


def test_rotate_clockwise_swaps_dimensions_and_turns_the_marker():
    document = _marked_document()
    document.rotate(True)
    assert (document.width, document.height) == (3, 2)
    assert pixel_at(document.surface, 2, 0) == (255, 0, 0, 255)
    assert document.can_undo


def test_rotate_counterclockwise_swaps_dimensions_and_turns_the_marker():
    document = _marked_document()
    document.rotate(False)
    assert (document.width, document.height) == (3, 2)
    assert pixel_at(document.surface, 0, 1) == (255, 0, 0, 255)


def test_flip_horizontal_mirrors_left_right():
    document = _marked_document()
    document.flip(True)
    assert (document.width, document.height) == (2, 3)
    assert pixel_at(document.surface, 1, 0) == (255, 0, 0, 255)


def test_flip_vertical_mirrors_top_bottom():
    document = _marked_document()
    document.flip(False)
    assert (document.width, document.height) == (2, 3)
    assert pixel_at(document.surface, 0, 2) == (255, 0, 0, 255)


# Crop


def test_crop_to_extracts_the_rectangle():
    document = Document(new_surface(4, 4, WHITE))
    paint_pixel(document.surface, 2, 1, RED)
    document.crop_to(1, 1, 2, 2)
    assert (document.width, document.height) == (2, 2)
    assert pixel_at(document.surface, 1, 0) == (255, 0, 0, 255)
    assert document.can_undo


def test_crop_to_undoes_back_to_the_original_size():
    document = Document(new_surface(4, 4, RED))
    document.crop_to(0, 0, 1, 1)
    document.undo()
    assert (document.width, document.height) == (4, 4)


# scale


def test_scale_resamples_the_whole_picture():
    document = Document(new_surface(4, 4, WHITE))
    paint_pixel(document.surface, 0, 0, RED)
    paint_pixel(document.surface, 1, 0, RED)
    paint_pixel(document.surface, 0, 1, RED)
    paint_pixel(document.surface, 1, 1, RED)

    document.scale(8, 8)

    assert (document.width, document.height) == (8, 8)
    # The red quarter is still a quarter, now twice the size.
    assert pixel_at(document.surface, 1, 1) == (255, 0, 0, 255)
    assert pixel_at(document.surface, 7, 7) == (255, 255, 255, 255)


def test_scale_shrinks_too():
    document = Document(new_surface(8, 8, WHITE))
    document.scale(2, 2)
    assert (document.width, document.height) == (2, 2)


def test_scale_can_be_undone():
    document = Document(new_surface(4, 2, WHITE))
    document.scale(40, 20)
    document.undo()
    assert (document.width, document.height) == (4, 2)


def test_scale_to_the_same_size_is_a_no_op():
    document = Document(new_surface(4, 4, WHITE))
    document.scale(4, 4)
    assert not document.can_undo


def test_scale_stays_within_what_a_canvas_can_hold():
    document = Document(new_surface(4, 4, WHITE))
    document.scale(MAX_SIZE * 2, 0)
    assert (document.width, document.height) == (MAX_SIZE, 1)


def test_scaling_up_does_not_fade_the_edges():
    """Sampling past the edge used to leave the right and bottom sides washed out."""
    document = Document(new_surface(2, 2, RED))
    document.scale(16, 16)
    for x, y in ((0, 0), (15, 0), (0, 15), (15, 15), (8, 15)):
        assert pixel_at(document.surface, x, y) == (255, 0, 0, 255)


# Undo steps keep only what changed


def brute_changed_rect(a, b):
    width, height = a.get_width(), a.get_height()
    points = [
        (x, y)
        for y in range(height)
        for x in range(width)
        if pixel_at(a, x, y) != pixel_at(b, x, y)
    ]
    if not points:
        return None
    xs, ys = [x for x, _y in points], [y for _x, y in points]
    return min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1


def test_changed_rect_finds_nothing_in_identical_images():
    a = new_surface(7, 5, WHITE)
    assert changed_rect(a, copy_surface(a)) is None


def test_changed_rect_matches_a_pixel_by_pixel_search():
    import random

    generator = random.Random(4)
    for _round in range(60):
        width, height = generator.randint(1, 23), generator.randint(1, 17)
        a = new_surface(width, height, WHITE)
        b = copy_surface(a)
        for _dot in range(generator.randint(1, 4)):
            paint_pixel(b, generator.randrange(width), generator.randrange(height), RED)
        assert changed_rect(a, b) == brute_changed_rect(a, b)


def test_a_stroke_keeps_only_the_rectangle_it_touched():
    document = Document(new_surface(400, 300, WHITE))
    document.begin_change()
    paint_pixel(document.surface, 10, 20, RED)
    paint_pixel(document.surface, 14, 22, RED)
    document.finish_change()
    patch = document._undo[-1]
    assert (patch.x, patch.y) == (10, 20)
    assert (patch.pixels.get_width(), patch.pixels.get_height()) == (5, 3)


def test_undo_and_redo_walk_through_mixed_edits():
    document = Document(new_surface(6, 4, WHITE))
    states = [copy_surface(document.surface)]

    paint_change(document)
    states.append(copy_surface(document.surface))
    document.resize(9, 3)
    states.append(copy_surface(document.surface))
    document.begin_change()
    paint_pixel(document.surface, 8, 2, (0.0, 0.0, 1.0, 1.0))
    document.finish_change()
    states.append(copy_surface(document.surface))
    document.rotate(clockwise=True)
    states.append(copy_surface(document.surface))

    for expected in reversed(states[:-1]):
        document.undo()
        assert same_pixels(document.surface, expected)
    assert not document.can_undo
    for expected in states[1:]:
        document.redo()
        assert same_pixels(document.surface, expected)
    assert not document.can_redo


def test_undo_waits_for_a_stroke_to_finish():
    document = Document(new_surface(3, 3, WHITE))
    paint_change(document)
    document.begin_change()
    paint_pixel(document.surface, 2, 2, RED)
    document.undo()
    assert pixel_at(document.surface, 0, 0) == (255, 0, 0, 255)
    document.finish_change()
    assert len(document._undo) == 2


# What changed, for the canvas to redraw


def paint_square(document, x, y, size):
    cr = cairo.Context(document.surface)
    cr.set_source_rgb(1, 0, 0)
    cr.rectangle(x, y, size, size)
    cr.fill()


def test_a_change_says_which_part_of_the_image_it_touched():
    document = Document(new_surface(40, 40))
    document.begin_change()
    paint_square(document, 5, 6, 3)
    document.finish_change()
    assert document.damage == (5, 6, 3, 3)


def test_undo_and_redo_say_which_part_they_put_back():
    document = Document(new_surface(40, 40))
    document.begin_change()
    paint_square(document, 5, 6, 3)
    document.finish_change()
    document.damage = None
    document.undo()
    assert document.damage == (5, 6, 3, 3)
    document.damage = None
    document.redo()
    assert document.damage == (5, 6, 3, 3)


def test_a_new_surface_may_have_changed_anywhere():
    document = Document(new_surface(40, 40))
    document.begin_change()
    paint_square(document, 5, 6, 3)
    document.finish_change()
    document.resize(50, 50)
    assert document.damage is None
    document.undo()
    assert document.damage is None


def test_a_change_that_altered_nothing_touched_nothing():
    document = Document(new_surface(40, 40))
    document.begin_change()
    document.commit_change()
    assert document.damage == (0, 0, 0, 0)
