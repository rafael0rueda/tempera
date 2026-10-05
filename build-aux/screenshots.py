#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Take the screenshots the README, the user guide and the app metadata show.

    python build-aux/screenshots.py            # all four, into data/screenshots/
    python build-aux/screenshots.py dark-style # one of them

Each is the real window, 1280 × 800, with a picture painted for the purpose,
rendered by GTK itself rather than grabbed off the screen. They are taken in a
headless compositor, so no window appears on the desktop, each in a process of
its own with settings of its own: neither the desktop's font and dark setting
nor Tempera's remembered options get into the picture.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "data" / "screenshots"
SIZE = (1280, 800)
DISPLAY = "tempera-screenshots"
SHOTS = ("main-window", "dark-style", "interface-size", "color-editor")


def take_all(names: tuple[str, ...]) -> int:
    """Start a compositor nobody sees, and take each screenshot in it."""
    compositor = subprocess.Popen(
        ["mutter", "--headless", "--wayland-display", DISPLAY, "--virtual-monitor", "1920x1080", "--no-x11"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        socket = Path(os.environ["XDG_RUNTIME_DIR"]) / DISPLAY
        deadline = time.monotonic() + 10
        while not socket.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        failed = 0
        for name in names:
            with tempfile.TemporaryDirectory() as home:
                environment = dict(
                    os.environ,
                    WAYLAND_DISPLAY=DISPLAY,
                    GDK_BACKEND="wayland",
                    XDG_CONFIG_HOME=f"{home}/config",
                    XDG_DATA_HOME=f"{home}/data",
                    TEMPERA_SHOT=name,
                )
                result = subprocess.run([sys.executable, __file__], env=environment, timeout=60)
                print(f"{name}: {'taken' if result.returncode == 0 else 'FAILED'}")
                failed += result.returncode != 0
        return failed
    finally:
        compositor.terminate()


# From here on, inside the process that takes one screenshot.


class Gesture:
    def __init__(self, gdk):
        self._gdk = gdk

    def get_current_button(self):
        return self._gdk.BUTTON_PRIMARY

    def get_current_event_state(self):
        return self._gdk.ModifierType(0)


def meadow(cairo, document_module):
    """A meadow with a house, a tree and the sun, each on a layer of its own."""
    from tempera.document import Document, Layer, new_surface

    width, height = 800, 520

    def layer(name, paint):
        surface = new_surface(width, height, (0, 0, 0, 0))
        paint(cairo.Context(surface))
        return Layer(surface, name)

    def rgb(cr, spec):
        cr.set_source_rgb(*(int(spec[i:i + 2], 16) / 255 for i in (1, 3, 5)))

    def background(cr):
        sky = cairo.LinearGradient(0, 0, 0, height)
        sky.add_color_stop_rgb(0, 0x86 / 255, 0xB6 / 255, 0xF2 / 255)
        sky.add_color_stop_rgb(1, 0xC4 / 255, 0xDC / 255, 0xF9 / 255)
        cr.set_source(sky)
        cr.paint()

    def hills(cr):
        for spec, cx, cy, rx, ry in (("#57e389", 250, 520, 420, 160), ("#33d17a", 760, 560, 550, 170)):
            rgb(cr, spec)
            cr.save()
            cr.translate(cx, cy)
            cr.scale(rx, ry)
            cr.arc(0, 0, 1, 0, 2 * math.pi)
            cr.restore()
            cr.fill()
        for spec, x, y in (
            ("#c061cb", 110, 440), ("#ff7800", 150, 470), ("#f66151", 320, 450), ("#c061cb", 360, 480),
            ("#dc8add", 560, 485), ("#f6d32d", 680, 460), ("#f66151", 730, 430),
        ):
            rgb(cr, spec)
            cr.arc(x, y, 9, 0, 2 * math.pi)
            cr.fill()

    def sun_and_clouds(cr):
        rgb(cr, "#f6d32d")
        cr.arc(640, 110, 56, 0, 2 * math.pi)
        cr.fill()
        cr.set_line_width(7)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        for ray in range(9):
            angle = ray * 2 * math.pi / 9 + 0.2
            cr.move_to(640 + 74 * math.cos(angle), 110 + 74 * math.sin(angle))
            cr.line_to(640 + 100 * math.cos(angle), 110 + 100 * math.sin(angle))
        cr.stroke()
        cr.set_source_rgb(1, 1, 1)
        for x, y, radius in ((165, 97, 30), (200, 78, 38), (237, 95, 32), (373, 157, 30), (410, 138, 38), (447, 155, 32)):
            cr.arc(x, y, radius, 0, 2 * math.pi)
            cr.fill()

    def tree(cr):
        rgb(cr, "#865e3c")
        cr.rectangle(212, 350, 22, 90)
        cr.fill()
        rgb(cr, "#26a269")
        for x, y, radius in ((222, 260, 50), (190, 300, 50), (256, 300, 50), (222, 312, 48)):
            cr.arc(x, y, radius, 0, 2 * math.pi)
            cr.fill()

    def house(cr):
        cr.set_line_width(5)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        for spec, shape in (
            ("#f6f5f4", lambda: cr.rectangle(440, 300, 150, 120)),
            ("#e01b24", lambda: (cr.move_to(425, 300), cr.line_to(515, 225), cr.line_to(607, 300), cr.close_path())),
            ("#f9f06b", lambda: cr.rectangle(462, 325, 34, 30)),
            ("#986a44", lambda: cr.rectangle(535, 345, 36, 72)),
        ):
            shape()
            rgb(cr, spec)
            cr.fill_preserve()
            rgb(cr, "#3d3846")
            cr.stroke()

    return Document(
        layers=[
            layer("Background", background),
            layer("Hills", hills),
            layer("Sun and clouds", sun_and_clouds),
            layer("Tree", tree),
            layer("House", house),
        ]
    )


def take_one(name: str) -> int:
    sys.path.insert(0, str(ROOT))
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Adw", "1")
    import cairo
    from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gtk

    from tempera import document as document_module
    from tempera import settings
    from tempera.color import rgba
    from tempera.main import TemperaApplication

    if name == "interface-size":
        settings.save_settings({"interface-size": "150"})

    app = TemperaApplication()
    app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
    status = {"code": 1}

    def tool(window, tool_id):
        window.lookup_action("tool").change_state(GLib.Variant.new_string(tool_id))

    def drag(canvas, start, end):
        gesture = Gesture(Gdk)
        offset = ((end[0] - start[0]) * canvas.zoom, (end[1] - start[1]) * canvas.zoom)
        canvas._on_drag_begin(gesture, start[0] * canvas.zoom, start[1] * canvas.zoom)
        canvas._on_drag_update(gesture, *offset)
        canvas._on_drag_end(gesture, *offset)

    def open_picture(window) -> None:
        document = meadow(cairo, document_module)
        document.file = Gio.File.new_for_path("/tmp/meadow.ora")
        window._set_document(document)
        window.colors.primary, window.colors.secondary = rgba("#9141ac"), rgba("#f8e45c")
        if name == "interface-size":
            window.lookup_action("layers-panel").change_state(GLib.Variant.new_boolean(False))

    def stage(window) -> None:
        """What the screenshot is of, once the window has laid itself out around the picture:
        what floats holds the canvas where it is, so it must be in its place first."""
        canvas, colors, document = window.canvas, window.colors, window.canvas.document

        if name == "main-window":
            colors.recent = [rgba(spec) for spec in ("#9141ac", "#26a269", "#865e3c", "#f66151", "#f8e45c", "#3584e4")]
            window._color_bar.refresh()
            tool(window, "brush")
            window._size_adjustment.set_value(14)
            document.select_layer(1)
            cr = cairo.Context(document.surface)
            cr.set_source_rgb(0x91 / 255, 0x41 / 255, 0xAC / 255)
            cr.set_line_width(14)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.move_to(70, 330)
            for point in ((78, 305), (92, 330), (110, 300), (128, 330), (140, 315)):
                cr.line_to(*point)
            cr.stroke()
            document._changed(None, layers=True)
        elif name == "dark-style":
            tool(window, "select")
            document.select_layer(2)
            canvas.select_region(530, 0, 220, 220)
            grip = canvas._handles()["rotate"]
            # A twelfth of a turn clockwise about the middle of the selection.
            centre = (640, 110)
            radius = centre[1] - grip[1]
            angle = math.radians(30)
            drag(canvas, grip, (centre[0] + radius * math.sin(angle), centre[1] - radius * math.cos(angle)))
            # And carried a little way in from the edge, so all of it shows.
            drag(canvas, centre, (centre[0] - 50, centre[1] + 60))
        elif name == "interface-size":
            tool(window, "shapes")
            window.lookup_action("shape").change_state(GLib.Variant.new_string("star"))
            window._size_adjustment.set_value(6)
            window._fill_toggle.set_active(True)
            window.lookup_action("line-style").change_state(GLib.Variant.new_string("dashed"))
            # The whole picture in view, at this size of everything around it.
            canvas.set_zoom(0.75)
            drag(canvas, (610, 330), (760, 480))
        elif name == "color-editor":
            tool(window, "pencil")
            colors.custom = [
                rgba(spec)
                for spec in ("#9141ac", "#26a269", "#865e3c", "#e01b24", "#f6d32d", "#1c71d8",
                             "#ff7800", "#63452c", "#c061cb", "#57e389")
            ]
            window._color_bar.choose(True)

    def capture(window) -> bool:
        width, height = window.get_width(), window.get_height()
        snapshot = Gtk.Snapshot()
        Gtk.WidgetPaintable.new(window).snapshot(snapshot, width, height)
        node = snapshot.to_node()
        texture = window.get_renderer().render_texture(node, Graphene.Rect().init(0, 0, width, height))
        OUTPUT.mkdir(parents=True, exist_ok=True)
        texture.save_to_png(str(OUTPUT / f"{name}.png"))
        status["code"] = 0 if (width, height) == SIZE else 2
        if status["code"]:
            print(f"{name}: the window came out {width} × {height}, not {SIZE[0]} × {SIZE[1]}", file=sys.stderr)
        app.quit()
        return GLib.SOURCE_REMOVE

    def on_activate(_app) -> None:
        # The fonts and style the screenshots have always had, whatever this desktop uses.
        Gtk.Settings.get_default().props.gtk_font_name = "Adwaita Sans 11"
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK if name == "dark-style" else Adw.ColorScheme.FORCE_LIGHT
        )
        window = app.props.active_window
        window.set_default_size(*SIZE)

        def opened() -> bool:
            open_picture(window)
            GLib.timeout_add(800, staged)
            return GLib.SOURCE_REMOVE

        def staged() -> bool:
            stage(window)
            GLib.timeout_add(1500, capture, window)
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(1000, opened)

    app.connect_after("activate", on_activate)
    app.run([])
    return status["code"]


if __name__ == "__main__":
    shot = os.environ.get("TEMPERA_SHOT")
    if shot:
        sys.exit(take_one(shot))
    wanted = tuple(sys.argv[1:]) or SHOTS
    unknown = [each for each in wanted if each not in SHOTS]
    if unknown:
        sys.exit(f"No such screenshot: {', '.join(unknown)}. There are: {', '.join(SHOTS)}")
    sys.exit(take_all(wanted))
