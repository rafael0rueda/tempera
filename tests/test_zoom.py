# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later


from tempera.canvas import fit_zoom, ZOOM_MAX, ZOOM_MIN, ZOOM_PRESETS, Canvas
from tempera.color import ColorState
from tempera.document import Document, new_surface

from pixels import paint_pixel, pixel_at, render_widget

WHITE = (1.0, 1.0, 1.0, 1.0)
BLACK = (0.0, 0.0, 0.0, 1.0)


def make_canvas() -> Canvas:
    return Canvas(Document(), ColorState())


def test_default_zoom_is_100_percent():
    assert make_canvas().zoom == 1.0


def test_zoom_in_and_out_step_through_presets():
    canvas = make_canvas()
    canvas.zoom_in()
    assert canvas.zoom == ZOOM_PRESETS[ZOOM_PRESETS.index(1.0) + 1]

    canvas.zoom_out()
    assert canvas.zoom == 1.0

    canvas.zoom_out()
    assert canvas.zoom == ZOOM_PRESETS[ZOOM_PRESETS.index(1.0) - 1]


def test_zoom_in_past_the_top_preset_clamps_to_zoom_max():
    canvas = make_canvas()
    canvas.set_zoom(ZOOM_MAX)
    canvas.zoom_in()
    assert canvas.zoom == ZOOM_MAX


def test_zoom_out_past_the_bottom_preset_clamps_to_zoom_min():
    canvas = make_canvas()
    canvas.set_zoom(ZOOM_MIN)
    canvas.zoom_out()
    assert canvas.zoom == ZOOM_MIN


def test_set_zoom_clamps_to_the_allowed_range():
    canvas = make_canvas()
    canvas.set_zoom(ZOOM_MAX * 10)
    assert canvas.zoom == ZOOM_MAX

    canvas.set_zoom(ZOOM_MIN / 10)
    assert canvas.zoom == ZOOM_MIN


def test_reset_zoom_returns_to_100_percent():
    canvas = make_canvas()
    canvas.set_zoom(2.0)
    canvas.reset_zoom()
    assert canvas.zoom == 1.0


def test_set_zoom_to_the_current_value_is_a_no_op():
    canvas = make_canvas()
    changes = []
    canvas.connect("zoom-changed", lambda _canvas, zoom: changes.append(zoom))
    canvas.set_zoom(1.0)
    assert changes == []


def test_set_zoom_emits_zoom_changed():
    canvas = make_canvas()
    changes = []
    canvas.connect("zoom-changed", lambda _canvas, zoom: changes.append(zoom))
    canvas.set_zoom(2.0)
    assert changes == [2.0]


# Drawing


def render(canvas: Canvas, width: int, height: int):
    """Draw the canvas widget into an image, the way GTK would on screen."""
    return render_widget(canvas, width, height)


def test_zoomed_in_pixels_stay_crisp():
    # One black pixel on white, at 400%: every screen pixel around it is one or
    # the other, never the grey a smoothing filter would blend in between.
    surface = new_surface(40, 40, WHITE)
    paint_pixel(surface, 10, 10, BLACK)
    canvas = Canvas(Document(surface), ColorState())
    canvas.set_zoom(4.0)

    # Rendered well inside the image, clear of the resize grips on its edges.
    screen = render(canvas, 60, 60)

    row = [pixel_at(screen, x, 42) for x in range(36, 48)]
    assert row == [(255, 255, 255, 255)] * 4 + [(0, 0, 0, 255)] * 4 + [(255, 255, 255, 255)] * 4


def test_transparency_shows_the_checkerboard():
    canvas = Canvas(Document(new_surface(20, 20, (0.0, 0.0, 0.0, 0.0))), ColorState())
    screen = render(canvas, 20, 20)
    light, dark = (255, 255, 255, 255), (230, 230, 230, 255)
    assert pixel_at(screen, 3, 3) == light
    assert pixel_at(screen, 11, 3) == dark
    assert pixel_at(screen, 3, 11) == dark
    assert pixel_at(screen, 11, 11) == light
    assert pixel_at(screen, 17, 3) == light


# fit_zoom


def test_fit_zoom_uses_the_tighter_side():
    assert fit_zoom((800, 600), (400, 600)) == 0.5
    assert fit_zoom((800, 600), (800, 300)) == 0.5


def test_fit_zoom_enlarges_a_small_image():
    assert fit_zoom((100, 100), (400, 400)) == 4.0
