# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gsk", "4.0")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def private_recovery_dir(monkeypatch, tmp_path):
    """Crash-recovery copies go to a folder of each test's own, never the real one."""
    from tempera import recovery

    directory = tmp_path / "recovery"
    monkeypatch.setattr(recovery, "recovery_dir", lambda: directory)
    return directory


@pytest.fixture(autouse=True)
def private_print_settings(monkeypatch, tmp_path):
    """The printer and paper last chosen are kept in each test's own file."""
    from tempera import printing

    path = tmp_path / "print-settings.ini"
    monkeypatch.setattr(printing, "_print_setup_path", lambda: path)
    return path


@pytest.fixture(autouse=True)
def private_settings(monkeypatch, tmp_path):
    """Settings and recent files are each test's own, never the ones in the home folder,
    and what a test leaves set for the whole process is put back."""
    from tempera import interface_size, recent_files, settings, shortcuts

    path = tmp_path / "settings.ini"
    monkeypatch.setattr(settings, "_settings_path", lambda: path)
    monkeypatch.setattr(recent_files, "_recent_file_path", lambda: tmp_path / "recent-files.txt")
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setattr(shortcuts, "_suspended", False)
    yield path
    if interface_size.current() != interface_size.DEFAULT_SIZE:
        interface_size.apply(interface_size.DEFAULT_SIZE)


@pytest.fixture(scope="module")
def application(request):
    """An application for a module's windows to belong to."""
    from gi.repository import Adw, Gio

    name = "".join(part.capitalize() for part in request.module.__name__.split("_"))
    app = Adw.Application(
        application_id=f"io.github.rafael0rueda.Tempera.{name}",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )
    # Windows can only be added once the application has started up.
    app.register(None)
    return app


@pytest.fixture
def window(application):
    from tempera.window import TemperaWindow

    window = TemperaWindow(application)
    yield window
    window.destroy()


@pytest.fixture(scope="session", autouse=True)
def app_resources():
    """Every test sees the canvas and the widgets styled as the app styles them,
    whichever tests ran before it."""
    from gi.repository import Adw

    from tempera.main import load_resources

    Adw.init()
    load_resources()
