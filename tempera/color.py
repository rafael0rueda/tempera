# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from gi.repository import Gdk, GObject, Gtk
from .i18n import _

# Named, because a swatch a screen reader can only call "#c01c28" is no use.
PALETTE = [
    (_("Black"), "#000000"), (_("Grey"), "#7a7a7a"), (_("Red"), "#c01c28"),
    (_("Orange"), "#e66100"), (_("Yellow"), "#f5c211"), (_("Green"), "#33d17a"),
    (_("Teal"), "#2ec27e"), (_("Blue"), "#3584e4"), (_("Dark blue"), "#1c71d8"),
    (_("Purple"), "#9141ac"), (_("Brown"), "#986a44"), (_("Dark brown"), "#63452c"),
    (_("White"), "#ffffff"), (_("Light grey"), "#deddda"), (_("Light red"), "#f66151"),
    (_("Light orange"), "#ffbe6f"), (_("Light yellow"), "#f9f06b"),
    (_("Light green"), "#8ff0a4"), (_("Light blue"), "#99c1f1"), (_("Pink"), "#dc8add"),
]


MAX_RECENT_COLORS = 10


def rgba(spec: str) -> Gdk.RGBA:
    color = Gdk.RGBA()
    color.parse(spec)
    return color


class ColorState(GObject.Object):
    """The primary (left click) and secondary (right click) colors."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__()
        self._primary = rgba("#000000")
        self._secondary = rgba("#ffffff")
        # Colors picked lately, newest first, so a mixed color is a click away
        # the next time it is wanted.
        self.recent: list[Gdk.RGBA] = []

    @property
    def primary(self) -> Gdk.RGBA:
        return self._primary

    @primary.setter
    def primary(self, value: Gdk.RGBA) -> None:
        self._primary = value
        self._remember(value)
        self.emit("changed")

    @property
    def secondary(self) -> Gdk.RGBA:
        return self._secondary

    @secondary.setter
    def secondary(self, value: Gdk.RGBA) -> None:
        self._secondary = value
        self._remember(value)
        self.emit("changed")

    def _remember(self, color: Gdk.RGBA) -> None:
        kept = [existing for existing in self.recent if not existing.equal(color)]
        self.recent = [color] + kept[: MAX_RECENT_COLORS - 1]

    def for_button(self, button: int) -> Gdk.RGBA:
        return self._secondary if button == Gdk.BUTTON_SECONDARY else self._primary

    def swap(self) -> None:
        self._primary, self._secondary = self._secondary, self._primary
        self.emit("changed")


def describe(color: Gdk.RGBA) -> str:
    """A color as a person would hear it: its palette name if it has one, else its hex."""
    spec = "#%02x%02x%02x" % tuple(round(channel * 255) for channel in (color.red, color.green, color.blue))
    for name, palette_spec in PALETTE:
        if palette_spec == spec:
            return _("{name} ({hex})").format(name=name, hex=spec)
    return spec


class Swatch(Gtk.Button):
    """A clickable color square. Left click sets primary, right click secondary.

    A button rather than a plain drawing area, so it can be reached with Tab,
    activated with Enter or Space, and announced by a screen reader. Keyboard
    activation sets the primary color; `X` then swaps the two.
    """

    __gsignals__ = {"picked": (GObject.SignalFlags.RUN_FIRST, None, (int,))}

    def __init__(self, color: Gdk.RGBA, size: int = 22, label: str = ""):
        super().__init__()
        self._color = color
        self.add_css_class("tempera-swatch")
        area = Gtk.DrawingArea(content_width=size, content_height=size)
        area.set_draw_func(self._draw)
        self.set_child(area)
        self._area = area

        self.connect("clicked", lambda *_args: self.emit("picked", Gdk.BUTTON_PRIMARY))
        secondary = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        secondary.connect("pressed", lambda *_args: self.emit("picked", Gdk.BUTTON_SECONDARY))
        self.add_controller(secondary)
        if label:
            self.set_label_text(label)

    def set_label_text(self, label: str) -> None:
        """What a screen reader reads out, since the button shows only colour."""
        self.set_tooltip_text(label)
        self.update_property([Gtk.AccessibleProperty.LABEL], [label])

    @property
    def color(self) -> Gdk.RGBA:
        return self._color

    @color.setter
    def color(self, value: Gdk.RGBA) -> None:
        self._color = value
        self._area.queue_draw()

    def _draw(self, area, cr, width, height, *_args):
        radius = 4
        cr.new_sub_path()
        cr.arc(width - radius, radius, radius, -1.5708, 0)
        cr.arc(width - radius, height - radius, radius, 0, 1.5708)
        cr.arc(radius, height - radius, radius, 1.5708, 3.1416)
        cr.arc(radius, radius, radius, 3.1416, 4.7124)
        cr.close_path()

        cr.set_source_rgba(self._color.red, self._color.green, self._color.blue, self._color.alpha)
        cr.fill_preserve()

        outline = area.get_color()
        cr.set_source_rgba(outline.red, outline.green, outline.blue, 0.25)
        cr.set_line_width(1)
        cr.stroke()


class PaletteLayout:
    WIDE = "wide"  # a row along the bottom bar
    NARROW = "narrow"  # a column beside the canvas
    BLOCK = "block"  # a block under the tools in the sidebar


class ColorBar(Gtk.Box):
    """Current colors, the fixed palette, and a custom color picker."""

    def __init__(self, colors: ColorState):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.colors = colors

        self._primary_swatch = Swatch(colors.primary, size=32)
        self._secondary_swatch = Swatch(colors.secondary, size=32)
        # Sized apart from the palette when the interface is drawn bigger.
        self._primary_swatch.add_css_class("tempera-swatch-current")
        self._secondary_swatch.add_css_class("tempera-swatch-current")
        self._primary_swatch.connect("picked", lambda *_args: self.choose(primary=True))
        self._secondary_swatch.connect("picked", lambda *_args: self.choose(primary=False))

        current = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        current.set_halign(Gtk.Align.CENTER)
        current.append(self._primary_swatch)
        current.append(self._secondary_swatch)

        # The window gives it a tooltip naming the current shortcut.
        self.swap_button = Gtk.Button(icon_name="tempera-swap-colors-symbolic")
        self.swap_button.add_css_class("flat")
        self.swap_button.set_halign(Gtk.Align.CENTER)
        self.swap_button.set_valign(Gtk.Align.CENTER)
        self.swap_button.connect("clicked", lambda *_args: colors.swap())

        # The current colors and the swap button, side by side or stacked.
        self._current_row = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        self._current_row.append(current)
        self._current_row.append(self.swap_button)
        self.append(self._current_row)

        self._grid = Gtk.Grid(row_spacing=4, column_spacing=4)
        self._palette_swatches = []
        for name, spec in PALETTE:
            swatch = Swatch(rgba(spec), label=_("{name} ({hex})").format(name=name, hex=spec))
            swatch.connect("picked", self._on_palette_picked)
            self._palette_swatches.append(swatch)
        self.append(self._grid)

        # Shown once something has been picked, and only then.
        self._recent_grid = Gtk.Grid(row_spacing=4, column_spacing=4, visible=False)
        self._recent_swatches: list[Swatch] = []
        self.append(self._recent_grid)

        self.set_layout(PaletteLayout.WIDE)
        colors.connect("changed", self._sync)
        self._sync()

    def set_layout(self, layout: str) -> None:
        """Lay out for the bottom bar, a narrow strip beside the canvas, or the tool sidebar."""
        wide = layout == PaletteLayout.WIDE
        self.set_orientation(Gtk.Orientation.HORIZONTAL if wide else Gtk.Orientation.VERTICAL)
        # A strip or the sidebar brings its own padding, so only the bottom bar needs margins.
        margin_x, margin_y = (12, 6) if wide else (0, 0)
        self.set_margin_start(margin_x)
        self.set_margin_end(margin_x)
        self.set_margin_top(margin_y)
        self.set_margin_bottom(margin_y)

        stacked = layout == PaletteLayout.NARROW
        self._current_row.set_orientation(
            Gtk.Orientation.VERTICAL if stacked else Gtk.Orientation.HORIZONTAL
        )
        self._grid.set_halign(Gtk.Align.FILL if wide else Gtk.Align.CENTER)
        self._grid.set_valign(Gtk.Align.CENTER if wide else Gtk.Align.START)

        self._recent_grid.set_halign(self._grid.get_halign())
        self._recent_grid.set_valign(self._grid.get_valign())

        self._columns = {
            PaletteLayout.WIDE: 10, PaletteLayout.NARROW: 2, PaletteLayout.BLOCK: 5
        }[layout]
        for swatch in self._palette_swatches:
            if swatch.get_parent() is not None:
                self._grid.remove(swatch)
        for index, swatch in enumerate(self._palette_swatches):
            self._grid.attach(swatch, index % self._columns, index // self._columns, 1, 1)
        self._refresh_recent()

    def refresh(self) -> None:
        """Take the colours afresh, after they have been restored from settings."""
        self._sync()

    def _refresh_recent(self) -> None:
        """Lay the recently picked colors out below the fixed palette."""
        recent = self.colors.recent
        self._recent_grid.set_visible(bool(recent))
        while len(self._recent_swatches) < len(recent):
            swatch = Swatch(recent[0])
            swatch.connect("picked", self._on_palette_picked)
            self._recent_swatches.append(swatch)
        for index, swatch in enumerate(self._recent_swatches):
            if swatch.get_parent() is not None:
                self._recent_grid.remove(swatch)
            if index >= len(recent):
                continue
            swatch.color = recent[index]
            swatch.set_label_text(
                _("Recent colour, {color}").format(color=describe(recent[index]))
            )
            self._recent_grid.attach(
                swatch, index % self._columns, index // self._columns, 1, 1
            )

    def _on_palette_picked(self, swatch: Swatch, button: int) -> None:
        if button == Gdk.BUTTON_SECONDARY:
            self.colors.secondary = swatch.color
        else:
            self.colors.primary = swatch.color

    def _sync(self, *_args):
        self._primary_swatch.color = self.colors.primary
        self._secondary_swatch.color = self.colors.secondary
        self._primary_swatch.set_label_text(
            _("Primary color, {color}").format(color=describe(self.colors.primary))
        )
        self._secondary_swatch.set_label_text(
            _("Secondary color, {color}").format(color=describe(self.colors.secondary))
        )
        self._refresh_recent()

    def choose(self, primary: bool) -> None:
        """Open the colour dialog for the primary or the secondary colour."""
        # With alpha, so a colour can be made see-through; the dialog's own
        # custom section is where a hex value can be typed in.
        dialog = Gtk.ColorDialog(with_alpha=True, title=_("Choose a color"))
        initial = self.colors.primary if primary else self.colors.secondary

        def on_done(source, result):
            try:
                color = source.choose_rgba_finish(result)
            except Exception:
                return
            if color is None:
                return
            if primary:
                self.colors.primary = color
            else:
                self.colors.secondary = color

        dialog.choose_rgba(self.get_root(), initial, None, on_done)
