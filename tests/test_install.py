# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tests import straight from the source tree, so a module left out of the
install list only shows up as a crash in the installed app. Catch it here."""

import json
import re
import subprocess
from pathlib import Path

import gi

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "tempera"


def test_every_module_is_installed():
    installed = set(re.findall(r"'([\w/]+\.py)'", (PACKAGE / "meson.build").read_text()))
    modules = {path.relative_to(PACKAGE).as_posix() for path in PACKAGE.rglob("*.py")}
    assert modules - installed == set()


def test_every_icon_is_shipped_or_built_into_gtk():
    """Buttons must not depend on the desktop's icon theme.

    Under Flatpak the host theme is often out of reach (one in ~/.icons, say),
    and GTK then only has the few icons compiled into it, so anything else
    renders as a broken-image placeholder.
    """
    from gi.repository import Gio, Gtk

    Gtk.init()
    built_in = {
        name.removesuffix(".svg")
        for name in Gio.resources_enumerate_children("/org/gtk/libgtk/icons/", 0)
    }
    shipped = {
        path.name.removesuffix(".svg")
        for path in (PACKAGE.parent / "data" / "icons").rglob("*.svg")
    }
    used = set()
    for path in PACKAGE.rglob("*.py"):
        used |= set(re.findall(r'"([\w-]+-symbolic)"', path.read_text()))

    assert used, "the icon names were not found at all"
    assert used - shipped - built_in == set()



def test_every_shipped_icon_draws_something():
    """GTK skips what it cannot render, such as a dot drawn as a zero-length stroke,
    and would show an empty button rather than complain."""
    gi.require_version("Gsk", "4.0")
    from gi.repository import Gdk, Gio, Gsk, Graphene, Gtk

    Gtk.init()
    display = Gdk.Display.get_default()
    renderer = Gsk.CairoRenderer()
    renderer.realize_for_display(display)
    empty = []
    try:
        for path in sorted((PACKAGE.parent / "data" / "icons").rglob("*-symbolic.svg")):
            icon = Gtk.IconPaintable.new_for_file(Gio.File.new_for_path(str(path)), 32, 1)
            snapshot = Gtk.Snapshot()
            color = Gdk.RGBA()
            color.parse("red")
            icon.snapshot_symbolic(snapshot, 32, 32, [color])
            node = snapshot.to_node()
            if node is None:
                empty.append(path.name)
                continue
            texture = renderer.render_texture(node, Graphene.Rect().init(0, 0, 32, 32))
            downloader = Gdk.TextureDownloader.new(texture)
            downloader.set_format(Gdk.MemoryFormat.R8G8B8A8)
            pixels, _stride = downloader.download_bytes()
            if not any(pixels.get_data()[3::4]):
                empty.append(path.name)
    finally:
        renderer.unrealize()
    assert empty == []


def test_icon_strokes_are_marked_for_gtk():
    """GTK recolours a symbolic icon by class, not by its fill and stroke attributes.

    Unmarked, a stroke is dropped and a path meant to be left open is filled in,
    so an outlined square draws as a solid one.
    """
    unmarked = []
    for path in sorted((PACKAGE.parent / "data" / "icons").rglob("*-symbolic.svg")):
        for element in re.findall(r"<(?:path|circle|rect|ellipse|line|polyline|polygon)\b[^>]*>", path.read_text()):
            classes = set(re.search(r'class="([^"]*)"', element).group(1).split()) if "class=" in element else set()
            if "stroke=" in element and "foreground-stroke" not in classes:
                unmarked.append(f"{path.name}: stroke without foreground-stroke")
            if 'fill="none"' in element and "transparent-fill" not in classes:
                unmarked.append(f"{path.name}: fill=none without transparent-fill")
    assert unmarked == []


def test_icons_carry_no_embedded_metadata():
    """Design tools embed provenance blocks many times the size of the drawing."""
    heavy = [
        path.name
        for path in (PACKAGE.parent / "data" / "icons").rglob("*-symbolic.svg")
        if "<metadata" in path.read_text()
    ]
    assert heavy == []


def test_nothing_is_still_called_hue():
    """The app was renamed from Hue; only the deliberate references to that remain."""
    allowed = {
        "tempera/settings.py": ['OLD_CONFIG_NAME = "hue"', "called Hue"],
        "data/io.github.rafael0rueda.Tempera.metainfo.xml.in": [
            "io.github.rafael0rueda.Hue",
            "called Hue",
            "Hue is now called Tempera",
            "carried over from Hue",
        ],
        "tests/test_install.py": None,
        "tests/test_settings.py": ["old_hue_settings"],
    }
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    leftovers = []
    for name in tracked:
        path = ROOT / name
        if name == "LICENSE" or path.suffix in {".png", ".svg"} or not path.is_file():
            continue
        if allowed.get(name, []) is None:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"hue", line, re.IGNORECASE) and not any(
                fragment in line for fragment in allowed.get(name, [])
            ):
                leftovers.append(f"{name}:{number}: {line.strip()}")
    assert leftovers == []


def test_the_desktop_file_opens_what_the_open_dialog_does():
    from tempera.file_io import OPEN_MIME_TYPES

    desktop = (ROOT / "data" / "io.github.rafael0rueda.Tempera.desktop.in").read_text(
        encoding="utf-8"
    )
    line = next(line for line in desktop.splitlines() if line.startswith("MimeType="))
    assert set(filter(None, line.removeprefix("MimeType=").split(";"))) == set(OPEN_MIME_TYPES)


def test_version_matches_meson_and_the_newest_release_notes():
    from tempera import VERSION
    from tempera.main import metainfo_path, release_notes

    meson = (ROOT / "meson.build").read_text(encoding="utf-8")
    assert f"version: '{VERSION}'" in meson
    version, notes = release_notes(metainfo_path(ROOT / "data"))
    assert version == VERSION
    assert notes.startswith("<p>")


def test_release_notes_of_a_missing_or_broken_metainfo_are_none(tmp_path):
    from tempera.main import release_notes

    broken = tmp_path / "broken.xml"
    broken.write_text("<component>", encoding="utf-8")
    assert release_notes(None) is None
    assert release_notes(tmp_path / "missing.xml") is None
    assert release_notes(broken) is None


def test_the_flatpak_asks_for_nothing_it_does_not_need():
    """The sandbox is the app's main defence: no network, no filesystem, no services."""
    manifest = json.loads(
        (ROOT / "flatpak" / "io.github.rafael0rueda.Tempera.json").read_text(encoding="utf-8")
    )
    assert set(manifest["finish-args"]) == {
        "--socket=wayland",
        "--socket=fallback-x11",
        "--share=ipc",
        "--device=dri",
    }


def test_every_file_with_translatable_strings_is_listed_for_translators():
    """A string left out of POTFILES.in can never be translated, and nothing else would say so."""
    call = re.compile(r"(?<![\w.])_\(")
    listed = {
        line.strip()
        for line in (ROOT / "po" / "POTFILES.in").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    marked = {
        str(path.relative_to(ROOT))
        for path in PACKAGE.rglob("*.py")
        if call.search(path.read_text(encoding="utf-8")) and path.name != "i18n.py"
    }
    assert marked - listed == set()
    assert all((ROOT / name).is_file() for name in listed)


def test_the_build_installs_translations_and_tells_the_app_where_they_are():
    assert "subdir('po')" in (ROOT / "meson.build").read_text(encoding="utf-8")
    assert "i18n.gettext" in (ROOT / "po" / "meson.build").read_text(encoding="utf-8")
    assert "TEMPERA_LOCALE_DIR" in (ROOT / "tempera" / "tempera.in").read_text(encoding="utf-8")


def test_no_user_visible_string_is_built_with_an_f_string():
    """Translators need whole sentences with named places, which f-strings cannot give them."""
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"(?<![\w.])_\(\s*f[\"']", line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert offenders == []
