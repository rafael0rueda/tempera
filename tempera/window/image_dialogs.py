# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The dialogs that ask for a size: New Image, Canvas Size and Resize Image."""

from __future__ import annotations

from gi.repository import Adw, Gtk

from ..document import DEFAULT_HEIGHT, DEFAULT_WIDTH, MAX_SIZE, Document, new_surface
from ..i18n import _

WHITE = (1.0, 1.0, 1.0, 1.0)
TRANSPARENT = (0.0, 0.0, 0.0, 0.0)


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
            spins.append(spin)
        width_spin, height_spin = spins

        grid = Gtk.Grid(row_spacing=6, column_spacing=12, margin_top=12)
        grid.attach(Gtk.Label(label=_("Width"), xalign=1), 0, 0, 1, 1)
        grid.attach(width_spin, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label=_("Height"), xalign=1), 0, 1, 1, 1)
        grid.attach(height_spin, 1, 1, 1, 1)
        if extra is not None:
            grid.attach(extra, 0, 2, 2, 1)

        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.set_extra_child(grid)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response(accept_id, accept_label)
        dialog.set_response_appearance(accept_id, Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response(accept_id)
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == accept_id:
                on_accept(int(width_spin.get_value()), int(height_spin.get_value()))

        dialog.connect("response", on_response)
        dialog.present(self)

    def _prompt_new_size(self) -> None:
        transparent = Gtk.CheckButton(label=_("Transparent background"))
        transparent.set_tooltip_text(_("Start with nothing rather than white"))

        def create(width: int, height: int) -> None:
            fill = TRANSPARENT if transparent.get_active() else WHITE
            self._set_document(Document(new_surface(width, height, fill)))

        self._prompt_size(
            _("New image"),
            _("Choose a canvas size in pixels."),
            (DEFAULT_WIDTH, DEFAULT_HEIGHT),
            "create",
            _("Create"),
            create,
            extra=transparent,
        )

    def _prompt_canvas_size(self) -> None:
        self.canvas.commit_floating()
        document = self.canvas.document

        self._prompt_size(
            _("Canvas size"),
            _("The image keeps its top-left corner; extra space is filled with white."),
            (document.width, document.height),
            "resize",
            _("Resize"),
            document.resize,
        )

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
        grid.attach(Gtk.Label(label=_("Width"), xalign=1), 0, 0, 1, 1)
        grid.attach(width_spin, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label=_("Height"), xalign=1), 0, 1, 1, 1)
        grid.attach(height_spin, 1, 1, 1, 1)
        grid.attach(keep_ratio, 0, 2, 2, 1)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(units)
        content.append(grid)

        dialog = Adw.AlertDialog(
            heading=_("Resize image"),
            body=_("The whole picture is stretched or shrunk to the new size."),
        )
        dialog.set_extra_child(content)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("scale", _("Resize"))
        dialog.set_response_appearance("scale", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("scale")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response != "scale":
                return
            values = [spin.get_value() for spin in spins]
            if in_percent():
                values = [scaled_side(side, value) for side, value in zip(original, values)]
            document.scale(int(values[0]), int(values[1]))

        dialog.connect("response", on_response)
        dialog.present(self)
