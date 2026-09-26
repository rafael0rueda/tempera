# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The panels around the canvas: tools, palette and status bar."""

from __future__ import annotations

from gi.repository import Gdk, GLib, Gtk

from .. import interface_size
from ..canvas import CanvasFrame
from ..color import PaletteLayout
from ..i18n import _
from ..settings import PALETTE_POSITIONS, save_palette_position
from ..tool_icon import ToolIcon
from ..tools import TOOL_CLASSES
from .layers_panel import LayersPanel

# Sizes of the panels and bars, given for the default interface size and
# scaled with it. The sidebar is fixed, so switching tools never moves the
# canvas sideways.
SIDEBAR_WIDTH = 96
OPTIONS_BAR_HEIGHT = 44
STATUS_BAR_HEIGHT = 32
PALETTE_BAR_HEIGHT = 56
PALETTE_COLUMN_WIDTH = 72
LAYERS_PANEL_WIDTH = 232
OPTION_SCALE_WIDTH = 120


class LayoutMixin:
    """The tools, the canvas area, the palette wherever it is put, and the status bar."""

    def _build_body(self) -> Gtk.Widget:
        """Under the header: the tool options, the tools, canvas and palette, then the status bar.

        The bars are part of the content rather than toolbar-view bars, which
        would paint them the header's colour.
        """
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(self._build_options_bar())
        body.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        body.append(self._build_content())
        body.append(self._build_palette_bar())
        body.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        body.append(self._build_status_bar())
        return body

    def _build_content(self) -> Gtk.Widget:
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
        content.append(self._build_sidebar())
        content.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self._canvas_area = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self._canvas_area.add_css_class("tempera-canvas-area")
        self._canvas_area.set_child(CanvasFrame(self.canvas))
        # Middle-drag to pan and pinch to zoom belong to the scrolling area.
        self.canvas.attach_to_viewport(self._canvas_area)
        content.append(self._canvas_area)

        content.append(self._build_palette_column())

        # The layers, at the far right, shown or hidden from the header.
        self._layers_panel = LayersPanel(self.canvas, self._add_shortcut_tooltip)
        self._layers_strip = Gtk.Box(visible=False)
        self._layers_strip.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        self._layers_strip.append(self._layers_panel)
        content.append(self._layers_strip)
        return content

    def _build_palette_column(self) -> Gtk.Widget:
        """A column right of the canvas for the palette, hidden while it is elsewhere.

        It scrolls, like the sidebar, when the window is too short for it.
        """
        slot = Gtk.Box(halign=Gtk.Align.FILL)
        slot.add_css_class("tempera-palette-column")
        self._palette_column = slot
        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            propagate_natural_width=True,
        )
        scroller.set_child(slot)
        strip = Gtk.Box(visible=False)
        strip.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        strip.append(scroller)
        self._palette_slots["right"] = (slot, strip)
        return strip

    def _build_palette_bar(self) -> Gtk.Widget:
        """A row under the canvas for the palette, hidden while it is elsewhere.

        It scrolls sideways rather than hold the window wider than the screen
        at a big interface size.
        """
        slot = Gtk.Box()
        slot.add_css_class("tempera-palette-bar")
        self._palette_bar = slot
        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
        )
        scroller.set_child(slot)
        strip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, visible=False)
        strip.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        strip.append(scroller)
        self._palette_slots["bottom"] = (slot, strip)
        return strip

    def _build_status_bar(self) -> Gtk.Widget:
        bar = Gtk.Box(spacing=16)
        bar.add_css_class("tempera-status-bar")
        self._status_bar = bar

        self._cursor_label = Gtk.Label(xalign=0)
        # How big the selection is, beside the pointer position.
        self._selection_label = Gtk.Label(xalign=0, hexpand=True)
        for label in (self._cursor_label, self._selection_label):
            label.add_css_class("numeric")
            label.add_css_class("dim-label")
            bar.append(label)

        # The size is also the header's subtitle, which renders too small to
        # read at larger interface font sizes; here it also opens Canvas Size.
        self._canvas_size_label = Gtk.Label()
        self._canvas_size_label.add_css_class("numeric")
        self._canvas_size_label.add_css_class("dim-label")
        button = Gtk.Button(child=self._canvas_size_label, valign=Gtk.Align.CENTER)
        self._add_shortcut_tooltip(button, "Canvas size", "win.resize")
        button.add_css_class("flat")
        button.add_css_class("tempera-status-button")
        button.set_action_name("win.resize")
        bar.append(button)

        zoom = Gtk.Box(spacing=2, valign=Gtk.Align.CENTER)
        self._zoom_label = Gtk.Label()
        self._zoom_label.add_css_class("numeric")
        # Wide enough for "800%", so the buttons either side stay put.
        self._zoom_label.set_width_chars(5)
        zoom_button = Gtk.Button(child=self._zoom_label)
        self._add_shortcut_tooltip(zoom_button, "Reset zoom", "win.zoom-reset")
        zoom_button.set_action_name("win.zoom-reset")
        # Scrolling over the zoom level steps through the zoom presets. Discrete,
        # so a touchpad swipe moves one level at a time rather than racing.
        zoom_scroll = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL
            | Gtk.EventControllerScrollFlags.DISCRETE
        )
        zoom_scroll.connect("scroll", self._on_zoom_label_scroll)
        zoom_button.add_controller(zoom_scroll)
        for widget, icon, text, action in (
            (Gtk.Button(), "tempera-zoom-out-symbolic", "Zoom out", "win.zoom-out"),
            (zoom_button, None, None, None),
            (Gtk.Button(), "tempera-zoom-in-symbolic", "Zoom in", "win.zoom-in"),
        ):
            if icon is not None:
                widget.set_icon_name(icon)
                self._add_shortcut_tooltip(widget, text, action)
                widget.set_action_name(action)
            widget.add_css_class("flat")
            widget.add_css_class("tempera-status-button")
            zoom.append(widget)
        bar.append(zoom)
        self._on_zoom_changed(self.canvas, self.canvas.zoom)
        return bar

    def _build_sidebar(self) -> Gtk.Widget:
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        sidebar.add_css_class("tempera-sidebar")
        self._sidebar = sidebar

        tools = Gtk.Grid(row_spacing=4, column_spacing=4, halign=Gtk.Align.CENTER)
        for index, tool in enumerate(TOOL_CLASSES):
            button = Gtk.ToggleButton(child=ToolIcon(tool.icon_name, tool.tip_icon_name, self.colors))
            self._add_shortcut_tooltip(button, tool.label, f"win.tool::{tool.id}")
            button.add_css_class("flat")
            button.add_css_class("tempera-tool")
            button.set_action_name("win.tool")
            button.set_action_target_value(GLib.Variant.new_string(tool.id))
            tools.attach(button, index % 2, index // 2, 1, 1)
        sidebar.append(tools)

        # The palette's place when it is on the left: under the tools.
        left_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, visible=False)
        left_section.append(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, margin_start=8, margin_end=8)
        )
        left_slot = Gtk.Box(halign=Gtk.Align.CENTER)
        left_section.append(left_slot)
        sidebar.append(left_section)
        self._palette_slots["left"] = (left_slot, left_section)

        # Scrolls rather than squeezing when the window is too short for it all,
        # which the palette makes likelier.
        scrolled = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            propagate_natural_width=True,
        )
        scrolled.set_child(sidebar)
        return scrolled

    def _on_palette_position_changed(self, action, value: GLib.Variant) -> None:
        position = value.get_string()
        if position not in PALETTE_POSITIONS:
            return
        action.set_state(value)
        self._place_palette(position)
        save_palette_position(position)

    def _place_palette(self, position: str) -> None:
        parent = self._color_bar.get_parent()
        if parent is not None:
            parent.remove(self._color_bar)
        for name, (_slot, strip) in self._palette_slots.items():
            strip.set_visible(name == position)
        slot, _strip = self._palette_slots[position]
        slot.append(self._color_bar)
        self._color_bar.set_layout(
            {
                "bottom": PaletteLayout.WIDE,
                "left": PaletteLayout.BLOCK,
                "right": PaletteLayout.NARROW,
            }[position]
        )
        self._palette_position = position

    def sync_interface_size(self) -> None:
        """Size what is set in code rather than by the stylesheets."""
        scaled = interface_size.scaled
        self._sidebar.set_size_request(scaled(SIDEBAR_WIDTH), -1)
        self._palette_column.set_size_request(scaled(PALETTE_COLUMN_WIDTH), -1)
        self._layers_panel.set_size_request(scaled(LAYERS_PANEL_WIDTH), -1)
        self._layers_panel.sync_interface_size()
        self._options_bar.set_size_request(-1, scaled(OPTIONS_BAR_HEIGHT))
        self._palette_bar.set_size_request(-1, scaled(PALETTE_BAR_HEIGHT))
        self._status_bar.set_size_request(-1, scaled(STATUS_BAR_HEIGHT))
        # The sliders keep their length, only their knobs grow, so the options
        # bar still fits a normal window at a bigger size.
        for scale in (self._size_scale, self._tolerance_scale, self._density_scale):
            scale.set_size_request(OPTION_SCALE_WIDTH, -1)
        self._color_bar.sync_size()
        self.canvas.sync_interface_size()

    def _on_resize_preview(self, canvas, width: int, height: int) -> None:
        """Count out the pending size while a resize grip is being dragged."""
        self._show_canvas_size(width, height)

    def _show_canvas_size(self, width: int, height: int) -> None:
        self._title.set_subtitle(_("{width} × {height}").format(width=width, height=height))
        self._canvas_size_label.set_label(_("{width} × {height} px").format(width=width, height=height))

    def _on_zoom_label_scroll(self, controller, dx: float, dy: float) -> bool:
        if dy < 0:
            self.canvas.zoom_in()
        elif dy > 0:
            self.canvas.zoom_out()
        return Gdk.EVENT_STOP

    def _on_zoom_changed(self, canvas, zoom: float) -> None:
        for label in (self._zoom_label, self._menu_zoom_label):
            label.set_label(f"{round(zoom * 100)}%")

    def _on_pointer_moved(self, canvas, x: float, y: float) -> None:
        self._cursor_label.set_label(_("{x}, {y}").format(x=round(x), y=round(y)))
        self._cursor_label.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("Pointer at {x}, {y} pixels").format(x=round(x), y=round(y))],
        )

    def _show_selection_size(self) -> None:
        size = self.canvas.selection_size
        self._selection_label.set_label(
            "" if size is None else _("Selection {width} × {height}").format(
                width=size[0], height=size[1]
            )
        )
