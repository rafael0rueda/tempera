# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""A colour editor: pick a hue, then its strength and brightness, type a hex value,
or take a colour off the screen, and keep the ones worth keeping."""

from __future__ import annotations

import colorsys
import re
from typing import Callable

from gi.repository import Adw, Gdk, GObject, Graphene, Gsk, Gtk

from . import interface_size
from .color import ColorState, Swatch, describe
from .i18n import _
from .screen_color import pick_screen_color

# The square of strength and brightness, at the default interface size.
AREA_WIDTH = 300
AREA_HEIGHT = 180
KNOB_RADIUS = 7
# Colours kept for later: two rows of eight.
MAX_CUSTOM_COLORS = 16
# Arrow keys move the knob this far, Shift ten times as far.
KEY_STEP = 0.01

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def parse_hex(text: str) -> Gdk.RGBA | None:
    """A colour from #rgb, #rrggbb or #rrggbbaa, the # optional; None if it is none of them."""
    match = _HEX.match(text.strip())
    if match is None:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    if len(digits) == 6:
        digits += "ff"
    color = Gdk.RGBA()
    color.red, color.green, color.blue, color.alpha = (
        int(digits[index:index + 2], 16) / 255 for index in range(0, 8, 2)
    )
    return color


def to_hex(color: Gdk.RGBA) -> str:
    """#rrggbb, with the opacity as a last pair only when the colour is see-through."""
    channels = [color.red, color.green, color.blue] + ([color.alpha] if color.alpha < 1 else [])
    return "#" + "".join("%02x" % round(channel * 255) for channel in channels)


class SaturationValueArea(Gtk.Widget):
    """A square of one hue: stronger to the right, brighter to the top.

    Dragged or clicked, or moved with the arrow keys, its knob sets both.
    """

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self):
        super().__init__(focusable=True, accessible_role=Gtk.AccessibleRole.GROUP)
        self.add_css_class("tempera-color-area")
        self.hue = 0.0
        self.saturation = 1.0
        self.value = 1.0
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", lambda gesture, x, y: self._point_at(x, y))
        drag.connect("drag-update", self._on_drag_update)
        self.add_controller(drag)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(keys)
        self._describe()

    def set_hsv(self, hue: float, saturation: float, value: float) -> None:
        self.hue, self.saturation, self.value = hue, saturation, value
        self._describe()
        self.queue_draw()

    def _set(self, saturation: float, value: float) -> None:
        self.saturation = max(0.0, min(saturation, 1.0))
        self.value = max(0.0, min(value, 1.0))
        self._describe()
        self.queue_draw()
        self.emit("changed")

    def _describe(self) -> None:
        self.update_property(
            [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION],
            [
                _("Strength and brightness"),
                _("Strength {saturation}%, brightness {value}%. Arrow keys move it.").format(
                    saturation=round(self.saturation * 100), value=round(self.value * 100)
                ),
            ],
        )

    def _point_at(self, x: float, y: float) -> None:
        self.grab_focus()
        width, height = max(1, self.get_width()), max(1, self.get_height())
        self._set(x / width, 1 - y / height)

    def _on_drag_update(self, gesture, offset_x: float, offset_y: float) -> None:
        _found, start_x, start_y = gesture.get_start_point()
        self._point_at(start_x + offset_x, start_y + offset_y)

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        step = KEY_STEP * (10 if state & Gdk.ModifierType.SHIFT_MASK else 1)
        moves = {
            Gdk.KEY_Left: (-step, 0), Gdk.KEY_Right: (step, 0),
            Gdk.KEY_Up: (0, step), Gdk.KEY_Down: (0, -step),
        }
        if keyval not in moves:
            return False
        dx, dy = moves[keyval]
        self._set(self.saturation + dx, self.value + dy)
        return True

    def do_measure(self, orientation: Gtk.Orientation, for_size: int):
        size = interface_size.scaled(AREA_WIDTH if orientation == Gtk.Orientation.HORIZONTAL else AREA_HEIGHT)
        return size, size, -1, -1

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        width, height = self.get_width(), self.get_height()
        bounds = Graphene.Rect().init(0, 0, width, height)
        outline = Gsk.RoundedRect()
        outline.init_from_rect(bounds, 8)
        snapshot.push_rounded_clip(outline)
        red, green, blue = colorsys.hsv_to_rgb(self.hue, 1, 1)
        snapshot.append_color(Gdk.RGBA(red=red, green=green, blue=blue, alpha=1), bounds)
        # White fading out to the right, then black fading in to the bottom.
        white, clear, black = (
            Gdk.RGBA(red=1, green=1, blue=1, alpha=1),
            Gdk.RGBA(red=0, green=0, blue=0, alpha=0),
            Gdk.RGBA(red=0, green=0, blue=0, alpha=1),
        )
        for start, end, first in (
            (Graphene.Point().init(0, 0), Graphene.Point().init(width, 0), white),
            (Graphene.Point().init(0, height), Graphene.Point().init(0, 0), black),
        ):
            stops = [Gsk.ColorStop(), Gsk.ColorStop()]
            stops[0].offset, stops[0].color = 0.0, first
            stops[1].offset, stops[1].color = 1.0, clear
            snapshot.append_linear_gradient(bounds, start, end, stops)
        snapshot.pop()

        # The knob: a ring in white over a ring in black, to show on any colour.
        x, y = self.saturation * width, (1 - self.value) * height
        for radius, color in ((KNOB_RADIUS + 1, black), (KNOB_RADIUS, white)):
            ring = Gsk.RoundedRect()
            ring.init_from_rect(Graphene.Rect().init(x - radius, y - radius, 2 * radius, 2 * radius), radius)
            snapshot.append_border(ring, [2, 2, 2, 2], [color] * 4)


class ColorPreview(Gtk.DrawingArea):
    """The colour as it was beside the colour as it is now, over a checkerboard."""

    def __init__(self):
        super().__init__(content_width=72, content_height=36, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.before = Gdk.RGBA()
        self.after = Gdk.RGBA()
        self.add_css_class("tempera-color-preview")
        self.set_draw_func(self._draw)

    def _draw(self, area, cr, width: int, height: int, *_args) -> None:
        square = 6
        for row in range(0, height, square):
            for column in range(0, width, square):
                shade = 1.0 if (row // square + column // square) % 2 == 0 else 0.8
                cr.set_source_rgb(shade, shade, shade)
                cr.rectangle(column, row, square, square)
                cr.fill()
        half = width / 2
        for x, color in ((0, self.before), (half, self.after)):
            cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
            cr.rectangle(x, 0, half, height)
            cr.fill()


class ColorEditor(Adw.Dialog):
    """Choose one colour, starting from another. Select hands it over in the
    "chosen" signal; closing or Cancel keeps the colour as it was."""

    __gsignals__ = {"chosen": (GObject.SignalFlags.RUN_FIRST, None, (Gdk.RGBA,))}

    def __init__(
        self,
        title: str,
        color: Gdk.RGBA,
        colors: ColorState,
        show_message: Callable[[str], None] | None = None,
    ):
        # Wide enough for the title between Cancel and Select.
        super().__init__(title=title, content_width=interface_size.scaled(AREA_WIDTH + 100))
        self.colors = colors
        # Where to say why picking from the screen did not work.
        self._show_message = show_message
        self._original = color.copy()
        self._alpha = color.alpha
        self._syncing = False

        self.area = SaturationValueArea()
        self.area.connect("changed", lambda *_args: self._changed_by("area"))

        self.hue = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 360, 1)
        self.hue.set_draw_value(False)
        self.hue.add_css_class("tempera-hue-scale")
        self.hue.update_property([Gtk.AccessibleProperty.LABEL], [_("Hue")])
        self.hue.connect("value-changed", lambda *_args: self._changed_by("hue"))

        self.opacity = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.opacity.set_draw_value(False)
        self.opacity.set_hexpand(True)
        self.opacity.update_property([Gtk.AccessibleProperty.LABEL], [_("Opacity")])
        self.opacity.connect("value-changed", lambda *_args: self._changed_by("opacity"))
        self.opacity_value = Gtk.Label(xalign=1, width_chars=4)
        self.opacity_value.add_css_class("numeric")

        self.preview = ColorPreview()
        self.preview.before = self._original
        self.hex = Gtk.Entry(width_chars=10, max_width_chars=10)
        self.hex.add_css_class("monospace")
        self.hex.update_property([Gtk.AccessibleProperty.LABEL], [_("Hex value")])
        self.hex.connect("activate", lambda *_args: self._take_hex())
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda *_args: self._take_hex())
        self.hex.add_controller(focus)
        self.hex.connect("changed", lambda *_args: self.hex.remove_css_class("error"))
        pick = Gtk.Button(icon_name="tempera-color-picker-symbolic", tooltip_text=_("Pick from the screen"))
        pick.update_property([Gtk.AccessibleProperty.LABEL], [_("Pick from the screen")])
        pick.connect("clicked", lambda *_args: self._pick_from_screen())

        opacity_row = Gtk.Box(spacing=8)
        caption = Gtk.Label(label=_("Opacity"))
        caption.add_css_class("dim-label")
        opacity_row.append(caption)
        opacity_row.append(self.opacity)
        opacity_row.append(self.opacity_value)

        value_row = Gtk.Box(spacing=8)
        value_row.append(self.preview)
        value_row.append(self.hex)
        value_row.append(pick)

        self.custom = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            max_children_per_line=8,
            min_children_per_line=8,
            homogeneous=True,
            row_spacing=4,
            column_spacing=4,
        )
        self.custom.update_property([Gtk.AccessibleProperty.LABEL], [_("Custom colours")])
        custom_caption = Gtk.Label(label=_("Custom Colours"), xalign=0)
        custom_caption.add_css_class("heading")
        self.save_button = Gtk.Button(
            icon_name="tempera-layer-add-symbolic", tooltip_text=_("Keep this colour for later")
        )
        self.save_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Keep this colour for later")])
        self.save_button.add_css_class("flat")
        self.save_button.connect("clicked", lambda *_args: self.keep_color())
        custom_heading = Gtk.Box(spacing=6)
        custom_caption.set_hexpand(True)
        custom_heading.append(custom_caption)
        custom_heading.append(self.save_button)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.add_css_class("tempera-color-editor")
        for widget in (self.area, self.hue, opacity_row, value_row, custom_heading, self.custom):
            content.append(widget)

        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *_args: self.close())
        select = Gtk.Button(label=_("Select"))
        select.add_css_class("suggested-action")
        select.connect("clicked", lambda *_args: self._select())
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(select)
        view = Adw.ToolbarView(content=content)
        view.add_top_bar(header)
        self.set_child(view)
        self.set_default_widget(select)

        self.set_color(color)
        self._refresh_custom()

    # The colour

    @property
    def color(self) -> Gdk.RGBA:
        red, green, blue = colorsys.hsv_to_rgb(self.area.hue, self.area.saturation, self.area.value)
        return Gdk.RGBA(red=red, green=green, blue=blue, alpha=self._alpha)

    def set_color(self, color: Gdk.RGBA) -> None:
        """Show a colour, taking its hue from it only where it has one."""
        hue, saturation, value = colorsys.rgb_to_hsv(color.red, color.green, color.blue)
        if saturation == 0 or value == 0:
            # A grey says nothing about hue: keep the one already chosen.
            hue = self.area.hue
        self._alpha = color.alpha
        self.area.set_hsv(hue, saturation, value)
        self._show(skip=None)

    def _changed_by(self, source: str) -> None:
        if self._syncing:
            return
        if source == "hue":
            self.area.set_hsv(self.hue.get_value() / 360, self.area.saturation, self.area.value)
        elif source == "opacity":
            self._alpha = self.opacity.get_value() / 100
        self._show(skip=source)

    def _show(self, skip: str | None) -> None:
        """Bring every control in line with the colour, but the one it came from."""
        self._syncing = True
        if skip != "hue":
            self.hue.set_value(round(self.area.hue * 360))
        if skip != "opacity":
            self.opacity.set_value(round(self._alpha * 100))
        self._syncing = False
        self.opacity_value.set_label(_("{percent}%").format(percent=round(self._alpha * 100)))
        color = self.color
        if skip != "hex":
            self.hex.set_text(to_hex(color))
            self.hex.remove_css_class("error")
        self.preview.after = color
        self.preview.queue_draw()

    def _take_hex(self) -> None:
        color = parse_hex(self.hex.get_text())
        if color is None:
            self.hex.add_css_class("error")
            return
        if to_hex(color) == to_hex(self.color):
            return
        self.set_color(color)

    def _pick_from_screen(self) -> None:
        def on_color(color: Gdk.RGBA) -> None:
            # The screen has no see-through: the opacity stays as it was.
            color.alpha = self._alpha
            self.set_color(color)

        def on_error(message: str) -> None:
            if self._show_message is not None:
                self._show_message(message)

        pick_screen_color(on_color, on_error)

    def _select(self) -> None:
        self.emit("chosen", self.color)
        self.close()

    # Custom colours

    def keep_color(self) -> None:
        """Put the colour at the front of the custom ones, dropping the oldest past the limit."""
        color = self.color
        kept = [existing for existing in self.colors.custom if not existing.equal(color)]
        self.colors.custom = [color] + kept[: MAX_CUSTOM_COLORS - 1]
        self._refresh_custom()

    def forget_color(self, index: int) -> None:
        del self.colors.custom[index]
        self._refresh_custom()

    def _refresh_custom(self) -> None:
        self.custom.remove_all()
        size = interface_size.scaled(26)
        for index, color in enumerate(self.colors.custom):
            swatch = Swatch(color, size=size, label=_("Custom colour, {color}").format(color=describe(color)))
            swatch.set_tooltip_text(_("{color}. Right-click or press Delete to remove it").format(color=to_hex(color)))
            # Square, rather than stretched to the width of its place in the row.
            swatch.set_halign(Gtk.Align.CENTER)
            swatch.connect("picked", self._on_custom_picked, index)
            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", self._on_custom_key, index)
            swatch.add_controller(keys)
            self.custom.append(swatch)
        self.custom.set_visible(bool(self.colors.custom))

    def _on_custom_picked(self, swatch: Swatch, button: int, index: int) -> None:
        if button == Gdk.BUTTON_SECONDARY:
            self.forget_color(index)
        else:
            self.set_color(swatch.color)

    def _on_custom_key(self, controller, keyval, keycode, state, index: int) -> bool:
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete, Gdk.KEY_BackSpace):
            self.forget_color(index)
            return True
        return False
