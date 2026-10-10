# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The C helper gives the answers the Python does, which is what runs without it.

Skipped where the helper has not been built (build-aux/build_native.sh builds
it), unless TEMPERA_REQUIRE_NATIVE is set, as it is where the tests run for
every change: there, not finding it is a failure.
"""

import os
import random

import cairo
import pytest

from tempera import native, selection as selection_module
from gi.repository import Gdk

from tempera.document import copy_surface, new_surface
from tempera.selection import EDGE_TILE, Selection
from tempera.tools.fill import flood_fill

from pixels import paint_pixel

WHITE = (1.0, 1.0, 1.0, 1.0)


def rgba(red, green, blue, alpha=1.0):
    color = Gdk.RGBA()
    color.red, color.green, color.blue, color.alpha = red, green, blue, alpha
    return color


BUILT = native.available()

needs_helper = pytest.mark.skipif(
    not BUILT and not os.environ.get("TEMPERA_REQUIRE_NATIVE"),
    reason="the C helper is not built",
)


@pytest.fixture
def in_python():
    """Do without the helper from here to the end of the `with`."""

    class Without:
        def __enter__(self):
            self.library, native.library = native.library, None

        def __exit__(self, *_args):
            native.library = self.library

    return Without()


def speckled(rng, width, height):
    """A picture of a few near colours scattered about, for a search to thread through."""
    surface = new_surface(width, height, WHITE)
    shades = [(1.0, 1.0, 1.0, 1.0), (0.97, 0.97, 0.97, 1.0), (0.9, 0.9, 0.9, 1.0), (0.2, 0.3, 0.9, 1.0)]
    for y in range(height):
        for x in range(width):
            if rng.random() < 0.45:
                paint_pixel(surface, x, y, rng.choice(shades))
    surface.flush()
    return surface


def mask_rows(selection):
    if selection.mask is None:
        return None
    selection.mask.flush()
    data, stride = selection.mask.get_data(), selection.mask.get_stride()
    return [bytes(data[row * stride:row * stride + selection.width]) for row in range(selection.height)]


def covered(edges):
    """Every unit step of some edges, so that where they are cut changes nothing."""
    steps = set()
    for x1, y1, x2, y2 in edges:
        if y1 == y2:
            steps.update(("across", x, y1) for x in range(x1, x2))
        else:
            steps.update(("down", x1, y) for y in range(y1, y2))
    return steps


@needs_helper
def test_the_helper_is_there():
    assert BUILT


@needs_helper
def test_a_fill_paints_the_same_pixels_either_way(in_python):
    rng = random.Random(11)
    for _each in range(120):
        width, height = rng.randrange(1, 40), rng.randrange(1, 30)
        surface = speckled(rng, width, height)
        x, y = rng.randrange(width), rng.randrange(height)
        tolerance = rng.choice([0, 4, 10, 32, 255])
        color = rgba(rng.random(), rng.random(), rng.random())
        helped, plain = copy_surface(surface), copy_surface(surface)
        helped_rect = flood_fill(helped, x, y, color, tolerance)
        with in_python:
            plain_rect = flood_fill(plain, x, y, color, tolerance)
        assert bytes(helped.get_data()) == bytes(plain.get_data())
        assert (helped_rect is None) == (plain_rect is None)
        if helped_rect is not None:
            # Tighter, if anything: around the pixels changed, not the runs they were in.
            assert helped_rect[0] >= plain_rect[0] and helped_rect[1] >= plain_rect[1]
            assert helped_rect[0] + helped_rect[2] <= plain_rect[0] + plain_rect[2]
            assert helped_rect[1] + helped_rect[3] <= plain_rect[1] + plain_rect[3]


@needs_helper
def test_the_wand_picks_the_same_pixels_and_the_same_border_either_way(in_python):
    rng = random.Random(12)
    for _each in range(120):
        width, height = rng.randrange(1, 40), rng.randrange(1, 30)
        surface = speckled(rng, width, height)
        x, y = rng.randrange(width), rng.randrange(height)
        tolerance = rng.choice([0, 4, 10, 32, 255])
        helped = Selection.from_color(surface, x, y, tolerance)
        helped_edges = covered(helped.edges)
        with in_python:
            plain = Selection.from_color(surface, x, y, tolerance)
            plain_edges = covered(plain.edges)
        assert helped.rect == plain.rect
        assert mask_rows(helped) == mask_rows(plain)
        assert helped_edges == plain_edges


@needs_helper
def test_a_fill_off_the_picture_or_of_the_same_colour_does_nothing():
    surface = new_surface(5, 5, WHITE)
    assert flood_fill(surface, 9, 9, rgba(1, 0, 0)) is None
    assert flood_fill(surface, 2, 2, rgba(1, 1, 1), 0) is None
    assert flood_fill(surface, 2, 2, rgba(1, 1, 1), 32) is None
    assert flood_fill(surface, 2, 2, rgba(1, 0, 0)) == (0, 0, 5, 5)


@needs_helper
def test_a_speckled_border_is_traced_a_view_at_a_time_and_never_kept_whole(monkeypatch, in_python):
    monkeypatch.setattr(selection_module, "COARSE_ABOVE", 100)
    rng = random.Random(13)
    surface = new_surface(300, 400, WHITE)
    for _each in range(4000):
        paint_pixel(surface, rng.randrange(300), rng.randrange(400), (0.0, 0.0, 0.0, 1.0))
    surface.flush()
    selection = Selection.from_color(surface, 0, 0, 0)
    selection.prepare()
    assert "edges" not in selection.__dict__ and "_edge_bands" not in selection.__dict__

    with in_python:
        plain = Selection.from_color(surface, 0, 0, 0)
        everything = covered(plain.edges)
    for view in ((0, 0, 300, 400), (40, 130, 90, 260), (250, 0, 300, 10), (0, 399, 300, 400)):
        left, top, right, bottom = view
        found = covered(selection.edges_within(*view))
        expected = {step for step in everything if left <= step[1] <= right and top <= step[2] <= bottom}
        # Nothing in view is missed, nothing made up, and what is beyond the
        # bands the view reaches into is left alone.
        assert expected <= found <= everything
        reach = {
            step for step in everything
            if left - EDGE_TILE <= step[1] <= right + EDGE_TILE and top - EDGE_TILE <= step[2] <= bottom + EDGE_TILE
        }
        assert found <= reach
    assert "edges" not in selection.__dict__


@needs_helper
def test_a_view_scrolled_a_little_is_not_traced_again(monkeypatch):
    monkeypatch.setattr(selection_module, "COARSE_ABOVE", 0)
    surface = new_surface(1200, 1200, WHITE)
    paint_pixel(surface, 150, 150, (0.0, 0.0, 0.0, 1.0))
    paint_pixel(surface, 900, 900, (0.0, 0.0, 0.0, 1.0))
    selection = Selection.from_color(surface, 0, 0, 0)
    first = selection.edges_within(130, 130, 200, 200)
    assert selection.edges_within(135, 140, 205, 210) is first
    tile = selection._tiles[(1, 1)]
    # Scrolled on to where another tile shows too, the first is kept as it was.
    both = selection.edges_within(130, 130, 950, 950)
    assert both is not first and selection._tiles[(1, 1)] is tile
    assert len(selection._tiles) == 49

    # Every stretch of border comes once, however the tiles divide it.
    whole = selection.edges_within(0, 0, 1200, 1200)
    assert len(whole) == len(set(whole)) and sum(x2 - x1 + y2 - y1 for x1, y1, x2, y2 in whole) == 4 * 1200 + 8


@needs_helper
def test_lines_are_cut_at_the_same_places_wherever_the_view_is(monkeypatch):
    monkeypatch.setattr(selection_module, "COARSE_ABOVE", 0)
    # A long straight border: the dashes along it must not shift as it scrolls.
    surface = new_surface(600, 40, WHITE)
    cr = cairo.Context(surface)
    cr.set_source_rgb(0, 0, 0)
    cr.rectangle(0, 20, 600, 20)
    cr.fill()
    paint_pixel(surface, 5, 5, (0.0, 0.0, 0.0, 1.0))
    selection = Selection.from_color(surface, 0, 0, 0)
    assert selection.mask is not None
    along = lambda edges: sorted(edge for edge in edges if edge[1] == edge[3] == 20)  # noqa: E731
    whole = along(selection.edges_within(0, 0, 600, 40))
    assert [(edge[0], edge[2]) for edge in whole] == [(0, 128), (128, 256), (256, 384), (384, 512), (512, 600)]
    assert along(selection.edges_within(200, 0, 300, 40)) == whole[1:3]
    assert along(selection.edges_within(520, 0, 590, 40)) == whole[4:]


def test_without_the_helper_everything_still_works(in_python):
    with in_python:
        assert not native.available()
        surface = new_surface(8, 8, WHITE)
        paint_pixel(surface, 4, 4, (0.0, 0.0, 0.0, 1.0))
        assert flood_fill(surface, 0, 0, rgba(1, 0, 0)) == (0, 0, 8, 8)
        selection = Selection.from_color(surface, 4, 4, 0)
        assert selection.rect == (4, 4, 1, 1)


def test_a_helper_that_is_missing_or_broken_is_done_without(monkeypatch, tmp_path):
    monkeypatch.setenv(native.ENVIRONMENT, "off")
    assert native._load() is None
    broken = tmp_path / native.LIBRARY_NAME
    broken.write_bytes(b"not a library")
    monkeypatch.setenv(native.ENVIRONMENT, str(broken))
    # Falls back on the one next to the source, if that was built, or on none.
    assert (native._load() is None) == (not (os.path.isfile(os.path.join(os.path.dirname(native.__file__), native.LIBRARY_NAME))))
