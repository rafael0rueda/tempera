# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import cairo
import pytest
from gi.repository import Gtk

from tempera import printing, recent_files, settings
from tempera.document import new_surface
from tempera.printing import ACTUAL, FIT, LANDSCAPE, PORTRAIT, PrintDialog, PrintJob, layout
from tempera.window import TemperaWindow

from pixels import pixel_at

RED = (1.0, 0.0, 0.0, 1.0)
RED_PIXEL = (255, 0, 0, 255)
CLEAR_PIXEL = (0, 0, 0, 0)

# Actual size, in points per pixel.
ACTUAL_SCALE = 0.75


# Laying it out


def test_fitting_fills_the_page_one_way_and_centres_the_other():
    placement = layout(200, 100, 500, 700, FIT)
    assert placement.scale == 2.5
    assert (placement.x, placement.y) == (0, 225)
    assert placement.pages == 1


def test_fitting_enlarges_a_small_image_too():
    assert layout(10, 10, 500, 700, FIT).scale == 50


def test_actual_size_is_the_size_on_screen_centred_on_the_page():
    placement = layout(96, 192, 500, 700, ACTUAL)
    assert placement.scale == ACTUAL_SCALE
    # One inch by two, in the middle of the page.
    assert (placement.x, placement.y) == ((500 - 72) / 2, (700 - 144) / 2)
    assert placement.pages == 1


def test_actual_size_spreads_a_big_image_over_pages_from_the_top_left():
    # 1050 by 1500 points, on pages of 500 by 700.
    placement = layout(1400, 2000, 500, 700, ACTUAL)
    assert (placement.columns, placement.rows) == (3, 3)
    assert (placement.x, placement.y) == (0, 0)


def test_an_image_that_just_fits_takes_one_page():
    placement = layout(int(500 / ACTUAL_SCALE), 100, 500, 700, ACTUAL)
    assert placement.pages == 1


def test_the_page_turns_with_the_image():
    assert printing.orientation_for(300, 200) == LANDSCAPE
    assert printing.orientation_for(200, 300) == PORTRAIT
    assert printing.orientation_for(200, 200) == PORTRAIT


# Drawing the pages


def render(image, placement, page, width=40, height=40):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    printing.draw_page(cairo.Context(surface), image, placement, page, width, height)
    return surface


def test_a_page_shows_the_image_where_the_layout_puts_it():
    page = render(new_surface(10, 20, RED), layout(10, 20, 40, 40, FIT), 0)
    # 20 by 40, in the middle.
    assert pixel_at(page, 20, 20) == RED_PIXEL
    assert pixel_at(page, 5, 20) == CLEAR_PIXEL


def test_each_page_shows_its_own_part_of_the_image():
    image = new_surface(4, 1, RED)
    # The right half blue, so each page can tell which part it got.
    cr = cairo.Context(image)
    cr.set_source_rgb(0, 0, 1)
    cr.rectangle(2, 0, 2, 1)
    cr.fill()
    placement = printing.Layout(scale=10, x=0, y=0, columns=2, rows=1)

    assert pixel_at(render(image, placement, 0, 20, 10), 10, 5) == RED_PIXEL
    assert pixel_at(render(image, placement, 1, 20, 10), 10, 5) == (0, 0, 255, 255)


def test_enlarged_pixels_stay_sharp():
    image = new_surface(2, 1, RED)
    cr = cairo.Context(image)
    cr.set_source_rgb(0, 0, 1)
    cr.rectangle(1, 0, 1, 1)
    cr.fill()
    page = render(image, layout(2, 1, 40, 20, FIT), 0, 40, 20)
    # Right up against the edge between the two pixels, nothing is blended.
    assert pixel_at(page, 19, 10) == RED_PIXEL
    assert pixel_at(page, 20, 10) == (0, 0, 255, 255)


# The print job


def export(job: PrintJob, path) -> int:
    """Print the job to a PDF without any dialog, and count the pages drawn."""
    operation = job.operation()
    operation.set_export_filename(str(path))
    pages = []
    operation.connect("draw-page", lambda _operation, _context, page: pages.append(page))
    result = operation.run(Gtk.PrintOperationAction.EXPORT, None)
    assert result == Gtk.PrintOperationResult.APPLY
    assert path.read_bytes().startswith(b"%PDF")
    return len(pages)


def test_a_fitted_image_prints_one_page(tmp_path):
    job = PrintJob(new_surface(3000, 2000, RED), "Big", FIT, LANDSCAPE)
    assert export(job, tmp_path / "out.pdf") == 1


def test_a_big_image_at_actual_size_prints_on_several_pages(tmp_path):
    job = PrintJob(new_surface(3000, 2000, RED), "Big", ACTUAL, LANDSCAPE)
    assert export(job, tmp_path / "out.pdf") > 1


def test_the_job_keeps_the_image_as_it_was():
    image = new_surface(4, 4, RED)
    job = PrintJob(image, "Untitled", FIT, PORTRAIT)
    cairo.Context(image).paint()  # black, after Print was chosen
    assert pixel_at(job.surface, 1, 1) == RED_PIXEL


def test_the_job_is_named_after_the_image_and_turned_its_way():
    operation = PrintJob(new_surface(4, 4, RED), "cat.png", FIT, LANDSCAPE).operation()
    assert operation.props.job_name == "cat.png"
    assert operation.get_default_page_setup().get_orientation() == LANDSCAPE


def test_the_last_paper_is_remembered():
    chosen = Gtk.PrintSettings()
    chosen.set_paper_size(Gtk.PaperSize.new(Gtk.PAPER_NAME_A5))
    printing.save_print_settings(chosen)

    remembered = printing.load_print_settings()
    assert remembered.get_paper_size().get_name() == Gtk.PAPER_NAME_A5
    page_setup = PrintJob(new_surface(4, 4, RED), "x", FIT, PORTRAIT).operation(
        remembered
    ).get_default_page_setup()
    assert page_setup.get_paper_size().get_name() == Gtk.PAPER_NAME_A5


def test_nothing_remembered_is_the_local_default(private_print_settings):
    assert printing.load_print_settings() is None
    private_print_settings.write_text("not a key file")
    assert printing.load_print_settings() is None


# Tempera's print dialog


def test_the_dialog_starts_from_the_image_shape_and_the_last_size():
    dialog = PrintDialog(new_surface(300, 200, RED), ACTUAL, lambda *_args: None)
    assert dialog.size == ACTUAL
    assert dialog.orientation == LANDSCAPE

    dialog = PrintDialog(new_surface(200, 300, RED), "nonsense", lambda *_args: None)
    assert dialog.size == FIT
    assert dialog.orientation == PORTRAIT


def test_the_dialog_says_when_it_takes_more_than_one_page():
    dialog = PrintDialog(new_surface(3000, 2000, RED), FIT, lambda *_args: None)
    assert not dialog.pages_label.get_visible()
    dialog.set_size(ACTUAL)
    assert dialog.pages_label.get_visible()
    assert str(dialog.page_layout().pages) in dialog.pages_label.get_label()


def test_the_preview_draws_the_image_on_a_page():
    dialog = PrintDialog(new_surface(20, 20, RED), FIT, lambda *_args: None)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 100)
    dialog._draw_preview(None, cairo.Context(surface), 100, 100)
    assert pixel_at(surface, 50, 50) == RED_PIXEL
    # A square image on an upright page leaves white paper above it, and
    # nothing is drawn beside the page.
    assert pixel_at(surface, 50, 5) == (255, 255, 255, 255)
    assert pixel_at(surface, 1, 50) == CLEAR_PIXEL


def test_print_hands_on_the_choices():
    chosen = []
    dialog = PrintDialog(new_surface(20, 20, RED), FIT, lambda *args: chosen.append(args))
    dialog.set_orientation(LANDSCAPE)
    dialog.set_size(ACTUAL)
    dialog.emit("response", "print")
    assert chosen == [(ACTUAL, LANDSCAPE)]

    chosen.clear()
    dialog.emit("response", "cancel")
    assert chosen == []


# The window


@pytest.fixture
def window(application, monkeypatch, tmp_path):
    monkeypatch.setattr(recent_files, "_recent_file_path", lambda: tmp_path / "recent-files.txt")
    monkeypatch.setattr(settings, "_settings_path", lambda: tmp_path / "settings.ini")
    window = TemperaWindow(application)
    window.present()
    yield window
    window.destroy()


def test_print_asks_first_and_remembers_the_size(window, monkeypatch):
    jobs = []
    monkeypatch.setattr(printing, "print_image", lambda parent, job, on_error: jobs.append(job))
    window.activate_action("win.print", None)
    dialog = window.get_visible_dialog()
    assert isinstance(dialog, PrintDialog)

    dialog.set_size(ACTUAL)
    dialog.emit("response", "print")
    dialog.force_close()
    assert jobs and jobs[0].size == ACTUAL
    assert jobs[0].title == window.canvas.document.title
    assert settings.load_setting("print-size") == ACTUAL

    window.activate_action("win.print", None)
    dialog = window.get_visible_dialog()
    assert dialog.size == ACTUAL
    dialog.force_close()


def test_print_lands_what_is_floating_first(window, monkeypatch):
    landed = []
    monkeypatch.setattr(window.canvas, "commit_floating", lambda: landed.append(True))
    window.activate_action("win.print", None)
    window.get_visible_dialog().force_close()
    assert landed


def test_print_has_a_shortcut_and_a_menu_entry():
    from tempera import shortcuts

    assert shortcuts.keys_for("win.print") == ["<Control>p"]
