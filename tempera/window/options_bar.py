# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The bar of options for the tool in hand."""

from __future__ import annotations

from gi.repository import GLib, Gtk, Pango

from ..color import ColorChip
from ..i18n import _
from ..text import FONT_SIZE_RANGE, font_size, font_without_size, with_font_size
from ..tools import DENSITY_RANGE, SHAPE_CLASSES

# The one size slider serves the brush and, with the text tool up, the font.
BRUSH_SIZE_RANGE = (1, 64)
# 0 fills only the exact colour clicked; the top end spreads across most shades.
TOLERANCE_RANGE = (0, 128)


def _bar_separator() -> Gtk.Separator:
    """A short upright line between groups of options in a bar."""
    return Gtk.Separator(
        orientation=Gtk.Orientation.VERTICAL,
        margin_top=12,
        margin_bottom=12,
        margin_start=6,
        margin_end=6,
    )


def _row(*widgets: Gtk.Widget) -> Gtk.Box:
    box = Gtk.Box(spacing=6)
    for widget in widgets:
        box.append(widget)
    return box


def _caption(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text)
    label.add_css_class("dim-label")
    return label


class ToolOptionsMixin:
    """The options bar, which shows only what applies to the tool in hand."""

    def _build_options_bar(self) -> Gtk.Widget:
        """The options of the tool in hand, in one row that changes with the tool."""
        bar = Gtk.Box(spacing=6)
        bar.add_css_class("tempera-options-bar")
        self._options_bar = bar

        self._tool_label = Gtk.Label(xalign=0, margin_end=6)
        self._tool_label.add_css_class("heading")
        bar.append(self._tool_label)

        # Picking a shape here, or with its key, also takes up the Shapes tool.
        self._shape_picker = Gtk.Box(valign=Gtk.Align.CENTER)
        self._shape_picker.add_css_class("linked")
        self._shape_picker.add_css_class("tempera-shape-picker")
        for shape in SHAPE_CLASSES:
            button = Gtk.ToggleButton(icon_name=shape.icon_name)
            button.add_css_class("tempera-option-toggle")
            self._add_shortcut_tooltip(button, shape.label, f"win.shape::{shape.id}")
            button.set_action_name("win.shape")
            button.set_action_target_value(GLib.Variant.new_string(shape.id))
            self._shape_picker.append(button)
        bar.append(self._shape_picker)

        # One size for every tool that has one: a brush or line width, or with
        # the text tool the font size. The slider and the box share one value.
        self._size_section = Gtk.Box(spacing=6)
        self._size_section.append(_bar_separator())
        self._size_section.append(_caption(_("Size")))
        self._size_adjustment = Gtk.Adjustment(
            value=self.canvas.brush_size,
            lower=BRUSH_SIZE_RANGE[0],
            upper=BRUSH_SIZE_RANGE[1],
            step_increment=1,
            page_increment=4,
        )
        self._size_scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            adjustment=self._size_adjustment,
            draw_value=False,
            valign=Gtk.Align.CENTER,
        )
        self._size_scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Size")])
        self._size_section.append(self._size_scale)
        # The value and its unit, in a box of their own; the slider says it
        # to a screen reader.
        self._size_value = Gtk.Label(valign=Gtk.Align.CENTER, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self._size_value.add_css_class("numeric")
        self._size_value.add_css_class("tempera-option-value")
        self._size_section.append(self._size_value)
        self._size_adjustment.connect("value-changed", self._on_size_changed)
        bar.append(self._size_section)

        # Each tool's own options, after the size.
        self._tool_options = Gtk.Stack(hhomogeneous=False, vhomogeneous=False)
        self._tool_options.add_named(Gtk.Box(), "none")
        bar.append(self._tool_options)

        # Outline and fill are separate, so a shape can be all fill. They wear
        # the colours they draw in: the primary for the outline, the secondary
        # for the fill.
        self._outline_chip = ColorChip(filled=False)
        self._outline_toggle = self._option_toggle(
            _("Outline"), self._outline_chip, _("Draw the outline, in the primary colour")
        )
        self._outline_toggle.set_active(True)
        self._outline_toggle.connect("toggled", self._on_outline_toggled)
        self._fill_chip = ColorChip(filled=True)
        self._fill_toggle = self._option_toggle(
            _("Fill"), self._fill_chip, _("Fill the inside, in the secondary colour")
        )
        self._fill_toggle.connect("toggled", self._on_fill_toggled)
        self._syncing_shape_options = False
        self._add_page("shape", _row(self._outline_toggle, self._fill_toggle))
        self.colors.connect("changed", lambda *_args: self._sync_color_chips())
        self._sync_color_chips()

        self._erase_check = Gtk.CheckButton(label=_("Erase to nothing"))
        self._erase_check.set_tooltip_text(
            _("Rub back to nothing instead of the secondary colour")
        )
        self._erase_check.connect(
            "toggled", lambda check: setattr(self.canvas, "erase_to_transparency", check.get_active())
        )
        self._add_page("eraser", self._erase_check)

        self._tolerance_scale, self._tolerance_value = self._option_scale(
            TOLERANCE_RANGE, self.canvas.fill_tolerance, self._on_tolerance_changed
        )
        self._add_page(
            "fill", _row(_caption(_("Tolerance")), self._tolerance_scale, self._tolerance_value)
        )
        self._tolerance_scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Tolerance")])
        self._show_tolerance(self.canvas.fill_tolerance)

        self._density_scale, density_value = self._option_scale(
            DENSITY_RANGE,
            self.canvas.airbrush_density,
            lambda scale: setattr(self.canvas, "airbrush_density", int(scale.get_value())),
        )
        self._density_scale.set_tooltip_text(_("How thickly the airbrush sprays"))
        self._density_scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Density")])
        self._add_page("airbrush", _row(_caption(_("Density")), self._density_scale, density_value))

        # The button names the typeface; the size is the one before it.
        self._font_label = Gtk.Label(label=font_without_size(self.canvas.font))
        self._font_label.set_ellipsize(Pango.EllipsizeMode.END)
        self._font_label.set_max_width_chars(20)
        self._font_button = Gtk.Button(
            child=self._font_label,
            tooltip_text=_("Typeface for the text tool"),
            valign=Gtk.Align.CENTER,
        )
        self._font_button.update_property(
            [Gtk.AccessibleProperty.DESCRIPTION], [_("Typeface for the text tool")]
        )
        self._font_button.connect("clicked", self._choose_font)
        self._add_page("text", self._font_button)

        self._sync_size_scale()

        # Scrolls sideways rather than hold the window wider than the screen,
        # which the shapes and a big interface size would otherwise do.
        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
        )
        scroller.set_child(bar)
        return scroller

    def _add_page(self, name: str, options: Gtk.Widget) -> None:
        """One tool's options, set off from the size before them by a line."""
        options.set_valign(Gtk.Align.CENTER)
        page = Gtk.Box(spacing=6)
        page.append(_bar_separator())
        page.append(options)
        self._tool_options.add_named(page, name)

    @staticmethod
    def _option_toggle(text: str, chip: Gtk.Widget, tooltip: str) -> Gtk.ToggleButton:
        content = Gtk.Box(spacing=8)
        content.append(chip)
        content.append(Gtk.Label(label=text))
        button = Gtk.ToggleButton(child=content, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
        button.add_css_class("tempera-option-toggle")
        button.update_property([Gtk.AccessibleProperty.LABEL], [text])
        return button

    @staticmethod
    def _option_scale(limits, value, on_changed) -> tuple[Gtk.Scale, Gtk.Label]:
        """A slider for a tool option, with its value written beside it."""
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, *limits, 1)
        scale.set_value(value)
        scale.set_draw_value(False)
        scale.set_valign(Gtk.Align.CENTER)
        shown = Gtk.Label(label=str(int(value)), xalign=1)
        shown.add_css_class("numeric")
        # Wide enough for the largest value, so the bar does not jiggle.
        shown.set_width_chars(len(str(limits[1])))

        def changed(scale: Gtk.Scale) -> None:
            shown.set_label(str(int(scale.get_value())))
            on_changed(scale)

        scale.connect("value-changed", changed)
        return scale, shown

    def _step_size(self, step: int) -> None:
        """[ and ]: a bigger or smaller brush, or bigger or smaller text."""
        self._size_adjustment.set_value(self._size_adjustment.get_value() + step)

    def _on_size_changed(self, adjustment: Gtk.Adjustment) -> None:
        if self._syncing_size:
            return
        size = int(adjustment.get_value())
        if self.canvas.supports_font:
            self.canvas.set_font(with_font_size(self.canvas.font, size))
        else:
            self.canvas.brush_size = size
        self._show_size(size)

    def _sync_size_scale(self) -> None:
        """Hand the slider over to the font while the text tool is selected."""
        text = self.canvas.supports_font
        size = font_size(self.canvas.font) if text else self.canvas.brush_size
        # Moving the range moves the value with it, which would write the brush
        # size into the font and back again.
        self._syncing_size = True
        low, high = FONT_SIZE_RANGE if text else BRUSH_SIZE_RANGE
        self._size_adjustment.configure(size, low, high, 1, 4, 0)
        self._syncing_size = False
        self._show_size(size)

    def _show_size(self, size: int) -> None:
        unit = _("pt") if self.canvas.supports_font else _("px")
        self._size_value.set_label(_("{size} {unit}").format(size=size, unit=unit))

    def _sync_color_chips(self) -> None:
        self._outline_chip.color = self.colors.primary
        self._fill_chip.color = self.colors.secondary

    def _sync_shape_options(self) -> None:
        """Show what the shape in hand will draw: a line is all outline, whatever is set."""
        canvas = self.canvas
        fillable = canvas.shapes.fillable
        self._syncing_shape_options = True
        self._outline_toggle.set_active(canvas.outline_shapes or not fillable)
        self._fill_toggle.set_active(canvas.fill_shapes and fillable)
        self._outline_toggle.set_sensitive(fillable)
        self._fill_toggle.set_sensitive(fillable)
        self._syncing_shape_options = False

    def _on_outline_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._syncing_shape_options:
            return
        self.canvas.outline_shapes = button.get_active()
        # A shape needs one or the other to show at all.
        if not button.get_active() and not self.canvas.fill_shapes:
            self._fill_toggle.set_active(True)

    def _on_fill_toggled(self, button: Gtk.ToggleButton) -> None:
        if self._syncing_shape_options:
            return
        self.canvas.fill_shapes = button.get_active()
        if not button.get_active() and not self.canvas.outline_shapes:
            self._outline_toggle.set_active(True)

    def _on_tolerance_changed(self, scale: Gtk.Scale) -> None:
        self.canvas.fill_tolerance = int(scale.get_value())
        self._show_tolerance(self.canvas.fill_tolerance)

    def _show_tolerance(self, tolerance: int) -> None:
        self._tolerance_scale.set_tooltip_text(
            _("How far a fill spreads into colours near the one you clicked: {value}").format(
                value=tolerance
            )
        )

    def _sync_tool_options(self) -> None:
        """Show the options belonging to the tool in hand, and none of the others."""
        canvas = self.canvas
        self._tool_label.set_label(canvas.active_tool.label)
        self._shape_picker.set_visible(canvas.supports_fill)
        self._size_section.set_visible(canvas.active_tool.sized)
        page = "none"
        if canvas.supports_fill:
            page = "shape"
            self._sync_shape_options()
        elif canvas.supports_erase_mode:
            page = "eraser"
        elif canvas.supports_tolerance:
            page = "fill"
        elif canvas.supports_density:
            page = "airbrush"
        elif canvas.supports_font:
            page = "text"
        self._tool_options.set_visible_child_name(page)

    def _choose_font(self, *_args) -> None:
        dialog = Gtk.FontDialog(title=_("Text font"))

        def on_done(source, result):
            try:
                description = source.choose_font_finish(result)
            except GLib.Error:
                return
            font = description.to_string()
            self._font_label.set_label(font_without_size(font))
            self.canvas.set_font(font)
            # The dialog carries a size of its own; the slider follows it.
            self._sync_size_scale()

        dialog.choose_font(self, Pango.FontDescription(self.canvas.font), None, on_done)
