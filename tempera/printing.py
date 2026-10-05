# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Printing the image: how it is laid out on paper, and the dialog that asks how.

Tempera asks its own questions first, with a preview, and only then opens the
system's print dialog. Inside the Flatpak that dialog belongs to the desktop,
which can show neither an app's own options nor a preview of what it prints.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import cairo
from gi.repository import Adw, GLib, Gtk

from . import interface_size
from .document import copy_surface
from .i18n import _, ngettext
from .settings import config_dir

FIT = "fit"
ACTUAL = "actual"
SIZES = (FIT, ACTUAL)
DEFAULT_SIZE = FIT

POINTS_PER_INCH = 72
# Images carry no resolution Tempera keeps, so actual size is the size they
# have on a screen at 100%.
PIXELS_PER_INCH = 96

PORTRAIT = Gtk.PageOrientation.PORTRAIT
LANDSCAPE = Gtk.PageOrientation.LANDSCAPE

# The length of the page preview's longer side, at the default interface size.
PREVIEW_SIZE = 240

_SETTINGS_GROUP = "Print Settings"

# Prints still between their dialog and the printer, kept alive until done.
_running: set[Gtk.PrintOperation] = set()


@dataclass(frozen=True)
class Layout:
    """Where the image goes on a printable area of the given size, in points."""

    scale: float  # points per image pixel
    x: float
    y: float
    columns: int = 1
    rows: int = 1

    @property
    def pages(self) -> int:
        return self.columns * self.rows


def layout(
    image_width: int, image_height: int, area_width: float, area_height: float, size: str
) -> Layout:
    """Fit the image to one page, or print it at its actual size over as many as it needs."""
    if size == ACTUAL:
        scale = POINTS_PER_INCH / PIXELS_PER_INCH
        width, height = image_width * scale, image_height * scale
        # A sliver of a point over is rounding, not another page.
        columns = max(1, math.ceil(width / area_width - 1e-6))
        rows = max(1, math.ceil(height / area_height - 1e-6))
        if columns == rows == 1:
            return Layout(scale, (area_width - width) / 2, (area_height - height) / 2)
        # Spread over pages from the top left, so they can be laid side by side.
        return Layout(scale, 0.0, 0.0, columns, rows)
    scale = min(area_width / image_width, area_height / image_height)
    return Layout(
        scale,
        (area_width - image_width * scale) / 2,
        (area_height - image_height * scale) / 2,
    )


def draw_page(
    cr: cairo.Context,
    surface: cairo.ImageSurface,
    placement: Layout,
    page: int,
    area_width: float,
    area_height: float,
) -> None:
    """Draw one page's share of the image; pages run along each row, then down."""
    column, row = page % placement.columns, page // placement.columns
    cr.save()
    cr.rectangle(0, 0, area_width, area_height)
    cr.clip()
    cr.translate(placement.x - column * area_width, placement.y - row * area_height)
    cr.scale(placement.scale, placement.scale)
    pattern = cairo.SurfacePattern(surface)
    # Enlarged, each pixel stays a crisp square, as it looks zoomed in.
    enlarged = placement.scale > POINTS_PER_INCH / PIXELS_PER_INCH + 1e-9
    pattern.set_filter(cairo.FILTER_NEAREST if enlarged else cairo.FILTER_GOOD)
    cr.set_source(pattern)
    cr.rectangle(0, 0, surface.get_width(), surface.get_height())
    cr.fill()
    cr.restore()


def orientation_for(width: int, height: int) -> Gtk.PageOrientation:
    return LANDSCAPE if width > height else PORTRAIT


# Paper and printer, remembered from one print to the next


def _print_setup_path() -> Path:
    return config_dir() / "print-settings.ini"


def load_print_settings() -> Gtk.PrintSettings | None:
    key_file = GLib.KeyFile()
    try:
        key_file.load_from_file(str(_print_setup_path()), GLib.KeyFileFlags.NONE)
        return Gtk.PrintSettings.new_from_key_file(key_file, _SETTINGS_GROUP)
    except GLib.Error:
        return None


def save_print_settings(print_settings: Gtk.PrintSettings) -> None:
    key_file = GLib.KeyFile()
    print_settings.to_key_file(key_file, _SETTINGS_GROUP)
    path = _print_setup_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        key_file.save_to_file(str(path))
    except (OSError, GLib.Error):
        pass


def page_setup_for(print_settings: Gtk.PrintSettings | None, orientation) -> Gtk.PageSetup:
    """The paper last printed on, or the local default, turned the given way."""
    page_setup = Gtk.PageSetup()
    paper = print_settings.get_paper_size() if print_settings is not None else None
    if paper is not None:
        page_setup.set_paper_size_and_default_margins(paper)
    page_setup.set_orientation(orientation)
    return page_setup


# Handing it to the printer


class PrintJob:
    """One image on its way to the printer, as it was when Print was chosen."""

    def __init__(self, surface: cairo.ImageSurface, title: str, size: str, orientation):
        # Copied, so drawing on while the print dialog is open changes nothing.
        self.surface = copy_surface(surface)
        self.title = title
        self.size = size
        self.orientation = orientation

    def operation(self, print_settings: Gtk.PrintSettings | None = None) -> Gtk.PrintOperation:
        operation = Gtk.PrintOperation(job_name=self.title, unit=Gtk.Unit.POINTS)
        operation.set_embed_page_setup(True)
        if print_settings is not None:
            print_settings = print_settings.copy()
            print_settings.set_orientation(self.orientation)
            operation.set_print_settings(print_settings)
        operation.set_default_page_setup(page_setup_for(print_settings, self.orientation))
        operation.connect("begin-print", self._on_begin_print)
        operation.connect("draw-page", self._on_draw_page)
        return operation

    def _layout_for(self, context: Gtk.PrintContext) -> Layout:
        return layout(
            self.surface.get_width(),
            self.surface.get_height(),
            context.get_width(),
            context.get_height(),
            self.size,
        )

    def _on_begin_print(self, operation: Gtk.PrintOperation, context: Gtk.PrintContext) -> None:
        # The paper is only known now, once the print dialog has been answered.
        operation.set_n_pages(self._layout_for(context).pages)

    def _on_draw_page(self, _operation, context: Gtk.PrintContext, page: int) -> None:
        draw_page(
            context.get_cairo_context(),
            self.surface,
            self._layout_for(context),
            page,
            context.get_width(),
            context.get_height(),
        )


def print_image(
    parent: Gtk.Window,
    job: PrintJob,
    on_error: Callable[[str], None],
) -> None:
    """Open the system's print dialog for the job, and print it if the user goes ahead."""
    operation = job.operation(load_print_settings())
    operation.set_allow_async(True)

    def on_done(operation: Gtk.PrintOperation, result: Gtk.PrintOperationResult) -> None:
        _running.discard(operation)
        if result == Gtk.PrintOperationResult.APPLY:
            save_print_settings(operation.get_print_settings())
        elif result == Gtk.PrintOperationResult.ERROR:
            try:
                operation.get_error()
            except GLib.Error as error:
                on_error(error.message)

    operation.connect("done", on_done)
    _running.add(operation)
    try:
        operation.run(Gtk.PrintOperationAction.PRINT_DIALOG, parent)
    except GLib.Error as error:
        _running.discard(operation)
        on_error(error.message)


# Tempera's own questions


def _linked_toggles(labels: list[str], active: int) -> tuple[Gtk.Box, list[Gtk.ToggleButton]]:
    box = Gtk.Box(halign=Gtk.Align.CENTER)
    box.add_css_class("linked")
    buttons = []
    for index, label in enumerate(labels):
        button = Gtk.ToggleButton(label=label, active=index == active)
        if buttons:
            button.set_group(buttons[0])
        box.append(button)
        buttons.append(button)
    return box, buttons


class PrintDialog(Adw.AlertDialog):
    """How to put the image on paper, with a preview of the first page."""

    def __init__(
        self, surface: cairo.ImageSurface, size: str, on_print: Callable[[str, object], None]
    ):
        super().__init__(heading=_("Print Image"))
        self._surface = surface
        self._on_print = on_print
        self._print_settings = load_print_settings()

        self.preview = Gtk.DrawingArea(halign=Gtk.Align.CENTER)
        self.preview.set_draw_func(self._draw_preview)
        self.preview.update_property(
            [Gtk.AccessibleProperty.LABEL], [_("Preview of the printed page")]
        )

        size_box, self._size_buttons = _linked_toggles(
            [_("Fit to Page"), _("Actual Size")],
            SIZES.index(size if size in SIZES else DEFAULT_SIZE),
        )
        landscape = orientation_for(surface.get_width(), surface.get_height()) == LANDSCAPE
        orientation_box, self._orientation_buttons = _linked_toggles(
            [_("Portrait"), _("Landscape")], 1 if landscape else 0
        )
        for button in self._size_buttons + self._orientation_buttons:
            button.connect("toggled", self._on_option_toggled)

        self.pages_label = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.pages_label.add_css_class("dim-label")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12)
        box.append(self.preview)
        box.append(size_box)
        box.append(orientation_box)
        box.append(self.pages_label)
        self.set_extra_child(box)

        self.add_response("cancel", _("Cancel"))
        self.add_response("print", _("Print…"))
        self.set_response_appearance("print", Adw.ResponseAppearance.SUGGESTED)
        self.set_default_response("print")
        self.set_close_response("cancel")
        self.connect("response", self._on_response)
        self._sync_pages()

    @property
    def size(self) -> str:
        return SIZES[next(i for i, button in enumerate(self._size_buttons) if button.get_active())]

    @property
    def orientation(self):
        return LANDSCAPE if self._orientation_buttons[1].get_active() else PORTRAIT

    def set_size(self, size: str) -> None:
        self._size_buttons[SIZES.index(size)].set_active(True)

    def set_orientation(self, orientation) -> None:
        self._orientation_buttons[1 if orientation == LANDSCAPE else 0].set_active(True)

    def page_setup(self) -> Gtk.PageSetup:
        return page_setup_for(self._print_settings, self.orientation)

    def page_layout(self) -> Layout:
        page_setup = self.page_setup()
        return layout(
            self._surface.get_width(),
            self._surface.get_height(),
            page_setup.get_page_width(Gtk.Unit.POINTS),
            page_setup.get_page_height(Gtk.Unit.POINTS),
            self.size,
        )

    def _on_option_toggled(self, button: Gtk.ToggleButton) -> None:
        # Each change toggles one button off and another on; act once.
        if button.get_active():
            self._sync_pages()
            self.preview.queue_draw()

    def _sync_pages(self) -> None:
        # The preview takes the shape of the paper, its longer side a set length.
        page_setup = self.page_setup()
        paper_width = page_setup.get_paper_width(Gtk.Unit.POINTS)
        paper_height = page_setup.get_paper_height(Gtk.Unit.POINTS)
        longest = interface_size.scaled(PREVIEW_SIZE)
        scale = longest / max(paper_width, paper_height)
        self.preview.set_content_width(round(paper_width * scale))
        self.preview.set_content_height(round(paper_height * scale))

        pages = self.page_layout().pages
        if pages > 1:
            # Translators: shown when an image printed at its actual size does not fit one page.
            self.pages_label.set_label(
                ngettext(
                    "Too big for one page: prints on {count} page",
                    "Too big for one page: prints on {count} pages",
                    pages,
                ).format(count=pages)
            )
        else:
            self.pages_label.set_label("")
        self.pages_label.set_visible(pages > 1)

    def _draw_preview(self, _area, cr: cairo.Context, width: int, height: int) -> None:
        page_setup = self.page_setup()
        paper_width = page_setup.get_paper_width(Gtk.Unit.POINTS)
        paper_height = page_setup.get_paper_height(Gtk.Unit.POINTS)
        # A pixel in from each side, so the paper's edge is drawn whole.
        scale = min((width - 2) / paper_width, (height - 2) / paper_height)
        cr.translate((width - paper_width * scale) / 2, (height - paper_height * scale) / 2)
        cr.scale(scale, scale)

        cr.rectangle(0, 0, paper_width, paper_height)
        cr.set_source_rgb(1, 1, 1)
        cr.fill_preserve()
        cr.save()
        cr.identity_matrix()
        cr.set_line_width(1)
        cr.set_source_rgba(0, 0, 0, 0.3)
        cr.stroke()
        cr.restore()

        cr.translate(
            page_setup.get_left_margin(Gtk.Unit.POINTS), page_setup.get_top_margin(Gtk.Unit.POINTS)
        )
        draw_page(
            cr,
            self._surface,
            self.page_layout(),
            0,
            page_setup.get_page_width(Gtk.Unit.POINTS),
            page_setup.get_page_height(Gtk.Unit.POINTS),
        )

    def _on_response(self, _dialog, response: str) -> None:
        if response == "print":
            self._on_print(self.size, self.orientation)
