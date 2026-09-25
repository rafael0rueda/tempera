# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import math

from gi.repository import Gdk, GObject, Graphene, Gsk, Gtk

from . import interface_size
from .i18n import _

# The GNOME palette, twenty colours with no two alike. Named, because a swatch
# a screen reader can only call "#c01c28" is no use.
PALETTE = [
    (_("Black"), "#000000"), (_("Grey"), "#77767b"), (_("Red"), "#c01c28"),
    (_("Orange"), "#e66100"), (_("Yellow"), "#f5c211"), (_("Green"), "#2ec27e"),
    (_("Dark green"), "#26a269"), (_("Blue"), "#3584e4"), (_("Dark blue"), "#1c71d8"),
    (_("Purple"), "#9141ac"), (_("Brown"), "#986a44"), (_("Dark brown"), "#63452c"),
    (_("White"), "#ffffff"), (_("Light grey"), "#deddda"), (_("Light red"), "#f66151"),
    (_("Light orange"), "#ffbe6f"), (_("Light yellow"), "#f8e45c"),
    (_("Light green"), "#8ff0a4"), (_("Light blue"), "#99c1f1"), (_("Pink"), "#dc8add"),
]


MAX_RECENT_COLORS = 6


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
        # Colors painted with lately, newest first, so a mixed color is a click
        # away the next time it is wanted.
        self.recent: list[Gdk.RGBA] = []

    @property
    def primary(self) -> Gdk.RGBA:
        return self._primary

    @primary.setter
    def primary(self, value: Gdk.RGBA) -> None:
        self._primary = value
        self.emit("changed")

    @property
    def secondary(self) -> Gdk.RGBA:
        return self._secondary

    @secondary.setter
    def secondary(self, value: Gdk.RGBA) -> None:
        self._secondary = value
        self.emit("changed")

    def remember(self, *used: Gdk.RGBA) -> None:
        """Put colours just painted with at the front of the recent ones, the first frontmost."""
        if not used:
            return
        for color in reversed(used):
            kept = [existing for existing in self.recent if not existing.equal(color)]
            self.recent = [color.copy()] + kept[: MAX_RECENT_COLORS - 1]
        self.emit("changed")

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

    def set_swatch_size(self, size: int) -> None:
        self._area.set_content_width(size)
        self._area.set_content_height(size)

    @property
    def color(self) -> Gdk.RGBA:
        return self._color

    @color.setter
    def color(self, value: Gdk.RGBA) -> None:
        self._color = value
        self._area.queue_draw()

    def _draw(self, area, cr, width, height, *_args):
        radius = max(3, min(width, height) / 4)
        _rounded_rect(cr, 0, 0, width, height, radius)
        cr.set_source_rgba(self._color.red, self._color.green, self._color.blue, self._color.alpha)
        cr.fill()

        # A faint line just inside the edge, so black on a dark panel and white
        # on a light one still read as squares.
        edge = area.get_color()
        _rounded_rect(cr, 0.5, 0.5, width - 1, height - 1, radius - 0.5)
        cr.set_source_rgba(edge.red, edge.green, edge.blue, 0.18)
        cr.set_line_width(1)
        cr.stroke()


def _rounded_rect(cr, x: float, y: float, width: float, height: float, radius: float) -> None:
    cr.new_sub_path()
    cr.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    cr.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    cr.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    cr.close_path()


class ColorChip(Gtk.DrawingArea):
    """A small square in a colour, outlined or filled, on a button that draws in it."""

    def __init__(self, filled: bool, size: int = 14):
        super().__init__(content_width=size, content_height=size, valign=Gtk.Align.CENTER)
        self.add_css_class("tempera-color-chip")
        self._filled = filled
        self._color = rgba("#000000")
        self.set_draw_func(self._draw)

    @property
    def color(self) -> Gdk.RGBA:
        return self._color

    @color.setter
    def color(self, value: Gdk.RGBA) -> None:
        self._color = value
        self.queue_draw()

    def _draw(self, area, cr, width, height, *_args):
        side = min(width, height)
        line = max(1.0, side / 7)
        x, y = (width - side) / 2, (height - side) / 2
        color = self._color
        if self._filled:
            _rounded_rect(cr, x, y, side, side, side / 3.5)
            cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
            cr.fill_preserve()
            # A faint edge, so black on a dark bar or white on a light one still shows.
            edge = area.get_color()
            cr.set_source_rgba(edge.red, edge.green, edge.blue, 0.2)
            cr.set_line_width(1)
            cr.stroke()
        else:
            inset = line / 2
            _rounded_rect(cr, x + inset, y + inset, side - line, side - line, side / 3.5 - inset)
            cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
            cr.set_line_width(line)
            cr.stroke()


class ColorWell(Gtk.Widget):
    """The primary and secondary colours as two overlapping squares, the primary in front.

    Clicking either opens the colour dialog for it.
    """

    def __init__(self, colors: ColorState):
        super().__init__()
        self.primary = Swatch(colors.primary, size=28)
        self.secondary = Swatch(colors.secondary, size=28)
        # The later child is the one in front, both for drawing and for
        # which of the two a click on the overlap reaches.
        for swatch in (self.secondary, self.primary):
            swatch.add_css_class("tempera-swatch-current")
            swatch.set_parent(self)

    def do_dispose(self) -> None:
        self.secondary.unparent()
        self.primary.unparent()

    def set_swatch_size(self, size: int) -> None:
        self.primary.set_swatch_size(size)
        self.secondary.set_swatch_size(size)
        self.queue_resize()

    def _side(self) -> int:
        return self.primary.measure(Gtk.Orientation.HORIZONTAL, -1)[1]

    def do_get_request_mode(self) -> Gtk.SizeRequestMode:
        return Gtk.SizeRequestMode.CONSTANT_SIZE

    def do_measure(self, orientation: Gtk.Orientation, for_size: int):
        # The two squares overlap by a little over a third of their side.
        size = round(self._side() * 11 / 7)
        return size, size, -1, -1

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        side = self._side()
        self.primary.allocate(side, side, -1, None)
        point = Graphene.Point()
        point.init(width - side, height - side)
        self.secondary.allocate(side, side, -1, Gsk.Transform.new().translate(point))


class PaletteLayout:
    WIDE = "wide"  # a row along the bottom
    NARROW = "narrow"  # a column beside the canvas
    BLOCK = "block"  # a block under the tools in the sidebar


# Per layout: palette columns, and the sizes of a palette swatch and of the
# colour well's squares, at the default interface size.
_LAYOUTS = {
    PaletteLayout.WIDE: (len(PALETTE), 24, 26),
    PaletteLayout.NARROW: (2, 22, 28),
    PaletteLayout.BLOCK: (4, 18, 26),
}


class ColorBar(Gtk.Box):
    """Current colors, the fixed palette, and the colours used lately."""

    def __init__(self, colors: ColorState):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.colors = colors

        self._well = ColorWell(colors)
        self._primary_swatch = self._well.primary
        self._secondary_swatch = self._well.secondary
        self._primary_swatch.connect("picked", lambda *_args: self.choose(primary=True))
        self._secondary_swatch.connect("picked", lambda *_args: self.choose(primary=False))

        # The window gives it a tooltip naming the current shortcut.
        self.swap_button = Gtk.Button(icon_name="tempera-swap-colors-symbolic")
        self.swap_button.add_css_class("flat")
        self.swap_button.add_css_class("dim-label")
        self.swap_button.set_halign(Gtk.Align.CENTER)
        self.swap_button.set_valign(Gtk.Align.CENTER)
        self.swap_button.connect("clicked", lambda *_args: colors.swap())

        # The current colors and the swap button, side by side or stacked.
        self._current_row = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        self._current_row.append(self._well)
        self._current_row.append(self.swap_button)
        self.append(self._current_row)

        self._grid = Gtk.Grid(row_spacing=4, column_spacing=4)
        self._palette_swatches = []
        for name, spec in PALETTE:
            swatch = Swatch(rgba(spec), label=_("{name} ({hex})").format(name=name, hex=spec))
            swatch.connect("picked", self._on_palette_picked)
            self._palette_swatches.append(swatch)
        self.append(self._grid)

        # Shown once something has been painted with, and only then.
        self._recent_separator = Gtk.Separator(
            orientation=Gtk.Orientation.VERTICAL, margin_top=16, margin_bottom=16
        )
        self._recent_caption = Gtk.Label(label=_("Recent"))
        self._recent_caption.add_css_class("caption")
        self._recent_caption.add_css_class("dim-label")
        self._recent_grid = Gtk.Grid(row_spacing=4, column_spacing=4)
        self._recent_swatches: list[Swatch] = []
        for widget in (self._recent_separator, self._recent_caption, self._recent_grid):
            self.append(widget)

        self.set_layout(PaletteLayout.WIDE)
        colors.connect("changed", self._sync)
        self._sync()

    def set_layout(self, layout: str) -> None:
        """Lay out for a row along the bottom, a column beside the canvas, or the tool sidebar."""
        self._layout = layout
        wide = layout == PaletteLayout.WIDE
        self.set_orientation(Gtk.Orientation.HORIZONTAL if wide else Gtk.Orientation.VERTICAL)
        self.set_spacing(14 if wide else 10)
        # Wherever it sits, the panel brings its own padding.
        self.set_valign(Gtk.Align.CENTER if wide else Gtk.Align.START)
        self.set_halign(Gtk.Align.START if wide else Gtk.Align.CENTER)

        stacked = layout == PaletteLayout.NARROW
        self._current_row.set_orientation(
            Gtk.Orientation.VERTICAL if stacked else Gtk.Orientation.HORIZONTAL
        )
        for grid in (self._grid, self._recent_grid):
            grid.set_halign(Gtk.Align.START if wide else Gtk.Align.CENTER)
            grid.set_valign(Gtk.Align.CENTER)

        self._columns = _LAYOUTS[layout][0]
        for swatch in self._palette_swatches:
            if swatch.get_parent() is not None:
                self._grid.remove(swatch)
        for index, swatch in enumerate(self._palette_swatches):
            self._grid.attach(swatch, index % self._columns, index // self._columns, 1, 1)
        self.sync_size()
        self._refresh_recent()

    def sync_size(self) -> None:
        """Size the swatches for where the palette is, at the interface size now chosen."""
        _columns, swatch, well = _LAYOUTS[self._layout]
        size = interface_size.scaled(swatch)
        for each in self._palette_swatches + self._recent_swatches:
            each.set_swatch_size(size)
        self._well.set_swatch_size(interface_size.scaled(well))

    def refresh(self) -> None:
        """Take the colours afresh, after they have been restored from settings."""
        self._sync()

    def _refresh_recent(self) -> None:
        """Lay the colours used lately out after the fixed palette."""
        recent = self.colors.recent
        self._recent_separator.set_visible(bool(recent) and self._layout == PaletteLayout.WIDE)
        self._recent_caption.set_visible(bool(recent))
        self._recent_grid.set_visible(bool(recent))
        size = interface_size.scaled(_LAYOUTS[self._layout][1])
        while len(self._recent_swatches) < len(recent):
            swatch = Swatch(recent[0], size=size)
            swatch.connect("picked", self._on_palette_picked)
            self._recent_swatches.append(swatch)
        # Along the bottom they make one row, as the palette does.
        columns = MAX_RECENT_COLORS if self._layout == PaletteLayout.WIDE else self._columns
        for index, swatch in enumerate(self._recent_swatches):
            if swatch.get_parent() is not None:
                self._recent_grid.remove(swatch)
            if index >= len(recent):
                continue
            swatch.color = recent[index]
            swatch.set_swatch_size(size)
            swatch.set_label_text(
                _("Recent colour, {color}").format(color=describe(recent[index]))
            )
            self._recent_grid.attach(swatch, index % columns, index // columns, 1, 1)

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
