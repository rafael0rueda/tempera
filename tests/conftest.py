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
