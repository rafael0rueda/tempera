# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The dialogs that ask for a size: New Image, Canvas Size and Resize Image."""

from __future__ import annotations

from gi.repository import Gtk

from ..canvas import too_large_message
from ..document import MAX_SIZE, TRANSPARENT, WHITE, Document, new_surface
from ..i18n import _



def scaled_side(original: int, percent: float) -> int:
    """One side of the image at a percentage of its size, within what a canvas can hold."""
    return max(1, min(round(original * percent / 100), MAX_SIZE))


class ImageDialogsMixin:
    """Asking for a new image's size, the canvas's, or the picture's."""

    def _action_new(self, *_args) -> None:
        self._confirm_discard(self._prompt_new_size)

    def _prompt_size(
        self, heading, body, size, accept_id, accept_label, on_accept, extra=None
    ) -> None:
        """Ask for a width/height pair, then hand it to on_accept."""
        spins = []
        for value in size:
            spin = Gtk.SpinButton.new_with_range(1, MAX_SIZE, 1)
            spin.set_value(value)
            # Wide enough for the largest allowed size in any interface font.
            spin.set_width_chars(len(str(MAX_SIZE)) + 1)
            # Enter in either field accepts the dialog.
            spin.set_activates_default(True)
            spins.append(spin)
        width_spin, height_spin = spins

        grid = Gtk.Grid(row_spacing=6, column_spacing=12, margin_top=12)
        for row, (caption, spin) in enumerate(((_("Width"), width_spin), (_("Height"), height_spin))):
            grid.attach(Gtk.Label(label=caption, xalign=1), 0, row, 1, 1)
            grid.attach(spin, 1, row, 1, 1)
            # Read out with the field, which on its own is only a number.
            spin.update_property([Gtk.AccessibleProperty.LABEL], [caption])
        if extra is not None:
            grid.attach(extra, 0, 2, 2, 1)

        self.ask(
            heading,
            body,
            accept_id,
            accept_label,
            lambda: on_accept(int(width_spin.get_value()), int(height_spin.get_value())),
            extra=grid,
        )

    def _prompt_new_size(self) -> None:
        last_width, last_height, last_transparent = self._new_image
        transparent = Gtk.CheckButton(label=_("Transparent background"), active=last_transparent)
        transparent.set_tooltip_text(_("Start with nothing rather than white"))

        def create(width: int, height: int) -> None:
            # Offered again the next time: the same size is often wanted twice.
            self._new_image = (width, height, transparent.get_active())
            fill = TRANSPARENT if transparent.get_active() else WHITE
            document = Document(new_surface(width, height, fill))
            # Where it later grows, it grows with the same.
            document.backdrop = fill
            self._set_document(document)

        self._prompt_size(
            _("New Image"),
            _("Choose a canvas size in pixels."),
            (last_width, last_height),
            "create",
            _("Create"),
            create,
            extra=transparent,
        )

    def _prompt_canvas_size(self) -> None:
        self.canvas.commit_floating()
        document = self.canvas.document

        self._prompt_size(
            _("Canvas Size"),
            _("The image keeps its top-left corner; extra space is left see-through.")
            if document.backdrop[3] == 0
            else _("The image keeps its top-left corner; extra space is filled with white."),
            (document.width, document.height),
            "resize",
            _("Resize"),
            lambda width, height: self._say_if_too_large(document, document.resize(width, height)),
        )

    def _say_if_too_large(self, document, fitted: bool) -> None:
        if not fitted:
            self.show_toast(too_large_message(len(document.layers)))

    def _prompt_scale_image(self) -> None:
        """Ask for a new size for the picture itself, in pixels or as a percentage."""
        self.canvas.commit_floating()
        self.canvas.clear_selection()
        document = self.canvas.document
        original = (document.width, document.height)

        pixels = Gtk.ToggleButton(label=_("Pixels"), active=True)
        percent = Gtk.ToggleButton(label=_("Percent"), group=pixels)
        units = Gtk.Box(halign=Gtk.Align.CENTER, margin_top=12)
        units.add_css_class("linked")
        units.append(pixels)
        units.append(percent)

        spins = [Gtk.SpinButton.new_with_range(1, MAX_SIZE, 1) for _side in original]
        width_spin, height_spin = spins
        for spin, side in zip(spins, original):
            spin.set_value(side)
            spin.set_width_chars(len(str(MAX_SIZE)) + 1)
            spin.set_activates_default(True)
        keep_ratio = Gtk.CheckButton(label=_("Keep aspect ratio"), active=True)

        syncing = False

        def in_percent() -> bool:
            return percent.get_active()

        def follow(changed: Gtk.SpinButton, other: Gtk.SpinButton, index: int) -> None:
            """Keep the other side in proportion while the ratio is locked."""
            nonlocal syncing
            if syncing or not keep_ratio.get_active():
                return
            syncing = True
            if in_percent():
                other.set_value(changed.get_value())
            else:
                other.set_value(
                    scaled_side(original[1 - index], changed.get_value() * 100 / original[index])
                )
            syncing = False

        width_spin.connect("value-changed", lambda spin: follow(spin, height_spin, 0))
        height_spin.connect("value-changed", lambda spin: follow(spin, width_spin, 1))

        def switch_units(*_args) -> None:
            nonlocal syncing
            syncing = True
            for spin, side in zip(spins, original):
                value = spin.get_value()
                if in_percent():
                    spin.set_range(1, 1000)
                    spin.set_value(round(value * 100 / side))
                else:
                    spin.set_range(1, MAX_SIZE)
                    spin.set_value(scaled_side(side, value))
            syncing = False

        percent.connect("toggled", switch_units)

        grid = Gtk.Grid(row_spacing=6, column_spacing=12, margin_top=12)
        for row, (caption, spin) in enumerate(((_("Width"), width_spin), (_("Height"), height_spin))):
            grid.attach(Gtk.Label(label=caption, xalign=1), 0, row, 1, 1)
            grid.attach(spin, 1, row, 1, 1)
            # Read out with the field, which on its own is only a number.
            spin.update_property([Gtk.AccessibleProperty.LABEL], [caption])
        grid.attach(keep_ratio, 0, 2, 2, 1)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(units)
        content.append(grid)

        def resize() -> None:
            values = [spin.get_value() for spin in spins]
            if in_percent():
                values = [scaled_side(side, value) for side, value in zip(original, values)]
            self._say_if_too_large(document, document.scale(int(values[0]), int(values[1])))

        self.ask(
            _("Resize Image"),
            _("The whole picture is stretched or shrunk to the new size."),
            "scale",
            _("Resize"),
            resize,
            extra=content,
        )
