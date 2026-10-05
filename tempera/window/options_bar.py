# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The bar of options for the tool in hand."""

from __future__ import annotations

from gi.repository import GLib, Gtk, Pango

from ..color import ColorChip
from ..i18n import _
from ..text import FONT_SIZE_RANGE, TEXT_SWITCHES, font_size, font_without_size, with_font_size
from ..tools import (
    DENSITY_RANGE,
    PICKER_TOOL_ID,
    SELECTION_SHAPE_IDS,
    SHAPE_CLASSES,
    TOOL_CLASSES,
    WAND_TOOL_ID,
)

# The one size slider serves the brush and, with the text tool up, the font.
BRUSH_SIZE_RANGE = (1, 64)
# The sizes offered beside the size, as a word processor offers them for
# text, and in steps that grow with the brush for the tools that paint.
FONT_SIZE_PRESETS = (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 60, 72, 96, 120, 144, 200)
BRUSH_SIZE_PRESETS = (1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 64)
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
        # The chips on the Transparent toggles, in the colour they leave out.
        self._left_out_chips: list[ColorChip] = []

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
        self._size_section.append(self._build_size_field())
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
        # The outline as dashes or dots, arrowheads at one end or both, and
        # smooth edges or crisp ones for pixel art.
        line_styles = self._choice_row(
            "win.line-style",
            (
                ("solid", "tempera-line-solid-symbolic", "Solid Outline"),
                ("dashed", "tempera-line-dashed-symbolic", "Dashed Outline"),
                ("dotted", "tempera-line-dotted-symbolic", "Dotted Outline"),
            ),
        )
        self._arrow_ends = self._choice_row(
            "win.arrow-ends",
            (
                ("end", "tempera-arrow-end-symbolic", "Arrowhead at the End"),
                ("both", "tempera-arrow-both-symbolic", "Arrowheads at Both Ends"),
            ),
        )
        edges = self._choice_row(
            "win.shape-edges",
            (
                ("smooth", "tempera-smooth-edges-symbolic", "Smooth Edges"),
                ("crisp", "tempera-crisp-edges-symbolic", "Crisp Edges"),
            ),
        )
        self._arrow_ends_separator = _bar_separator()
        self._add_page(
            "shape",
            _row(
                self._outline_toggle,
                self._fill_toggle,
                _bar_separator(),
                line_styles,
                self._arrow_ends_separator,
                self._arrow_ends,
                _bar_separator(),
                edges,
            ),
        )
        self.colors.connect("changed", lambda *_args: self._sync_color_chips())

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

        # The two ways of drawing a selection share one button in the sidebar;
        # here is where one is picked over the other.
        selection_shapes = Gtk.Box(valign=Gtk.Align.CENTER)
        selection_shapes.add_css_class("linked")
        selection_shapes.add_css_class("tempera-shape-picker")
        for tool in TOOL_CLASSES:
            if tool.id in SELECTION_SHAPE_IDS:
                button = Gtk.ToggleButton(icon_name=tool.icon_name)
                button.add_css_class("tempera-option-toggle")
                self._add_shortcut_tooltip(button, tool.label, f"win.tool::{tool.id}")
                button.set_action_name("win.tool")
                button.set_action_target_value(GLib.Variant.new_string(tool.id))
                selection_shapes.append(button)
        self._add_page("select", _row(selection_shapes, _bar_separator(), self._transparent_toggle()))

        self._wand_tolerance_scale, wand_value = self._option_scale(
            TOLERANCE_RANGE,
            self.canvas.wand_tolerance,
            lambda scale: setattr(self.canvas, "wand_tolerance", int(scale.get_value())),
        )
        self._wand_tolerance_scale.set_tooltip_text(
            _("How far the selection spreads into colours near the one you clicked")
        )
        self._wand_tolerance_scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Tolerance")])
        self._add_page(
            "wand",
            _row(
                _caption(_("Tolerance")),
                self._wand_tolerance_scale,
                wand_value,
                _bar_separator(),
                self._transparent_toggle(),
            ),
        )

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

        # How the text looks: each button also answers to its key.
        styles = Gtk.Box(valign=Gtk.Align.CENTER)
        styles.add_css_class("linked")
        for markup, text, action in (
            ("<b>B</b>", "Bold", "win.text-bold"),
            ("<i>I</i>", "Italic", "win.text-italic"),
            ("<u>U</u>", "Underline", "win.text-underline"),
            ("<s>S</s>", "Strikethrough", "win.text-strikethrough"),
        ):
            button = Gtk.ToggleButton(child=Gtk.Label(label=markup, use_markup=True))
            button.add_css_class("tempera-option-toggle")
            button.add_css_class("tempera-text-style")
            self._add_shortcut_tooltip(button, text, action)
            button.set_action_name(action)
            styles.append(button)
        alignment = Gtk.Box(valign=Gtk.Align.CENTER)
        alignment.add_css_class("linked")
        for value, text in (("left", "Align Left"), ("center", "Center"), ("right", "Align Right")):
            button = Gtk.ToggleButton(icon_name=f"tempera-align-{value}-symbolic")
            button.add_css_class("tempera-option-toggle")
            self._add_shortcut_tooltip(button, text, f"win.text-align::{value}")
            button.set_action_name("win.text-align")
            button.set_action_target_value(GLib.Variant.new_string(value))
            alignment.append(button)
        # The box behind the text wears the colour it is filled with.
        self._background_chip = ColorChip(filled=True)
        background = self._option_toggle(
            _("Background"), self._background_chip, _("Put the text on a box of the secondary colour")
        )
        background.set_action_name("win.text-background")
        # The picker takes colours off the canvas; this takes one off anywhere
        # on the screen, other windows too.
        from_screen = Gtk.Button(valign=Gtk.Align.CENTER)
        from_screen_content = Gtk.Box(spacing=8)
        from_screen_content.append(Gtk.Image(icon_name="tempera-color-picker-symbolic"))
        from_screen_content.append(Gtk.Label(label=_("Pick from Screen")))
        from_screen.set_child(from_screen_content)
        from_screen.set_tooltip_text(_("Take the primary colour from anywhere on the screen"))
        from_screen.set_action_name("win.pick-from-screen")
        self._add_page("picker", from_screen)

        self._add_page(
            "text",
            _row(
                self._font_button,
                _bar_separator(),
                styles,
                _bar_separator(),
                alignment,
                _bar_separator(),
                background,
            ),
        )

        self._sync_color_chips()
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

    def _choice_row(self, action: str, choices) -> Gtk.Box:
        """Linked buttons, one for each value of a stateful action; the one it holds is pressed."""
        row = Gtk.Box(valign=Gtk.Align.CENTER)
        row.add_css_class("linked")
        for value, icon, text in choices:
            button = Gtk.ToggleButton(icon_name=icon)
            button.add_css_class("tempera-option-toggle")
            self._add_shortcut_tooltip(button, text, f"{action}::{value}")
            button.set_action_name(action)
            button.set_action_target_value(GLib.Variant.new_string(value))
            row.append(button)
        return row

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

    def _build_size_field(self) -> Gtk.Widget:
        """The size as a number to type, with a list of the usual ones beside it, and its unit."""
        self._size_entry = Gtk.Entry(
            width_chars=3,
            max_width_chars=4,
            xalign=1,
            input_purpose=Gtk.InputPurpose.DIGITS,
            valign=Gtk.Align.CENTER,
        )
        self._size_entry.add_css_class("numeric")
        self._size_entry.update_property([Gtk.AccessibleProperty.LABEL], [_("Size")])
        self._size_entry.connect("activate", lambda *_args: self._take_typed_size(done=True))
        leaving = Gtk.EventControllerFocus()
        leaving.connect("leave", lambda *_args: self._take_typed_size())
        self._size_entry.add_controller(leaving)

        self._size_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self._size_list.add_css_class("tempera-size-list")
        self._size_list.connect("row-activated", self._on_size_preset)
        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            max_content_height=320,
            propagate_natural_height=True,
            propagate_natural_width=True,
        )
        scroller.set_child(self._size_list)
        popover = Gtk.Popover(child=scroller)
        popover.connect("show", lambda *_args: self._select_size_preset())
        self._size_presets = Gtk.MenuButton(
            icon_name="pan-down-symbolic", popover=popover, valign=Gtk.Align.CENTER
        )
        self._size_presets.set_tooltip_text(_("Common sizes"))
        self._size_presets.update_property([Gtk.AccessibleProperty.LABEL], [_("Common sizes")])

        field = Gtk.Box(valign=Gtk.Align.CENTER)
        field.add_css_class("linked")
        field.append(self._size_entry)
        field.append(self._size_presets)
        self._size_unit = Gtk.Label(valign=Gtk.Align.CENTER)
        self._size_unit.add_css_class("dim-label")
        box = Gtk.Box(spacing=6)
        box.append(field)
        box.append(self._size_unit)
        return box

    def _take_typed_size(self, done: bool = False) -> None:
        """Take the size typed in, kept within what the slider reaches; anything else puts back the size.

        Enter says the typing is `done`, and hands the keys back to the canvas.
        """
        if done:
            self.canvas.grab_focus()
        text = self._size_entry.get_text().strip().lower().removesuffix("pt").removesuffix("px").strip()
        try:
            size = int(float(text))
        except ValueError:
            self._show_size(int(self._size_adjustment.get_value()))
            return
        low, high = self._size_adjustment.get_lower(), self._size_adjustment.get_upper()
        size = int(max(low, min(size, high)))
        if size == int(self._size_adjustment.get_value()):
            self._show_size(size)
        else:
            self._size_adjustment.set_value(size)

    def _fill_size_presets(self) -> None:
        """The usual sizes for what the slider serves now: text or a brush."""
        self._size_list.remove_all()
        text = self.canvas.supports_font
        unit = _("pt") if text else _("px")
        self._size_choices = FONT_SIZE_PRESETS if text else BRUSH_SIZE_PRESETS
        for size in self._size_choices:
            label = Gtk.Label(label=_("{size} {unit}").format(size=size, unit=unit), xalign=1)
            label.add_css_class("numeric")
            self._size_list.append(label)

    def _select_size_preset(self) -> None:
        """Show which of the usual sizes is the one now, if it is one of them."""
        current = int(self._size_adjustment.get_value())
        self._size_list.unselect_all()
        if current in self._size_choices:
            self._size_list.select_row(self._size_list.get_row_at_index(self._size_choices.index(current)))

    def _on_size_preset(self, listbox, row: Gtk.ListBoxRow) -> None:
        self._size_presets.popdown()
        self._size_adjustment.set_value(self._size_choices[row.get_index()])

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
        self._fill_size_presets()

    def _show_size(self, size: int) -> None:
        self._size_entry.set_text(str(size))
        self._size_unit.set_label(_("pt") if self.canvas.supports_font else _("px"))

    def _transparent_toggle(self) -> Gtk.ToggleButton:
        """Transparent selection, for the options of each selection tool; they share one setting."""
        chip = ColorChip(filled=True)
        self._left_out_chips.append(chip)
        button = self._option_toggle(
            _("Transparent"), chip, _("Leave the secondary colour out of what is moved or pasted")
        )
        button.set_action_name("win.transparent-selection")
        return button

    def _sync_color_chips(self) -> None:
        self._outline_chip.color = self.colors.primary
        self._fill_chip.color = self.colors.secondary
        for chip in self._left_out_chips:
            chip.color = self.colors.secondary
        self._background_chip.color = self.colors.secondary

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
        # Only an arrow has heads.
        arrow = canvas.shapes.shape.id == "arrow"
        self._arrow_ends.set_visible(arrow)
        self._arrow_ends_separator.set_visible(arrow)

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
        elif canvas.active_tool.id in SELECTION_SHAPE_IDS:
            page = "select"
        elif canvas.active_tool.id == WAND_TOOL_ID:
            page = "wand"
        elif canvas.active_tool.id == PICKER_TOOL_ID:
            page = "picker"
        self._tool_options.set_visible_child_name(page)
        # Ctrl+B with a brush in hand would otherwise restyle, unseen, the next text typed.
        for name in (*(f"text-{switch}" for switch in TEXT_SWITCHES), "text-align"):
            action = self.lookup_action(name)
            # Laid out before the actions exist, the first time round.
            if action is not None:
                action.set_enabled(canvas.supports_font)

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
