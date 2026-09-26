# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Opening, saving and printing, and the recent files."""

from __future__ import annotations

from gi.repository import Adw, Gio, GLib, Gtk

from .. import printing
from ..document import Document
from ..i18n import _
from ..file_io import (
    format_for,
    image_filters,
    load_document_async,
    save_as_name,
    save_document_async,
    with_default_extension,
)
from ..recent_files import clear_recent, forget_recent, load_recent, remember_recent
from ..settings import load_setting, save_settings


class FilesMixin:
    """Opening, saving and printing images, and the recent files menu."""

    def _confirm_discard(self, proceed) -> None:
        # A paste or text still floating counts as a change, but is not landed
        # yet: Cancel has to leave the image exactly as it was.
        document = self.canvas.document
        if not document.modified and not self.canvas.has_pending_floating:
            proceed()
            return

        dialog = Adw.AlertDialog(
            heading=_("Save changes?"),
            body=_("“{name}” has unsaved changes.").format(name=document.title),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("discard", _("Discard"))
        dialog.add_response("save", _("Save"))
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == "discard":
                proceed()
            elif response == "save":
                self._save(proceed)

        dialog.connect("response", on_response)
        dialog.present(self)

    def _action_open(self, *_args) -> None:
        self._confirm_discard(self._show_open_dialog)

    def _show_open_dialog(self) -> None:
        if self._busy:
            return
        dialog = Gtk.FileDialog(title=_("Open Image"), filters=image_filters())

        def on_done(source, result):
            try:
                file = source.open_finish(result)
            except GLib.Error:
                return
            self._open_file(file, _("Could not open image: {message}"))

        dialog.open(self, None, on_done)

    def _open_file(self, file: Gio.File, error_format: str, on_error=None) -> None:
        """Read an image in the background and show it, or say why it could not be."""
        self._set_busy(True)

        def on_document(document: Document) -> None:
            self._set_busy(False)
            self._set_document(document)
            self._remember_recent(file)

        def on_error_message(message: str) -> None:
            self._set_busy(False)
            self.show_toast(error_format.format(message=message))
            if on_error is not None:
                on_error()

        load_document_async(file, on_document, on_error_message)

    def _refresh_recent_menu(self) -> None:
        self._recent_menu.remove_all()
        recent = load_recent()
        if not recent:
            self._recent_menu.append(_("No Recent Files"), None)
            return
        files = Gio.Menu()
        for uri in recent:
            item = Gio.MenuItem.new(Gio.File.new_for_uri(uri).get_basename(), None)
            item.set_action_and_target_value("win.open-recent", GLib.Variant.new_string(uri))
            files.append_item(item)
        self._recent_menu.append_section(None, files)
        clearing = Gio.Menu()
        clearing.append(_("Clear Recent Files"), "win.clear-recent")
        self._recent_menu.append_section(None, clearing)

    def _clear_recent(self) -> None:
        clear_recent()
        self._refresh_recent_menu()
        self.show_toast(_("Cleared the recent files"))

    def _remember_recent(self, file: Gio.File) -> None:
        remember_recent(file)
        self._refresh_recent_menu()

    def _action_open_recent(self, action, param: GLib.Variant) -> None:
        uri = param.get_string()

        def proceed():
            file = Gio.File.new_for_uri(uri)

            def forget():
                forget_recent(uri)
                self._refresh_recent_menu()

            self._open_file(
                file,
                _("Could not open “{name}”: {{message}}").format(name=file.get_basename()),
                forget,
            )

        self._confirm_discard(proceed)

    def _save(self, then=None) -> None:
        if self._busy:
            return
        # What gets written should match what is on screen.
        self.canvas.commit_floating()
        document = self.canvas.document
        if document.file is None or format_for(document.file) is None:
            # Never saved, or opened from a format such as GIF that Tempera
            # cannot write back: ask where, rather than overwrite it as PNG.
            self._save_as(then)
            return
        # Ctrl+S keeps the quality already chosen; only Save As asks for it.
        self._write_now(document.file, then, self._last_jpeg_quality)

    def _print(self) -> None:
        # What gets printed should match what is on screen.
        self.canvas.commit_floating()
        document = self.canvas.document

        # The picture as it shows, every visible layer blended.
        picture = document.flattened()

        def on_print(size: str, orientation) -> None:
            save_settings({"print-size": size})
            job = printing.PrintJob(picture, document.title, size, orientation)

            def on_error(message: str) -> None:
                self.show_toast(_("Could not print: {message}").format(message=message))

            printing.print_image(self, job, on_error)

        printing.PrintDialog(
            picture, load_setting("print-size", printing.DEFAULT_SIZE), on_print
        ).present(self)

    def _save_as(self, then=None) -> None:
        if self._busy:
            return
        self.canvas.commit_floating()
        document = self.canvas.document
        dialog = Gtk.FileDialog(title=_("Save Image"), filters=image_filters())
        if document.file is None:
            dialog.set_initial_name("Untitled.png")
        else:
            dialog.set_initial_name(save_as_name(document.file))

        def on_done(source, result):
            try:
                chosen = source.save_finish(result)
            except GLib.Error:
                return
            file = with_default_extension(chosen)
            if not file.equal(chosen) and file.query_exists(None):
                # The dialog only asked about replacing the name as typed.
                self._confirm_replace(file, lambda: self._write(file, then))
            else:
                self._write(file, then)

        dialog.save(self, None, on_done)

    def _confirm_replace(self, file: Gio.File, proceed) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Replace “{name}”?").format(name=file.get_basename()),
            body=_("A file with this name already exists. Saving will overwrite it."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("replace", _("Replace"))
        dialog.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == "replace":
                proceed()

        dialog.connect("response", on_response)
        dialog.present(self)

    def _write(self, file: Gio.File, then=None) -> None:
        if format_for(file) == "jpeg":
            self._prompt_jpeg_quality(lambda quality: self._write_now(file, then, quality))
        else:
            self._write_now(file, then, None)

    def _prompt_jpeg_quality(self, on_accept) -> None:
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        scale.set_value(self._last_jpeg_quality)
        scale.set_draw_value(True)
        scale.set_hexpand(True)
        scale.set_size_request(220, -1)

        dialog = Adw.AlertDialog(
            heading=_("JPEG Quality"),
            body=_("Lower values make a smaller file but lose more detail."),
        )
        dialog.set_extra_child(scale)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save"))
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == "save":
                self._last_jpeg_quality = int(scale.get_value())
                on_accept(self._last_jpeg_quality)

        dialog.connect("response", on_response)
        dialog.present(self)

    def _write_now(self, file: Gio.File, then, quality: int | None) -> None:
        self._set_busy(True)

        def on_saved() -> None:
            self._set_busy(False)
            self.show_toast(_("Saved {name}").format(name=file.get_basename()))
            self._remember_recent(file)
            if then is not None:
                then()

        def on_error(message: str) -> None:
            self._set_busy(False)
            self.show_toast(_("Could not save image: {message}").format(message=message))

        arguments = {} if quality is None else {"quality": quality}
        save_document_async(self.canvas.document, file, on_saved, on_error, **arguments)
