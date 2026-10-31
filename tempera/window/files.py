# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Opening, saving and printing, and the recent files."""

from __future__ import annotations

import weakref

from gi.repository import Adw, Gio, GLib, Gtk

from .. import interface_size, printing
from ..document import Document
from ..i18n import _
from ..file_io import (
    LAYERED_FORMAT,
    QUALITY_FORMATS,
    export_name,
    format_for,
    format_of_filter,
    image_filters,
    load_document_async,
    save_as_name,
    save_document_async,
    with_default_extension,
)
from ..openraster import BLENDING, GROUPS, OVERHANG
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
            heading=_("Save Changes?"),
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
            self._open_file(file)

        dialog.open(self, None, on_done)

    def _open_file(self, file: Gio.File, on_error=None) -> None:
        """Read an image in the background and show it, or say why it could not be."""
        heading = _("Could Not Open “{name}”").format(name=file.get_basename())
        self._set_busy(True)
        # Left alone until the file is read: what is drawn while waiting would
        # go with the picture it replaces.
        self.canvas.frozen = True

        def on_document(document: Document) -> None:
            self._set_busy(False)
            self.canvas.frozen = False
            self._set_document(document)
            self._remember_recent(file)
            self._say_what_was_lost(document)

        def on_error_message(message: str) -> None:
            self._set_busy(False)
            self.canvas.frozen = False
            self.show_failure(heading, message)
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

            self._open_file(file, forget)

        self._confirm_discard(proceed)

    def _say_what_was_lost(self, document: Document) -> None:
        """Say that a file from another program holds more than Tempera shows."""
        if not document.lost:
            return
        names = {
            BLENDING: _("how its layers blend"),
            GROUPS: _("its groups of layers"),
            OVERHANG: _("what lies beyond the edge of the canvas"),
        }
        parts = [names[each] for each in document.lost if each in names]
        self.show_toast(
            # Translators: {parts} is a list such as "how its layers blend, its groups of layers".
            _("Opened without {parts}; saving asks for a new name, to keep the original").format(
                parts=", ".join(parts)
            )
        )

    def _save(self, then=None) -> None:
        if self._busy:
            return
        # What gets written should match what is on screen.
        self.canvas.commit_floating()
        document = self.canvas.document
        if document.file is None or format_for(document.file) is None or document.lost:
            # Never saved, or opened from a format such as GIF that Tempera
            # cannot write back, or from a file holding more than Tempera
            # shows: ask where, rather than overwrite it.
            self._save_as(then)
            return
        # Ctrl+S keeps the quality already chosen; only Save As asks for it.
        self._write(document.file, then, self._last_quality(format_for(document.file)))

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

    def _save_as(self, then=None, keep_layers: bool = False) -> None:
        """Ask where to save. To `keep_layers`, only the OpenRaster files are shown."""
        if self._busy:
            return
        self.canvas.commit_floating()
        document = self.canvas.document
        layered = len(document.layers) > 1

        def on_chosen(chosen: Gio.File, chosen_format: str | None) -> None:
            file = with_default_extension(chosen, layered, chosen_format)
            if not file.equal(chosen) and file.query_exists(None):
                # The dialog only asked about replacing the name as typed.
                self._confirm_replace(file, lambda: self._write(file, then))
            else:
                self._write(file, then)

        self._ask_where_to_save(
            _("Save Image"),
            image_filters(layered_only=keep_layers, saving=True),
            None,
            save_as_name(document.file, layered),
            on_chosen,
        )

    def _ask_where_to_save(self, title: str, filters, folder, name: str, on_chosen) -> None:
        """Ask for a file to save to, and tell `on_chosen` the file and the format
        picked in the dialog, if it picked one.

        The older dialog on purpose: Gtk.FileDialog never says which filter was
        picked, so choosing "JPEG image" could not make a JPEG.
        """
        dialog = Gtk.FileChooserNative.new(title, self, Gtk.FileChooserAction.SAVE, None, None)
        dialog.set_modal(True)
        for index in range(filters.get_n_items()):
            dialog.add_filter(filters.get_item(index))
        if folder is not None:
            try:
                dialog.set_current_folder(folder)
            except GLib.Error:
                # A folder that has gone: the dialog starts somewhere else.
                pass
        dialog.set_current_name(name)

        def on_response(dialog, response: int) -> None:
            self._save_chooser = None
            if response == Gtk.ResponseType.ACCEPT:
                on_chosen(dialog.get_file(), format_of_filter(dialog.get_filter()))
            dialog.destroy()

        dialog.connect("response", on_response)
        # Nothing else holds on to it while it shows.
        self._save_chooser = dialog
        dialog.show()

    def _export_as(self) -> None:
        """Write a copy, in any format, of the picture as it shows.

        Unlike Save As, the picture keeps its own file, the one Ctrl+S goes
        on saving to, and its layers: a copy as a PNG or a JPEG can be made
        of a picture kept as OpenRaster, as often as it changes.
        """
        if self._busy:
            return
        self.canvas.commit_floating()
        document = self.canvas.document
        folder, name = self._export_start(document)

        def on_chosen(chosen: Gio.File, chosen_format: str | None) -> None:
            file = with_default_extension(chosen, chosen_format=chosen_format)
            if not file.equal(chosen) and file.query_exists(None):
                self._confirm_replace(file, lambda: self._export(file))
            else:
                self._export(file)

        self._ask_where_to_save(
            _("Export Image"), image_filters(saving=True), folder, name, on_chosen
        )

    def _export_start(self, document: Document) -> tuple[Gio.File | None, str]:
        """Where Export As starts: where this picture was last exported to, or else
        beside its own file, named after it."""
        last = self._last_export
        if last is not None and last[0]() is document:
            return last[1].get_parent(), last[1].get_basename()
        folder = document.file.get_parent() if document.file is not None else None
        return folder, export_name(document.file)

    def _export(self, file: Gio.File) -> None:
        image_format = format_for(file)
        if image_format in QUALITY_FORMATS:
            self._prompt_quality(
                image_format, lambda quality: self._export_now(file, quality), _("Export")
            )
        else:
            self._export_now(file, None)

    def _export_now(self, file: Gio.File, quality: int | None) -> None:
        self._set_busy(True)
        document = self.canvas.document

        def on_exported() -> None:
            self._set_busy(False)
            # Only for as long as the picture is open: it is not kept alive for this.
            self._last_export = (weakref.ref(document), file)
            self.show_toast(_("Exported {name}").format(name=file.get_basename()))

        def on_error(message: str) -> None:
            self._set_busy(False)
            self.show_failure(
                _("Could Not Export “{name}”").format(name=file.get_basename()), message
            )

        arguments = {} if quality is None else {"quality": quality}
        save_document_async(document, file, on_exported, on_error, copy=True, **arguments)

    def _confirm_replace(self, file: Gio.File, proceed) -> None:
        self.ask(
            _("Replace “{name}”?").format(name=file.get_basename()),
            _("A file with this name already exists. Saving will overwrite it."),
            "replace",
            _("Replace"),
            proceed,
            destructive=True,
        )

    def _write(self, file: Gio.File, then=None, quality: int | None = None) -> None:
        """Save to a file, first asking what has to be asked: whether to go without
        the layers, and, unless a `quality` is given, how good a file to make."""
        document = self.canvas.document
        flat = len(document.layers) > 1 and format_for(file) != LAYERED_FORMAT
        agreed = self._flat_agreed is not None and self._flat_agreed() is document
        if flat and not agreed:
            self._confirm_flat(file, lambda: self._write(file, then, quality), then)
        elif format_for(file) in QUALITY_FORMATS and quality is None:
            self._prompt_quality(
                format_for(file), lambda quality: self._write_now(file, then, quality)
            )
        else:
            self._write_now(file, then, quality)

    def _confirm_flat(self, file: Gio.File, proceed, then) -> None:
        """Ask before a picture's layers are left out of its file: once for each picture."""
        document = self.canvas.document
        dialog = Adw.AlertDialog(
            heading=_("Save Without Layers?"),
            body=_(
                "“{name}” cannot hold layers: it will get the picture as it shows, "
                "all {count} layers merged into one. An OpenRaster file keeps them."
            ).format(name=file.get_basename(), count=len(document.layers)),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("openraster", _("Save as OpenRaster…"))
        dialog.add_response("flat", _("Save Flattened"))
        dialog.set_response_appearance("openraster", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("openraster")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == "flat":
                self._flat_agreed = weakref.ref(document)
                proceed()
            elif response == "openraster":
                self._save_as(then, keep_layers=True)

        dialog.connect("response", on_response)
        dialog.present(self)

    def _last_quality(self, image_format: str | None) -> int:
        return self._last_jxl_quality if image_format == "jxl" else self._last_jpeg_quality

    def _prompt_quality(self, image_format: str, on_accept, accept_label: str | None = None) -> None:
        jxl = image_format == "jxl"
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        scale.set_value(self._last_quality(image_format))
        scale.set_draw_value(True)
        scale.set_hexpand(True)
        scale.set_size_request(interface_size.scaled(220), -1)
        scale.update_property([Gtk.AccessibleProperty.LABEL], [_("JPEG XL quality") if jxl else _("JPEG quality")])

        def accept() -> None:
            quality = int(scale.get_value())
            if jxl:
                self._last_jxl_quality = quality
            else:
                self._last_jpeg_quality = quality
            on_accept(quality)

        self.ask(
            _("JPEG XL Quality") if jxl else _("JPEG Quality"),
            _("Lower values make a smaller file but lose more detail. At 100, no detail is lost.")
            if jxl
            else _("Lower values make a smaller file but lose more detail."),
            "save",
            accept_label or _("Save"),
            accept,
            extra=scale,
        )

    def _write_now(self, file: Gio.File, then, quality: int | None) -> None:
        self._set_busy(True)
        document = self.canvas.document

        def on_saved() -> None:
            self._set_busy(False)
            # The file is Tempera's own now, with nothing in it Tempera cannot keep.
            document.lost = ()
            self.show_toast(_("Saved {name}").format(name=file.get_basename()))
            self._remember_recent(file)
            if then is not None:
                then()

        def on_error(message: str) -> None:
            self._set_busy(False)
            self.show_failure(
                _("Could Not Save “{name}”").format(name=file.get_basename()),
                message,
                save_as=True,
            )

        arguments = {} if quality is None else {"quality": quality}
        save_document_async(self.canvas.document, file, on_saved, on_error, **arguments)
