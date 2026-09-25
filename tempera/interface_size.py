# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""How big the interface is drawn: one setting for text, icons and controls alike.

GTK has no zoom for a whole app, so this is done in parts. Text follows the font
resolution GTK keeps for the display, which every label, menu and dialog in the
process reads. Icons and the controls whose size is set in pixels follow two
stylesheets written for the chosen size. The few things Tempera draws itself,
such as the resize grips, ask `scaled()`.

At the default size none of this is touched, so Tempera then looks exactly as the
system and theme make it. One limit: while a bigger size is in use, a change to
the system's text size is only picked up once the size is chosen again or the
app restarts, since GTK stops following the system once an app sets it.
"""

from __future__ import annotations

from gi.repository import Gdk, Gtk

SIZES = (100, 125, 150, 200)
DEFAULT_SIZE = 100

# GTK's own default when the system gives no resolution: 96 dpi, in 1/1024ths.
_FALLBACK_DPI = 96 * 1024
# Below the theme, so the icons it sizes on purpose (a large one on an empty
# page, say) keep their size; every other icon grows.
_ICON_PRIORITY = Gtk.STYLE_PROVIDER_PRIORITY_THEME - 1
# Above Tempera's own stylesheet, whose sizes these replace.
_CONTROL_PRIORITY = Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1

_current = DEFAULT_SIZE
# Per display: (icon stylesheet, control stylesheet).
_providers: dict[Gdk.Display, tuple[Gtk.CssProvider, Gtk.CssProvider]] = {}


def parse(text: str) -> int:
    """A remembered size, or the default for anything else a settings file may hold."""
    try:
        size = int(text)
    except ValueError:
        return DEFAULT_SIZE
    return size if size in SIZES else DEFAULT_SIZE


def current() -> int:
    return _current


def scaled(pixels: float, size: int | None = None) -> int:
    """A length given for the default size, at the current (or given) size."""
    return round(pixels * (_current if size is None else size) / 100)


def icon_stylesheet(size: int) -> str:
    if size == DEFAULT_SIZE:
        return ""
    return f"image {{ -gtk-icon-size: {scaled(16, size)}px; }}\n"


def control_stylesheet(size: int) -> str:
    """Sizes for the controls that are measured in pixels rather than in text."""
    if size == DEFAULT_SIZE:
        return ""

    def px(pixels: float) -> str:
        return f"{scaled(pixels, size)}px"

    slider = scaled(20, size)
    # libadwaita pulls the slider knob over the 4-pixel-thick trough with a
    # negative margin; the margin grows with the knob so it stays centred.
    slider_margin = f"-{(slider - 4) // 2}px"
    return "\n".join(
        [
            f".tempera-tool {{ min-width: {px(38)}; min-height: {px(38)}; }}",
            f".tempera-shape-picker > button {{ min-width: {px(30)}; min-height: {px(28)}; }}",
            f".tempera-status-button {{ min-width: {px(24)}; min-height: {px(24)}; }}",
            f".tempera-color-chip {{ min-width: {px(14)}; min-height: {px(14)}; }}",
            f".tempera-swatch > * {{ min-width: {px(22)}; min-height: {px(22)}; }}",
            ".tempera-swatch.tempera-swatch-current > *"
            f" {{ min-width: {px(32)}; min-height: {px(32)}; }}",
            f"check, radio {{ min-width: {px(14)}; min-height: {px(14)}; -gtk-icon-size: {px(14)}; }}",
            "scale > trough > slider"
            f" {{ min-width: {slider}px; min-height: {slider}px; margin: {slider_margin}; }}",
            f"switch > slider {{ min-width: {px(20)}; min-height: {px(20)}; }}",
            "",
        ]
    )


def _providers_for(display: Gdk.Display) -> tuple[Gtk.CssProvider, Gtk.CssProvider]:
    if display not in _providers:
        icons, controls = Gtk.CssProvider(), Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(display, icons, _ICON_PRIORITY)
        Gtk.StyleContext.add_provider_for_display(display, controls, _CONTROL_PRIORITY)
        _providers[display] = (icons, controls)
    return _providers[display]


def apply(size: int, display: Gdk.Display | None = None) -> None:
    """Draw every window of the app at this size, from now on."""
    global _current
    _current = size if size in SIZES else DEFAULT_SIZE
    display = display or Gdk.Display.get_default()
    if display is None:
        return

    settings = Gtk.Settings.get_for_display(display)
    # Back to the system's resolution first, so sizes never compound.
    settings.reset_property("gtk-xft-dpi")
    if _current != DEFAULT_SIZE:
        system_dpi = settings.props.gtk_xft_dpi
        if system_dpi <= 0:
            system_dpi = _FALLBACK_DPI
        settings.props.gtk_xft_dpi = round(system_dpi * _current / 100)

    icons, controls = _providers_for(display)
    icons.load_from_string(icon_stylesheet(_current))
    controls.load_from_string(control_stylesheet(_current))
