# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The clipboard, undo, and turning the image."""

from __future__ import annotations

from gi.repository import Gdk, GLib

from ..clipboard import has_image, has_text, read_image, read_text, texture_from_surface
from ..i18n import _


class EditMixin:
    """Cut, copy, paste, undo, and rotating or flipping the whole image."""

    def _transform_image(self, apply) -> None:
        """Whatever floats or is selected does not survive a rotate or flip."""
        self.canvas.commit_floating()
        self.canvas.clear_selection()
        apply(self.canvas.document)

    def _sync_paste_action(self) -> None:
        clipboard = self.get_clipboard()
        # Text goes into the text box being typed in; anywhere else only a picture will do.
        self.lookup_action("paste").set_enabled(
            has_image(clipboard) or (self.canvas.is_typing and has_text(clipboard))
        )

    def _sync_selection_actions(self) -> None:
        # There is nothing to cut or crop to without a selection; pixels that
        # float over the picture count as one.
        selected = self.canvas.has_selection or self.canvas.has_floating_paste
        self.lookup_action("cut").set_enabled(selected)
        self.lookup_action("crop").set_enabled(selected)

    def _put_on_clipboard(self, surface) -> None:
        texture = texture_from_surface(surface)
        self.get_clipboard().set_content(Gdk.ContentProvider.new_for_value(texture))
        # The clipboard's own notification is asynchronous; do not wait for it.
        self._sync_paste_action()

    def _select_all(self) -> None:
        self.lookup_action("tool").change_state(GLib.Variant.new_string("select"))
        self.canvas.select_all()

    def _copy(self) -> None:
        floating = self.canvas.floating_pixels()
        if floating is not None:
            # It stays floating: copying is not a reason to put it down.
            self._put_on_clipboard(floating)
            self.show_toast(_("Copied the selection"))
            return
        self.canvas.commit_floating()
        # A selection narrows the copy down to itself; otherwise it is the canvas.
        selection = self.canvas.selection_surface()
        self._put_on_clipboard(selection or self.canvas.document.surface)
        document = self.canvas.document
        if selection:
            message = _("Copied the selection")
        elif len(document.layers) > 1:
            # Only what is on this layer, which the picture as it shows may not be.
            message = _("Copied the layer “{name}”").format(name=document.layer.name)
        else:
            message = _("Copied to clipboard")
        self.show_toast(message)

    def _cut(self) -> None:
        floating = self.canvas.floating_pixels()
        if floating is not None:
            self._put_on_clipboard(floating)
            self.canvas.discard_paste()
            self.show_toast(_("Cut the selection"))
            return
        self.canvas.commit_floating()
        selection = self.canvas.selection_surface()
        if selection is None:
            return
        self._put_on_clipboard(selection)
        self.canvas.delete_selection()
        self.show_toast(_("Cut the selection"))

    def _paste(self) -> None:
        clipboard = self.get_clipboard()
        if self.canvas.is_typing and has_text(clipboard):
            # Into the text box, at the caret, as anywhere else text is typed.
            read_text(clipboard, self.canvas.insert_text)
            return
        read_image(clipboard, self.canvas.begin_paste, self.show_toast)

    def _action_undo(self, *_args) -> None:
        # A paste or a text box has not been stamped down yet, so undo drops it.
        if not self.canvas.cancel_floating():
            self.canvas.document.undo()
