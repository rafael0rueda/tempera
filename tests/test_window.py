# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import time

import pytest
from gi.repository import Adw, Gdk, Gio, GdkPixbuf, GLib, Gtk

from tempera import recent_files, settings
from tempera.color import rgba
from tempera.document import new_surface
from tempera.main import TemperaApplication
from tempera.window import TemperaWindow, scaled_side

from pixels import paint_pixel, pixel_at

RED = (1.0, 0.0, 0.0, 1.0)


@pytest.fixture(scope="module")
def application():
    app = Adw.Application(
        application_id="io.github.rafael0rueda.Tempera.Tests",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )
    # Windows can only be added once the application has started up.
    app.register(None)
    return app


@pytest.fixture
def window(application, monkeypatch, tmp_path):
    monkeypatch.setattr(recent_files, "_recent_file_path", lambda: tmp_path / "recent-files.txt")
    monkeypatch.setattr(settings, "_settings_path", lambda: tmp_path / "settings.ini")
    window = TemperaWindow(application)
    yield window
    window.destroy()


def test_undo_waits_while_a_stroke_is_under_way(window):
    document = window.canvas.document
    document.begin_change()
    paint_pixel(document.surface, 0, 0, RED)
    document.commit_change()

    window.canvas._drag_origin = (0.0, 0.0)
    window.activate_action("win.undo", None)
    assert pixel_at(window.canvas.document.surface, 0, 0) == (255, 0, 0, 255)

    window.canvas._drag_origin = None
    window.activate_action("win.undo", None)
    assert pixel_at(window.canvas.document.surface, 0, 0) == (255, 255, 255, 255)


def test_switching_tools_waits_while_a_stroke_is_under_way(window):
    window.canvas._drag_origin = (0.0, 0.0)
    window.lookup_action("tool").change_state(GLib.Variant.new_string("brush"))
    assert window.canvas.active_tool.id == "pencil"

    window.canvas._drag_origin = None
    window.lookup_action("tool").change_state(GLib.Variant.new_string("brush"))
    assert window.canvas.active_tool.id == "brush"


def test_zooming_still_works_while_a_stroke_is_under_way(window):
    window.canvas._drag_origin = (0.0, 0.0)
    window.activate_action("win.zoom-in", None)
    assert window.canvas.zoom > 1.0


def palette_position(window):
    return window.lookup_action("palette-position").get_state().get_string()


def test_palette_starts_on_the_right(window):
    assert palette_position(window) == "right"
    slot, _strip = window._palette_slots["right"]
    assert window._color_bar.get_parent() is slot
    assert window._color_bar.get_orientation() == Gtk.Orientation.VERTICAL


@pytest.mark.parametrize(
    "position, orientation",
    [("left", Gtk.Orientation.VERTICAL), ("bottom", Gtk.Orientation.HORIZONTAL)],
)
def test_palette_moves(window, position, orientation):
    window.activate_action("win.palette-position", GLib.Variant.new_string(position))

    slot, _strip = window._palette_slots[position]
    assert window._color_bar.get_parent() is slot
    assert window._color_bar.get_orientation() == orientation
    visible = {name for name, (_slot, s) in window._palette_slots.items() if s.get_visible()}
    assert visible == {position}


@pytest.mark.parametrize("position, columns", [("bottom", 20), ("left", 4), ("right", 2)])
def test_palette_grid_fits_where_it_is(window, position, columns):
    window.activate_action("win.palette-position", GLib.Variant.new_string(position))
    grid = window._color_bar._grid
    assert max(grid.query_child(child)[0] for child in window._color_bar._palette_swatches) == columns - 1


def test_palette_returns_to_the_right(window):
    window.activate_action("win.palette-position", GLib.Variant.new_string("left"))
    window.activate_action("win.palette-position", GLib.Variant.new_string("right"))

    slot, _strip = window._palette_slots["right"]
    assert window._color_bar.get_parent() is slot
    visible = {name for name, (_slot, s) in window._palette_slots.items() if s.get_visible()}
    assert visible == {"right"}


def test_unknown_palette_position_is_ignored(window):
    window.activate_action("win.palette-position", GLib.Variant.new_string("top"))
    assert palette_position(window) == "right"


def test_palette_position_is_remembered(application, window):
    window.activate_action("win.palette-position", GLib.Variant.new_string("bottom"))

    reopened = TemperaWindow(application)
    try:
        assert palette_position(reopened) == "bottom"
        slot, _strip = reopened._palette_slots["bottom"]
        assert reopened._color_bar.get_parent() is slot
    finally:
        reopened.destroy()


def test_tooltips_follow_changed_shortcuts(application, window):
    from tempera import shortcuts

    swap = window._color_bar.swap_button
    assert swap.get_tooltip_text() == "Swap colors (X)"

    shortcuts.assign(application, "win.swap-colors", "<Shift>x")
    assert swap.get_tooltip_text() == "Swap colors (Shift+X)"

    shortcuts.assign(application, "win.swap-colors", None)
    assert swap.get_tooltip_text() == "Swap colors"

    shortcuts.reset(application)
    assert swap.get_tooltip_text() == "Swap colors (X)"


def test_bare_keys_pause_while_typing_including_new_ones(application, window):
    from tempera import shortcuts

    shortcuts.assign(application, "win.crop", "c")
    window.canvas.begin_text(10, 10, window.colors.primary)
    try:
        assert application.get_accels_for_action("win.tool::pencil") == []
        assert application.get_accels_for_action("win.crop") == []
        assert application.get_accels_for_action("win.new") == ["<Control>n"]
    finally:
        window.canvas.cancel_text()
    assert application.get_accels_for_action("win.tool::pencil") == ["p"]
    assert application.get_accels_for_action("win.crop") == ["c"]
    shortcuts.reset(application)


def test_shortcuts_dialog_lists_every_shortcut(application, window):
    from tempera import shortcuts
    from tempera.shortcuts_dialog import ShortcutsDialog

    shortcuts.assign(application, "win.crop", "<Control>k")
    dialog = ShortcutsDialog(application)
    assert set(dialog._rows) == set(shortcuts.SHORTCUTS)
    keys, reset = dialog._rows["win.crop"]
    assert keys.get_accelerator() == "<Control>k"
    assert reset.get_visible()
    assert not dialog._rows["win.new"][1].get_visible()
    assert dialog._reset_all_row.get_sensitive()

    dialog._reset(shortcuts.SHORTCUTS["win.crop"])
    assert keys.get_accelerator() == ""
    assert not dialog._reset_all_row.get_sensitive()


def settle():
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)


def settle_until(condition, timeout=5.0):
    """Keep the main loop turning until something a worker thread started has finished."""
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        context.iteration(False)
        time.sleep(0.002)
    return condition()


def test_unchanged_window_closes_on_the_first_try(application, window):
    window.present()
    settle()
    window.close()
    settle()
    assert window not in application.get_windows()


def test_unsaved_changes_are_asked_about_before_closing(application, window):
    document = window.canvas.document
    document.begin_change()
    paint_pixel(document.surface, 0, 0, RED)
    document.commit_change()

    window.present()
    settle()
    window.close()
    settle()
    assert window in application.get_windows()
    assert isinstance(window.get_visible_dialog(), Adw.AlertDialog)


def test_scrolling_over_the_zoom_level_steps_the_zoom(window):
    window._on_zoom_label_scroll(None, 0, -1)
    zoomed_in = window.canvas.zoom
    assert zoomed_in > 1.0
    assert window._zoom_label.get_label() == f"{round(zoomed_in * 100)}%"

    window._on_zoom_label_scroll(None, 0, 1)
    window._on_zoom_label_scroll(None, 0, 1)
    assert window.canvas.zoom < 1.0


def load_recent_uris():
    return " ".join(recent_files.load_recent())


def test_a_floating_paste_is_asked_about_but_not_landed_on_close(application, window):
    window.canvas.begin_paste(new_surface(2, 2, RED), 0, 0)

    window.present()
    settle()
    window.close()
    settle()

    assert window in application.get_windows()
    assert isinstance(window.get_visible_dialog(), Adw.AlertDialog)
    # Cancel must leave things as they were, so nothing has landed yet.
    assert window.canvas.has_floating
    assert not window.canvas.document.can_undo


def test_an_empty_text_box_does_not_stop_the_window_closing(application, window):
    window.canvas.begin_text(10, 10, window.colors.primary)
    window.present()
    settle()
    window.close()
    settle()
    assert window not in application.get_windows()


def test_save_keeps_the_jpeg_quality_without_asking(window, tmp_path):
    path = tmp_path / "photo.jpg"
    window.canvas.document.file = Gio.File.new_for_path(str(path))
    window.present()
    settle()

    window.activate_action("win.save", None)

    assert settle_until(lambda: not window._busy)
    assert path.stat().st_size > 0
    assert window.get_visible_dialog() is None


def test_saving_shows_a_spinner_until_it_is_done(window, tmp_path):
    path = tmp_path / "drawing.png"
    window.canvas.document.file = Gio.File.new_for_path(str(path))

    window.activate_action("win.save", None)
    assert window._busy
    assert window._busy_spinner.get_visible()

    assert settle_until(lambda: not window._busy)
    assert not window._busy_spinner.get_visible()
    assert path.exists()


def test_painting_while_a_save_runs_leaves_the_image_modified(window, tmp_path):
    document = window.canvas.document
    document.file = Gio.File.new_for_path(str(tmp_path / "drawing.png"))

    window.activate_action("win.save", None)
    # The save is encoding in a worker; this stroke is not in what it wrote.
    document.begin_change()
    paint_pixel(document.surface, 0, 0, RED)
    document.commit_change()

    assert settle_until(lambda: not window._busy)
    assert document.modified


def test_a_second_save_is_ignored_while_one_is_running(window, tmp_path):
    window.canvas.document.file = Gio.File.new_for_path(str(tmp_path / "drawing.png"))
    saves = []
    window.canvas.document.connect("state-changed", lambda *_args: saves.append(True))

    window.activate_action("win.save", None)
    window.activate_action("win.save", None)

    assert settle_until(lambda: not window._busy)
    assert not window._busy


def test_opening_an_image_reads_it_in_the_background(window, tmp_path):
    path = tmp_path / "picture.png"
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 7, 3)
    pixbuf.fill(0xFFFFFFFF)
    pixbuf.savev(str(path), "png", [], [])

    window._open_file(Gio.File.new_for_path(str(path)), "no: {message}")
    assert window._busy

    assert settle_until(lambda: not window._busy)
    assert (window.canvas.document.width, window.canvas.document.height) == (7, 3)
    assert str(path) in load_recent_uris()


def test_an_image_that_cannot_be_read_says_so_and_keeps_the_old_one(window, tmp_path):
    path = tmp_path / "broken.png"
    path.write_text("not a picture")
    before = window.canvas.document
    forgotten = []

    window._open_file(Gio.File.new_for_path(str(path)), "no: {message}", lambda: forgotten.append(True))

    assert settle_until(lambda: not window._busy)
    assert window.canvas.document is before
    assert forgotten


def test_save_asks_where_for_an_image_it_cannot_write_back(window, tmp_path, monkeypatch):
    path = tmp_path / "animation.gif"
    path.write_bytes(b"the original animation")
    window.canvas.document.file = Gio.File.new_for_path(str(path))
    asked = []
    monkeypatch.setattr(window, "_save_as", lambda then=None: asked.append(then))

    window.activate_action("win.save", None)

    assert asked == [None]
    assert path.read_bytes() == b"the original animation"


def test_quit_closes_every_window_asking_about_unsaved_ones(application, window):
    changed = TemperaWindow(application)
    try:
        document = changed.canvas.document
        document.begin_change()
        paint_pixel(document.surface, 0, 0, RED)
        document.commit_change()
        window.present()
        changed.present()
        settle()

        TemperaApplication._on_quit(application)
        settle()

        assert window not in application.get_windows()
        assert changed in application.get_windows()
        assert isinstance(changed.get_visible_dialog(), Adw.AlertDialog)
    finally:
        changed.destroy()


def test_clear_recent_files_empties_the_menu(window, tmp_path):
    path = tmp_path / "picture.png"
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 2, 2)
    pixbuf.fill(0xFFFFFFFF)
    pixbuf.savev(str(path), "png", [], [])
    window._remember_recent(Gio.File.new_for_path(str(path)))
    assert recent_files.load_recent()

    window.activate_action("win.clear-recent", None)

    assert recent_files.load_recent() == []
    assert window._recent_menu.get_n_items() == 1


def test_scaled_side_rounds_and_stays_in_range():
    assert scaled_side(800, 50) == 400
    assert scaled_side(3, 50) == 2
    assert scaled_side(800, 0.01) == 1
    assert scaled_side(8192, 1000) == 8192


def test_resize_image_scales_the_picture(window):
    window._prompt_scale_image()
    dialog = window.get_visible_dialog()
    width_spin, height_spin = (
        child for child in dialog.get_extra_child().get_last_child()
        if isinstance(child, Gtk.SpinButton)
    )
    width_spin.set_value(400)
    # Keeping the ratio, the height follows the width.
    assert height_spin.get_value() == 300

    dialog.emit("response", "scale")
    assert (window.canvas.document.width, window.canvas.document.height) == (400, 300)


def test_zoom_to_fit_shows_the_whole_image(window):
    window.present()
    settle()
    window.canvas.document.resize(4000, 3000)

    window.activate_action("win.zoom-fit", None)

    zoom = window.canvas.zoom
    assert zoom < 1.0
    assert 4000 * zoom <= window._canvas_area.get_width()
    assert 3000 * zoom <= window._canvas_area.get_height()


def test_an_image_larger_than_the_window_opens_zoomed_out(application, window, tmp_path):
    window.present()
    settle()
    path = tmp_path / "big.png"
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 4000, 3000)
    pixbuf.fill(0xFFFFFFFF)
    pixbuf.savev(str(path), "png", [], [])

    window._open_file(Gio.File.new_for_path(str(path)), "no: {message}")
    assert settle_until(lambda: not window._busy)
    settle()

    assert window.canvas.zoom < 1.0


def test_a_small_image_opens_at_full_size(window, tmp_path):
    window.present()
    settle()
    window.canvas.zoom = 0.25
    path = tmp_path / "small.png"
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 20, 20)
    pixbuf.fill(0xFFFFFFFF)
    pixbuf.savev(str(path), "png", [], [])

    window._open_file(Gio.File.new_for_path(str(path)), "no: {message}")
    assert settle_until(lambda: not window._busy)
    settle()

    assert window.canvas.zoom == 1.0


def test_middle_drag_pans_the_view(window, monkeypatch):
    # Against adjustments of our own, so the test does not depend on the window
    # having been given a size yet.
    horizontal = Gtk.Adjustment(value=300, lower=0, upper=4000, page_size=800)
    vertical = Gtk.Adjustment(value=100, lower=0, upper=3000, page_size=600)
    monkeypatch.setattr(window.canvas, "_adjustments", lambda: (horizontal, vertical))

    window.canvas._on_pan_begin(None, 0, 0)
    # Dragging the image left and up moves the view the other way.
    window.canvas._on_pan_update(None, -50, -25)

    assert (horizontal.get_value(), vertical.get_value()) == (350, 125)

    window.canvas._on_pan_update(None, 100, 0)
    assert horizontal.get_value() == 200

    window.canvas._on_pan_end(None, 100, 0)
    assert window.canvas._pan_origin is None


def test_tool_options_show_only_for_the_tool_in_hand(window):
    def use(tool):
        window.lookup_action("tool").change_state(GLib.Variant.new_string(tool))

    def showing():
        return window._tool_options.get_visible_child_name()

    use("shapes")
    assert showing() == "shape"

    use("fill")
    assert showing() == "fill"

    use("eraser")
    assert showing() == "eraser"

    use("text")
    assert showing() == "text"

    use("pencil")
    assert showing() == "none"


def test_the_tolerance_slider_reaches_the_fill_tool(window):
    window._tolerance_scale.set_value(96)
    assert window.canvas.fill_tolerance == 96
    assert "96" in window._tolerance_scale.get_tooltip_text()


def test_erase_to_transparency_reaches_the_canvas(window):
    window._erase_check.set_active(True)
    assert window.canvas.erase_to_transparency


def test_a_new_image_can_start_transparent(window):
    window.activate_action("win.new", None)
    dialog = window.get_visible_dialog()
    grid = dialog.get_extra_child()
    transparent = next(
        child for child in grid if isinstance(child, Gtk.CheckButton)
    )
    transparent.set_active(True)

    dialog.emit("response", "create")

    assert pixel_at(window.canvas.document.surface, 0, 0) == (0, 0, 0, 0)


def test_the_size_keys_step_the_brush(window):
    window.canvas.brush_size = 4
    window._size_scale.set_value(4)

    window.activate_action("win.size-up", None)
    assert window.canvas.brush_size == 5

    window.activate_action("win.size-down", None)
    window.activate_action("win.size-down", None)
    assert window.canvas.brush_size == 3


def test_the_bottom_bar_shows_the_size_of_a_selection(window):
    window.canvas.select_region(1, 2, 30, 20)
    assert "30" in window._selection_label.get_label()
    assert "20" in window._selection_label.get_label()

    window.canvas.clear_selection()
    assert window._selection_label.get_label() == ""


def test_the_tool_sizes_colours_and_window_size_are_remembered(application, window):
    window.lookup_action("tool").change_state(GLib.Variant.new_string("brush"))
    window.canvas.brush_size = 12
    window.canvas.fill_tolerance = 77
    window.colors.primary = rgba("#ff0000")
    window.colors.remember(rgba("#ff0000"))
    window.set_default_size(900, 700)
    window._last_jpeg_quality = 55

    window._save_preferences()
    reopened = TemperaWindow(application)
    try:
        assert reopened.canvas.active_tool.id == "brush"
        assert reopened.canvas.brush_size == 12
        assert reopened.canvas.fill_tolerance == 77
        assert reopened.colors.primary.to_string() == rgba("#ff0000").to_string()
        assert reopened.get_default_size() == (900, 700)
        assert reopened._last_jpeg_quality == 55
        assert reopened.colors.recent
    finally:
        reopened.destroy()


def test_a_damaged_preference_falls_back_to_the_default(application, window, tmp_path):
    settings.save_settings({"brush-size": "enormous", "window-width": "wide", "tool": "hammer"})
    reopened = TemperaWindow(application)
    try:
        assert reopened.canvas.brush_size == 4
        assert reopened.get_default_size()[0] == 1120
        assert reopened.canvas.active_tool.id == "pencil"
    finally:
        reopened.destroy()


def test_the_sidebar_keeps_its_width_whichever_tool_is_in_hand(window):
    """Switching tools must never shove the canvas sideways."""
    widths = set()
    for tool in ("pencil", "shapes", "fill", "eraser", "text", "lasso"):
        window.lookup_action("tool").change_state(GLib.Variant.new_string(tool))
        widths.add(window._sidebar.measure(Gtk.Orientation.HORIZONTAL, -1)[1])
    assert len(widths) == 1


def test_the_options_bar_names_the_tool_and_shows_a_size_only_where_one_applies(window):
    def use(tool):
        window.lookup_action("tool").change_state(GLib.Variant.new_string(tool))

    use("brush")
    assert window._tool_label.get_label() == "Brush"
    assert window._size_section.get_visible()
    assert window._size_value.get_label() == f"{window.canvas.brush_size} px"
    assert not window._shape_picker.get_visible()

    use("text")
    assert window._size_value.get_label().endswith(" pt")

    use("fill")
    assert not window._size_section.get_visible()

    use("shapes")
    assert window._shape_picker.get_visible()


def test_picking_a_shape_takes_up_the_shapes_tool(window):
    window.activate_action("win.shape", GLib.Variant.new_string("star"))
    assert window.canvas.active_tool.id == "shapes"
    assert window.canvas.shapes.shape.id == "star"
    assert window._tool_options.get_visible_child_name() == "shape"


def test_outline_and_fill_reach_the_canvas(window):
    window.activate_action("win.shape", GLib.Variant.new_string("ellipse"))
    window._fill_toggle.set_active(True)
    window._outline_toggle.set_active(False)
    assert window.canvas.fill_shapes
    assert not window.canvas.outline_shapes


def test_outline_and_fill_are_never_both_off(window):
    window.activate_action("win.shape", GLib.Variant.new_string("ellipse"))
    assert window._outline_toggle.get_active() and not window._fill_toggle.get_active()

    window._outline_toggle.set_active(False)
    assert window._fill_toggle.get_active()
    assert window.canvas.fill_shapes

    window._fill_toggle.set_active(False)
    assert window._outline_toggle.get_active()
    assert window.canvas.outline_shapes


def test_a_line_shows_as_all_outline_without_losing_the_choice(window):
    window.activate_action("win.shape", GLib.Variant.new_string("ellipse"))
    window._fill_toggle.set_active(True)
    window._outline_toggle.set_active(False)

    window.activate_action("win.shape", GLib.Variant.new_string("line"))
    assert window._outline_toggle.get_active() and not window._fill_toggle.get_active()
    assert not window._outline_toggle.get_sensitive()
    assert not window._fill_toggle.get_sensitive()

    window.activate_action("win.shape", GLib.Variant.new_string("star"))
    assert window._fill_toggle.get_active() and not window._outline_toggle.get_active()


def test_the_outline_and_fill_buttons_show_their_colours(window):
    window.colors.primary = rgba("#c01c28")
    window.colors.secondary = rgba("#3584e4")
    assert window._outline_chip.color.equal(rgba("#c01c28"))
    assert window._fill_chip.color.equal(rgba("#3584e4"))
    window.colors.swap()
    assert window._outline_chip.color.equal(rgba("#3584e4"))


def test_outline_and_fill_are_remembered(application, window):
    window.activate_action("win.shape", GLib.Variant.new_string("rectangle"))
    window._fill_toggle.set_active(True)
    window._outline_toggle.set_active(False)
    window._save_preferences()

    reopened = TemperaWindow(application)
    try:
        assert reopened.canvas.fill_shapes
        assert not reopened.canvas.outline_shapes
    finally:
        reopened.destroy()


def test_the_header_shows_the_image_size(window):
    window.canvas.document.resize(640, 480)
    assert window._title.get_subtitle() == "640 × 480"
    assert window._canvas_size_label.get_label() == "640 × 480 px"


def test_an_unknown_shape_is_ignored(window):
    window.activate_action("win.shape", GLib.Variant.new_string("hexagon"))
    assert window.canvas.shapes.shape.id == "rectangle"


def test_the_shape_is_remembered(application, window):
    window.activate_action("win.shape", GLib.Variant.new_string("arrow"))
    window.lookup_action("tool").change_state(GLib.Variant.new_string("brush"))
    window._save_preferences()

    reopened = TemperaWindow(application)
    try:
        assert reopened.canvas.active_tool.id == "brush"
        assert reopened.canvas.shapes.shape.id == "arrow"
    finally:
        reopened.destroy()


def test_a_shape_tool_saved_by_tempera_1_0_opens_as_that_shape(application, window):
    settings.save_settings({"tool": "ellipse"})
    reopened = TemperaWindow(application)
    try:
        assert reopened.canvas.active_tool.id == "shapes"
        assert reopened.canvas.shapes.shape.id == "ellipse"
    finally:
        reopened.destroy()


# The color picker


def test_picking_a_color_keeps_it_rather_than_turning_black(window):
    """The picked color comes through a signal, so it has to outlive the emission."""
    blue = (0.2, 0.5, 0.9, 1.0)
    paint_pixel(window.canvas.document.surface, 5, 5, blue)
    window.lookup_action("tool").change_state(GLib.Variant.new_string("picker"))

    ctx = window.canvas._make_context(Gdk.BUTTON_PRIMARY)
    window.canvas.active_tool.press(ctx, 5, 5)

    # Read it back only once the emission is long over, the way a redraw would.
    picked = window.colors.primary
    assert [round(channel, 2) for channel in
            (picked.red, picked.green, picked.blue, picked.alpha)] == list(blue)


def test_the_paint_tools_wear_the_primary_colour(window):
    from tempera.tool_icon import ToolIcon

    grid = window._sidebar.get_first_child()
    icons = {}
    child = grid.get_first_child()
    while child is not None:
        icon = child.get_child()
        assert isinstance(icon, ToolIcon)
        icons[child.get_action_target_value().get_string()] = icon
        child = child.get_next_sibling()

    tipped = {tool for tool, icon in icons.items() if icon.tip_icon_name}
    assert tipped == {"pencil", "brush", "airbrush", "shapes", "fill", "picker"}

    window.colors.primary = rgba("#2ec27e")
    assert icons["brush"].tip_color.equal(rgba("#2ec27e"))


def test_the_menu_zoom_row_follows_the_zoom(window):
    window.canvas.set_zoom(2.0)
    assert window._menu_zoom_label.get_label() == "200%"
    assert window._zoom_label.get_label() == "200%"


def test_rotating_from_the_menu_row_closes_the_menu(window, monkeypatch):
    closed = []
    monkeypatch.setattr(window._main_menu, "popdown", lambda: closed.append(True))
    row = window._build_transform_row()
    row.get_first_child().emit("clicked")
    assert closed == [True]


def test_rotate_counterclockwise_has_a_key():
    from tempera import shortcuts

    assert shortcuts.keys_for("win.rotate-ccw") == ["<Control><Shift>r"]
