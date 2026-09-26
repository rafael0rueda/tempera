# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import random
import threading
import time

import pytest
from gi.repository import Gdk, GLib

from tempera.canvas import Canvas, pointer
from tempera.color import ColorState
from tempera.document import Document, changed_rect, copy_surface, new_surface, same_pixels
from tempera.tools.fill import _premultiplied, flood_fill

from pixels import paint_pixel, pixel_at

WHITE = (1.0, 1.0, 1.0, 1.0)
BLACK = (0.0, 0.0, 0.0, 1.0)


def rgba(r: float, g: float, b: float, a: float = 1.0) -> Gdk.RGBA:
    color = Gdk.RGBA()
    color.red, color.green, color.blue, color.alpha = r, g, b, a
    return color


def test_fills_a_matching_region_and_stops_at_the_boundary():
    surface = new_surface(4, 4, WHITE)
    for y in range(4):
        paint_pixel(surface, 2, y, BLACK)
        paint_pixel(surface, 3, y, BLACK)

    assert flood_fill(surface, 0, 0, rgba(0, 1, 0)) == (0, 0, 2, 4)

    assert pixel_at(surface, 0, 0) == (0, 255, 0, 255)
    assert pixel_at(surface, 1, 3) == (0, 255, 0, 255)
    # The black column was never matched, so it is untouched.
    assert pixel_at(surface, 2, 0) == (0, 0, 0, 255)
    assert pixel_at(surface, 3, 3) == (0, 0, 0, 255)


def test_tolerance_widens_what_counts_as_a_match():
    surface = new_surface(2, 1, WHITE)
    paint_pixel(surface, 1, 0, (0.9, 0.9, 0.9, 1.0))

    strict = new_surface(2, 1, WHITE)
    paint_pixel(strict, 1, 0, (0.9, 0.9, 0.9, 1.0))
    flood_fill(strict, 0, 0, rgba(0, 1, 0), tolerance=1)
    assert pixel_at(strict, 0, 0) == (0, 255, 0, 255)
    assert pixel_at(strict, 1, 0) != (0, 255, 0, 255)

    loose = surface
    flood_fill(loose, 0, 0, rgba(0, 1, 0), tolerance=64)
    assert pixel_at(loose, 0, 0) == (0, 255, 0, 255)
    assert pixel_at(loose, 1, 0) == (0, 255, 0, 255)


def test_filling_with_a_color_that_already_matches_is_a_no_op():
    surface = new_surface(2, 2, WHITE)
    assert flood_fill(surface, 0, 0, rgba(1, 1, 1)) is None
    assert pixel_at(surface, 1, 1) == (255, 255, 255, 255)


def test_out_of_bounds_coordinates_do_nothing():
    surface = new_surface(2, 2, WHITE)
    assert flood_fill(surface, -1, 0, rgba(0, 1, 0)) is None
    assert flood_fill(surface, 0, 2, rgba(0, 1, 0)) is None
    assert pixel_at(surface, 0, 0) == (255, 255, 255, 255)


def reference_flood_fill(surface, x, y, color, tolerance):
    """The original pixel-at-a-time fill, kept as the behaviour to match."""
    width, height = surface.get_width(), surface.get_height()
    if not (0 <= x < width and 0 <= y < height):
        return False
    surface.flush()
    stride = surface.get_stride()
    data = surface.get_data()
    replacement = _premultiplied(color)
    origin = y * stride + x * 4
    target = tuple(data[origin:origin + 4])

    def matches(offset):
        return all(abs(data[offset + i] - target[i]) <= tolerance for i in range(4))

    if all(abs(replacement[i] - target[i]) <= tolerance for i in range(4)):
        return False
    replacement_bytes = bytes(replacement)
    stack = [(x, y)]
    while stack:
        seed_x, seed_y = stack.pop()
        row = seed_y * stride
        if not matches(row + seed_x * 4):
            continue
        left = seed_x
        while left > 0 and matches(row + (left - 1) * 4):
            left -= 1
        right = seed_x
        while right < width - 1 and matches(row + (right + 1) * 4):
            right += 1
        data[row + left * 4:row + (right + 1) * 4] = replacement_bytes * (right - left + 1)
        for neighbour_y in (seed_y - 1, seed_y + 1):
            if not 0 <= neighbour_y < height:
                continue
            neighbour_row = neighbour_y * stride
            scan = left
            while scan <= right:
                if matches(neighbour_row + scan * 4):
                    stack.append((scan, neighbour_y))
                    while scan <= right and matches(neighbour_row + scan * 4):
                        scan += 1
                scan += 1
    surface.mark_dirty()
    return True


def random_image(rng, width, height):
    """Blotches of a few near-identical colours, so regions are ragged and tolerance matters."""
    palette = [(1.0, 1.0, 1.0, 1.0), (0.95, 0.95, 0.95, 1.0), (0.0, 0.0, 0.0, 1.0),
               (0.2, 0.6, 0.2, 1.0), (0.5, 0.5, 0.5, 0.5), (0.0, 0.0, 0.0, 0.0)]
    surface = new_surface(width, height, WHITE)
    for y in range(height):
        for x in range(width):
            if rng.random() < 0.35:
                paint_pixel(surface, x, y, rng.choice(palette))
    return surface


@pytest.mark.parametrize("seed", range(40))
def test_matches_the_original_fill_on_random_images(seed):
    rng = random.Random(seed)
    width, height = rng.randint(1, 23), rng.randint(1, 23)
    image = random_image(rng, width, height)
    x, y = rng.randrange(width), rng.randrange(height)
    color = rgba(rng.random(), rng.random(), rng.random(), rng.choice([1.0, 0.5]))
    tolerance = rng.choice([0, 8, 32, 64, 255])

    expected, actual = copy_surface(image), copy_surface(image)
    before = copy_surface(image)
    painted = flood_fill(actual, x, y, color, tolerance)
    assert (painted is not None) == reference_flood_fill(expected, x, y, color, tolerance)
    assert same_pixels(actual, expected)
    # Everything that changed lies inside the rectangle it says it painted.
    changed = changed_rect(before, actual)
    if painted is not None and changed is not None:
        px, py, pw, ph = painted
        cx, cy, cw, ch = changed
        assert px <= cx and py <= cy and cx + cw <= px + pw and cy + ch <= py + ph


def test_fills_a_region_that_winds_back_on_itself():
    # A spiral corridor: the fill has to turn up, down, left and right to finish.
    surface = new_surface(9, 9, BLACK)
    corridor = [(x, 1) for x in range(1, 8)] + [(7, y) for y in range(1, 8)]
    corridor += [(x, 7) for x in range(1, 8)] + [(1, y) for y in range(3, 8)]
    corridor += [(x, 3) for x in range(1, 6)] + [(5, 5), (5, 4), (4, 5), (3, 5)]
    for x, y in corridor:
        paint_pixel(surface, x, y, WHITE)

    assert flood_fill(surface, 1, 1, rgba(0, 1, 0))

    for x, y in corridor:
        assert pixel_at(surface, x, y) == (0, 255, 0, 255)
    assert pixel_at(surface, 0, 0) == (0, 0, 0, 255)
    assert pixel_at(surface, 2, 5) == (0, 0, 0, 255)


# Filling from the canvas, which runs the fill off the UI thread


class FakeGesture:
    def get_current_button(self):
        return Gdk.BUTTON_PRIMARY

    def get_current_event_state(self):
        return Gdk.ModifierType(0)


@pytest.fixture
def jobs(monkeypatch):
    """Background work held back until the test runs it, to control the order things happen in."""
    held = []
    monkeypatch.setattr(pointer, "run_in_background", lambda work, done: held.append((work, done)))
    return held


@pytest.fixture
def canvas():
    colors = ColorState()
    colors.primary = rgba(0, 1, 0)
    canvas = Canvas(Document(new_surface(20, 20, WHITE)), colors)
    canvas.select_tool("fill")
    return canvas


def run(job):
    work, done = job
    done(work())


def test_a_fill_let_go_before_it_is_done_lands_once_it_is(canvas, jobs):
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 5, 5)
    canvas._on_drag_end(gesture, 0, 0)
    # Still at work: nothing to undo yet, and the image actions wait.
    assert canvas.is_dragging
    assert not canvas.document.can_undo

    run(jobs.pop())

    assert not canvas.is_dragging
    assert pixel_at(canvas.document.surface, 5, 5) == (0, 255, 0, 255)
    canvas.document.undo()
    assert pixel_at(canvas.document.surface, 5, 5) == (255, 255, 255, 255)
    assert not canvas.document.can_undo
    assert [color.to_string() for color in canvas.colors.recent] == [rgba(0, 1, 0).to_string()]


def test_a_fill_done_before_it_is_let_go_lands_on_release(canvas, jobs):
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 5, 5)
    run(jobs.pop())
    assert canvas.is_dragging
    assert not canvas.document.can_undo

    canvas._on_drag_end(gesture, 0, 0)

    assert not canvas.is_dragging
    assert canvas.document.can_undo
    assert pixel_at(canvas.document.surface, 5, 5) == (0, 255, 0, 255)


def test_nothing_else_paints_while_a_fill_is_at_work(canvas, jobs):
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 5, 5)
    canvas._on_drag_end(gesture, 0, 0)

    # Another press, and a key, are both turned away.
    canvas._on_drag_begin(gesture, 1, 1)
    canvas._on_drag_end(gesture, 0, 0)
    assert len(jobs) == 1
    canvas.select_all()
    assert not canvas._on_key_pressed(None, Gdk.KEY_Delete, 0, Gdk.ModifierType(0))

    run(jobs.pop())
    assert pixel_at(canvas.document.surface, 5, 5) == (0, 255, 0, 255)


def test_a_fill_that_fails_still_ends_the_stroke(canvas, jobs, monkeypatch):
    def broken(ctx, x, y):
        raise RuntimeError("broken fill")

    monkeypatch.setattr(canvas.tools["fill"], "press", broken)
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 5, 5)
    canvas._on_drag_end(gesture, 0, 0)

    with pytest.raises(RuntimeError, match="broken fill"):
        run(jobs.pop())
    assert not canvas.is_dragging


def test_a_fill_runs_on_a_thread_of_its_own(canvas):
    threads = []
    original = canvas.tools["fill"].press

    def press(ctx, x, y):
        threads.append(threading.current_thread())
        original(ctx, x, y)

    canvas.tools["fill"].press = press
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 5, 5)
    canvas._on_drag_end(gesture, 0, 0)
    deadline = time.monotonic() + 5
    while canvas.is_dragging and time.monotonic() < deadline:
        GLib.MainContext.default().iteration(False)

    assert threads and threads[0] is not threading.main_thread()
    assert not canvas.is_dragging
    assert pixel_at(canvas.document.surface, 5, 5) == (0, 255, 0, 255)
