# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from tempera.selection import Selection


def test_from_rect_clips_to_the_image_bounds():
    selection = Selection.from_rect(-5, -5, 10, 10, image_width=8, image_height=8)
    assert selection.rect == (0, 0, 5, 5)


def test_from_rect_clips_the_far_edge_too():
    selection = Selection.from_rect(6, 6, 10, 10, image_width=8, image_height=8)
    assert selection.rect == (6, 6, 2, 2)


def test_from_rect_returns_none_for_a_collapsed_rect():
    assert Selection.from_rect(2, 2, 0, 5, image_width=8, image_height=8) is None
    assert Selection.from_rect(2, 2, 5, 0, image_width=8, image_height=8) is None


def test_from_rect_returns_none_when_entirely_outside_the_image():
    assert Selection.from_rect(20, 20, 5, 5, image_width=8, image_height=8) is None


def test_contains_includes_the_edges():
    selection = Selection(1, 1, 2, 2)
    assert selection.contains(1, 1)
    assert selection.contains(3, 3)
    assert not selection.contains(0.5, 1)
    assert not selection.contains(1, 3.5)


def test_clamped_reclips_after_the_image_shrinks():
    selection = Selection(4, 4, 4, 4)
    assert selection.clamped(6, 6).rect == (4, 4, 2, 2)
    assert selection.clamped(2, 2) is None
