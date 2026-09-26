# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import math

import cairo
import pytest
from gi.repository import Adw, Gdk, Gio, GLib

from tempera import recent_files, settings
from tempera.canvas import PIXEL_GRID_ZOOM, Canvas
from tempera.color import ColorState
from tempera.document import Document, new_surface
from tempera.tools.airbrush import AirbrushTool, dots_per_spray
from tempera.tools.base import ToolContext
from tempera.window import TemperaWindow

from pixels import pixel_at, render_widget

WHITE = (1.0, 1.0, 1.0, 1.0)
WHITE_PIXEL = (255, 255, 255, 255)


def context(surface, size=10, density=50) -> ToolContext:
    black = Gdk.RGBA()
    black.parse("#000000")
    return ToolContext(
        surface=surface,
        primary=black,
        secondary=black,
        button=Gdk.BUTTON_PRIMARY,
        size=size,
        fill_shapes=False,
        pick_color=lambda color, btn: None,
        begin_text=lambda x, y, color: None,
        select_region=lambda x, y, width, height: None,
        density=density,
    )


def painted(surface) -> set[tuple[int, int]]:
    return {
        (x, y)
        for y in range(surface.get_height())
        for x in range(surface.get_width())
        if pixel_at(surface, x, y) != WHITE_PIXEL
    }


# The airbrush


def test_more_dots_for_a_bigger_or_denser_spray():
    assert dots_per_spray(20, 50) > dots_per_spray(10, 50)
    assert dots_per_spray(20, 100) > dots_per_spray(20, 50)
    assert dots_per_spray(1, 1) == 1


def test_the_spray_lands_inside_the_brush_circle():
    surface = new_surface(60, 60, WHITE)
    tool, ctx = AirbrushTool(seed=1), context(surface, size=20, density=100)
    tool.press(ctx, 30, 30)
    for _round in range(20):
        tool.repeat(ctx)
    dots = painted(surface)
    assert len(dots) > 100
    # Dots are whole pixels, so allow the one they were rounded into.
    assert all(math.hypot(x - 30, y - 30) <= 10 + 1.5 for x, y in dots)


def test_holding_still_keeps_spraying():
    surface = new_surface(60, 60, WHITE)
    tool, ctx = AirbrushTool(seed=2), context(surface, size=20)
    tool.press(ctx, 30, 30)
    first = len(painted(surface))
    tool.repeat(ctx)
    tool.repeat(ctx)
    assert len(painted(surface)) > first


def test_nothing_sprays_after_the_button_is_let_go():
    surface = new_surface(60, 60, WHITE)
    tool, ctx = AirbrushTool(seed=3), context(surface, size=20)
    tool.press(ctx, 30, 30)
    tool.release(ctx, 30, 30)
    before = painted(surface)
    tool.repeat(ctx)
    tool.motion(ctx, 10, 10)
    assert painted(surface) == before


def test_moving_sprays_where_the_pointer_goes():
    surface = new_surface(100, 40, WHITE)
    tool, ctx = AirbrushTool(seed=4), context(surface, size=10, density=100)
    tool.press(ctx, 10, 20)
    tool.motion(ctx, 90, 20)
    assert any(x > 80 for x, _y in painted(surface))


# The canvas holding the airbrush


@pytest.fixture
def canvas():
    canvas = Canvas(Document(new_surface(60, 60, WHITE)), ColorState())
    canvas.select_tool("airbrush")
    canvas.brush_size = 20
    return canvas


class FakeGesture:
    def get_current_button(self):
        return Gdk.BUTTON_PRIMARY

    def get_current_event_state(self):
        return Gdk.ModifierType(0)


def test_the_canvas_keeps_spraying_until_release_and_it_is_one_undo_step(canvas):
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 30, 30)
    assert canvas._repeat_source != 0
    first = len(painted(canvas.document.surface))
    for _tick in range(5):
        assert canvas._on_repeat() == GLib.SOURCE_CONTINUE
    assert len(painted(canvas.document.surface)) > first

    canvas._on_drag_end(gesture, 0, 0)
    assert canvas._repeat_source == 0

    canvas.document.undo()
    assert painted(canvas.document.surface) == set()
    assert not canvas.document.can_undo


def test_a_late_tick_after_release_does_nothing(canvas):
    gesture = FakeGesture()
    canvas._on_drag_begin(gesture, 30, 30)
    canvas._on_drag_end(gesture, 0, 0)
    before = painted(canvas.document.surface)
    assert canvas._on_repeat() == GLib.SOURCE_REMOVE
    assert painted(canvas.document.surface) == before


def test_the_density_reaches_the_tool(canvas):
    canvas.airbrush_density = 80
    assert canvas._make_context(Gdk.BUTTON_PRIMARY).density == 80


def test_other_tools_do_not_start_a_timer(canvas):
    canvas.select_tool("brush")
    canvas._on_drag_begin(FakeGesture(), 30, 30)
    assert canvas._repeat_source == 0
    canvas._on_drag_end(FakeGesture(), 0, 0)


# The pixel grid


def render(canvas) -> cairo.ImageSurface:
    width = round(canvas.document.width * canvas.zoom)
    height = round(canvas.document.height * canvas.zoom)
    return render_widget(canvas, width, height)


def test_the_grid_shows_only_when_on_and_zoomed_in(canvas):
    canvas.show_pixel_grid = True
    canvas.set_zoom(PIXEL_GRID_ZOOM / 2)
    assert not canvas.pixel_grid_visible
    canvas.set_zoom(PIXEL_GRID_ZOOM)
    assert canvas.pixel_grid_visible
    canvas.show_pixel_grid = False
    assert not canvas.pixel_grid_visible


def test_the_grid_draws_a_thin_line_between_pixels(canvas):
    canvas.set_zoom(8.0)
    plain = render(canvas)
    canvas.show_pixel_grid = True
    gridded = render(canvas)

    # A line runs along the left edge of image column 5 (screen column 40),
    # and the middle of that image pixel is untouched.
    assert pixel_at(gridded, 40, 44) != pixel_at(plain, 40, 44)
    assert pixel_at(gridded, 44, 44) == pixel_at(plain, 44, 44)


# The window


@pytest.fixture(scope="module")
def application():
    app = Adw.Application(
        application_id="io.github.rafael0rueda.Tempera.AirbrushTests",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )
    app.register(None)
    return app


@pytest.fixture
def window(application, monkeypatch, tmp_path):
    monkeypatch.setattr(recent_files, "_recent_file_path", lambda: tmp_path / "recent-files.txt")
    monkeypatch.setattr(settings, "_settings_path", lambda: tmp_path / "settings.ini")
    window = TemperaWindow(application)
    yield window
    window.destroy()


def test_the_airbrush_shows_its_density(window):
    window.lookup_action("tool").change_state(GLib.Variant.new_string("airbrush"))
    assert window._tool_options.get_visible_child_name() == "airbrush"
    window._density_scale.set_value(75)
    assert window.canvas.airbrush_density == 75


def test_the_grid_toggles_from_the_menu_and_says_when_it_is_too_far_out(window):
    toasts = []
    window.show_toast = toasts.append
    window.activate_action("win.pixel-grid", None)
    assert window.canvas.show_pixel_grid
    assert toasts and "400%" in toasts[0]

    window.activate_action("win.pixel-grid", None)
    assert not window.canvas.show_pixel_grid


def test_density_and_grid_are_remembered(application, window):
    window._density_scale.set_value(20)
    window.activate_action("win.pixel-grid", None)
    window._save_preferences()

    reopened = TemperaWindow(application)
    try:
        assert reopened.canvas.airbrush_density == 20
        assert reopened.canvas.show_pixel_grid
        assert reopened.lookup_action("pixel-grid").get_state().get_boolean()
    finally:
        reopened.destroy()


def test_airbrush_and_grid_have_shortcuts():
    from tempera import shortcuts

    assert shortcuts.keys_for("win.tool::airbrush") == ["a"]
    assert shortcuts.keys_for("win.pixel-grid") == ["<Control>g"]
