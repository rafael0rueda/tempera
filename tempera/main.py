# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, VERSION, interface_size, recovery  # noqa: E402
from .file_io import load_document  # noqa: E402
from .openraster import OpenRasterError  # noqa: E402
from .i18n import _
from .recent_files import remember_recent  # noqa: E402
from .settings import load_setting, migrate_old_config  # noqa: E402
from .window import TemperaWindow  # noqa: E402


WEBSITE = "https://github.com/rafael0rueda/tempera"
ISSUES = WEBSITE + "/issues"


def metainfo_path(directory: Path | None = None) -> Path | None:
    """The AppStream metainfo, next to the data in a source tree or in share/metainfo installed."""
    directory = data_dir() if directory is None else directory
    if directory is None:
        return None
    name = f"{APP_ID}.metainfo.xml"
    # Installed, next to the data; or, running from the source tree, the
    # template the translated one is built from.
    for candidate in (
        directory / name,
        directory.parent / "metainfo" / name,
        directory / (name + ".in"),
    ):
        if candidate.is_file():
            return candidate
    return None


def release_notes(path: Path | None) -> tuple[str, str] | None:
    """(version, notes) for the newest release in the metainfo, for the About dialog.

    The notes are the release's description, which is already the small subset
    of markup (paragraphs and lists) the dialog understands.
    """
    if path is None:
        return None
    try:
        release = ElementTree.parse(path).getroot().find("releases/release")
    except (OSError, ElementTree.ParseError):
        return None
    if release is None:
        return None
    description = release.find("description")
    notes = "" if description is None else "".join(
        ElementTree.tostring(child, encoding="unicode") for child in description
    )
    return release.get("version", ""), notes


def data_dir() -> Path | None:
    """Find the app's data directory, whether running from source or installed."""
    candidates = []
    if "TEMPERA_DATA_DIR" in os.environ:
        candidates.append(Path(os.environ["TEMPERA_DATA_DIR"]))
    candidates.append(Path(__file__).resolve().parent.parent / "data")
    candidates += [Path(d) / "tempera" for d in GLib.get_system_data_dirs()]
    return next((path for path in candidates if path.is_dir()), None)


class TemperaApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        # Work left by a crash is offered once, when the first window opens.
        self._recovery_checked = False

    def do_startup(self):
        Adw.Application.do_startup(self)
        migrate_old_config()
        self._load_resources()
        interface_size.apply(interface_size.parse(load_setting("interface-size")))

        for name, callback in (("quit", self._on_quit), ("about", self._on_about)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)

    def do_activate(self):
        window = self.props.active_window or TemperaWindow(self)
        window.present()
        self._offer_recovery(window)

    def do_open(self, files, n_files, hint):
        error_message = None
        try:
            document = load_document(files[0])
        except GLib.Error as error:
            error_message = error.message
            document = None
        else:
            remember_recent(files[0])
        window = TemperaWindow(self, document)
        window.present()
        self._offer_recovery(window)
        if error_message is not None:
            print(f"tempera: could not open image: {error_message}", file=sys.stderr)
            window.show_toast(
                _("Could not open image: {message}").format(message=error_message)
            )

    def _offer_recovery(self, window: TemperaWindow) -> None:
        if self._recovery_checked:
            return
        self._recovery_checked = True
        self._offer_next(window, recovery.find_leftovers())

    def _offer_next(self, window: TemperaWindow, leftovers: list[recovery.Leftover]) -> None:
        """Ask about each image a crash left unsaved, one at a time, newest first."""
        if not leftovers:
            return
        leftover = leftovers.pop(0)
        when = GLib.DateTime.new_from_unix_local(int(leftover.saved_at)).format("%c")
        dialog = Adw.AlertDialog(
            heading=_("Recover Unsaved Image?"),
            body=_(
                "Tempera stopped before the changes to “{title}” were saved. "
                "A copy from {time} was kept."
            ).format(title=leftover.title, time=when),
        )
        dialog.add_response("later", _("Decide Later"))
        dialog.add_response("discard", _("Discard"))
        dialog.add_response("recover", _("Recover"))
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("recover", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("recover")
        dialog.set_close_response("later")

        def on_response(_dialog, response: str) -> None:
            target = window
            if response == "recover":
                target = self._recover(window, leftover)
            elif response == "discard":
                leftover.discard()
            else:
                leftover.release()
            self._offer_next(target, leftovers)

        dialog.connect("response", on_response)
        dialog.present(window)

    def _recover(self, window: TemperaWindow, leftover: recovery.Leftover) -> TemperaWindow:
        """Open a recovered image, as unsaved changes to the file it came from."""
        try:
            document = leftover.load()
        except (cairo.Error, MemoryError, OSError, OpenRasterError) as error:
            # Kept for next time rather than lost.
            leftover.release()
            window.show_toast(
                _("Could not recover “{title}”: {message}").format(
                    title=leftover.title, message=str(error)
                )
            )
            return window
        if leftover.uri is not None:
            document.file = Gio.File.new_for_uri(leftover.uri)
        document.modified = True
        if not window.is_untouched():
            window = TemperaWindow(self)
            window.present()
        window.show_recovered(document)
        # The window has its own copy now.
        leftover.discard()
        return window

    def _load_resources(self) -> None:
        directory = data_dir()
        if directory is None:
            return

        display = Gdk.Display.get_default()
        if display is None:
            return

        icons = directory / "icons"
        if icons.is_dir():
            Gtk.IconTheme.get_for_display(display).add_search_path(str(icons))

        stylesheet = directory / "style.css"
        if stylesheet.is_file():
            provider = Gtk.CssProvider()
            provider.load_from_string(stylesheet.read_text())
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _on_quit(self, *_args):
        # Each window asks about its own unsaved changes; the application ends
        # once the last one has gone.
        windows = self.get_windows()
        if not windows:
            self.quit()
        for window in windows:
            window.close()

    def _on_about(self, *_args):
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=VERSION,
            developer_name="Rafael Rueda",
            copyright="© 2026 Rafael Rueda",
            comments=_("A simple, offline raster paint app for the GNOME desktop."),
            website=WEBSITE,
            issue_url=ISSUES,
            license_type=Gtk.License.GPL_3_0,
        )
        notes = release_notes(metainfo_path())
        if notes is not None and notes[0] == VERSION:
            about.set_release_notes_version(notes[0])
            about.set_release_notes(notes[1])
        about.present(self.props.active_window)


def main() -> int:
    return TemperaApplication().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
