# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The clipboard, undo, and turning the image."""

from __future__ import annotations

from gi.repository import Gdk, GLib

from ..clipboard import has_image, read_image, texture_from_surface
from ..i18n import _


class EditMixin:
    """Cut, copy, paste, undo, and rotating or flipping the whole image."""

    def _transform_image(self, apply) -> None:
        """Whatever floats or is selected does not survive a rotate or flip."""
        self.canvas.commit_floating()
        self.canvas.clear_selection()
        apply(self.canvas.document)

    def _sync_paste_action(self) -> None:
        self.lookup_action("paste").set_enabled(has_image(self.get_clipboard()))

    def _sync_selection_actions(self) -> None:
        # There is nothing to cut or crop to without a selection.
        self.lookup_action("cut").set_enabled(self.canvas.has_selection)
        self.lookup_action("crop").set_enabled(self.canvas.has_selection)

    def _put_on_clipboard(self, surface) -> None:
        texture = texture_from_surface(surface)
        self.get_clipboard().set_content(Gdk.ContentProvider.new_for_value(texture))
        # The clipboard's own notification is asynchronous; do not wait for it.
        self._sync_paste_action()

    def _select_all(self) -> None:
        self.lookup_action("tool").change_state(GLib.Variant.new_string("select"))
        self.canvas.select_all()

    def _copy(self) -> None:
        self.canvas.commit_floating()
        # A selection narrows the copy down to itself; otherwise it is the canvas.
        selection = self.canvas.selection_surface()
        self._put_on_clipboard(selection or self.canvas.document.surface)
        self.show_toast(_("Copied the selection") if selection else _("Copied to clipboard"))

    def _cut(self) -> None:
        self.canvas.commit_floating()
        selection = self.canvas.selection_surface()
        if selection is None:
            return
        self._put_on_clipboard(selection)
        self.canvas.delete_selection()
        self.show_toast(_("Cut the selection"))

    def _paste(self) -> None:
        read_image(self.get_clipboard(), self.canvas.begin_paste, self.show_toast)

    def _action_undo(self, *_args) -> None:
        # A paste or a text box has not been stamped down yet, so undo drops it.
        if not self.canvas.cancel_floating():
            self.canvas.document.undo()
