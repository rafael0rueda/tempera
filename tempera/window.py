# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from . import APP_NAME, interface_size, printing, recovery, shortcuts
from .canvas import PIXEL_GRID_ZOOM, Canvas, CanvasFrame
from .clipboard import has_image, read_image, texture_from_surface
from .color import MAX_RECENT_COLORS, ColorBar, ColorState, PaletteLayout, Swatch, describe, rgba
from .document import DEFAULT_HEIGHT, DEFAULT_WIDTH, MAX_SIZE, Document, new_surface
from .i18n import _
from .file_io import (
    format_for,
    image_filters,
    load_document_async,
    save_as_name,
    save_document_async,
    with_default_extension,
)
from .recent_files import clear_recent, forget_recent, load_recent, remember_recent
from .settings import (
    PALETTE_POSITIONS,
    load_palette_position,
    load_setting,
    save_palette_position,
    save_settings,
)
from .preferences import PreferencesDialog
from .shortcuts_dialog import ShortcutsDialog
from .text import FONT_SIZE_RANGE, font_size, font_without_size, with_font_size
from .tools import (
    DEFAULT_SHAPE,
    DENSITY_RANGE,
    SHAPE_CLASSES,
    SHAPE_IDS,
    SHAPES_TOOL_ID,
    TOOL_CLASSES,
)

# Actions that edit or replace the image, or like Print land what is floating
# on it. A stroke, move or resize in progress holds on to the image it started
# on, so these wait until the button is let go.
IMAGE_ACTIONS = {
    "new",
    "print",
    "open",
    "undo",
    "redo",
    "select-all",
    "cut",
    "paste",
    "resize",
    "scale",
    "crop",
    "rotate-cw",
    "rotate-ccw",
    "flip-horizontal",
    "flip-vertical",
}

# The one size slider serves the brush and, with the text tool up, the font.
BRUSH_SIZE_RANGE = (1, 64)
# 0 fills only the exact colour clicked; the top end spreads across most shades.
TOLERANCE_RANGE = (0, 128)
# Wide enough for the palette block and the tool grid, and fixed, so that
# switching tools never moves the canvas sideways. Given for the default
# interface size, like the bottom bar's height.
SIDEBAR_WIDTH = 128
BOTTOM_BAR_HEIGHT = 60
WHITE = (1.0, 1.0, 1.0, 1.0)
TRANSPARENT = (0.0, 0.0, 0.0, 0.0)


def _option_check(text: str) -> Gtk.CheckButton:
    """A tool option whose label wraps rather than widening the sidebar."""
    label = Gtk.Label(label=text, wrap=True, xalign=0)
    # Two shortish lines rather than one long one, so that the widest option
    # does not set the width of the whole sidebar.
    label.set_max_width_chars(9)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    check = Gtk.CheckButton()
    check.set_child(label)
    check.update_property([Gtk.AccessibleProperty.LABEL], [text])
    return check


def _whole(text: str, fallback: int, limits: tuple[int, int] | None = None) -> int:
    """A remembered number, ignoring anything a damaged settings file may hold."""
    try:
        value = int(text)
    except ValueError:
        return fallback
    if limits is not None:
        value = max(limits[0], min(value, limits[1]))
    return value


def scaled_side(original: int, percent: float) -> int:
    """One side of the image at a percentage of its size, within what a canvas can hold."""
    return max(1, min(round(original * percent / 100), MAX_SIZE))


class TemperaWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application, document: Document | None = None):
        super().__init__(application=application, title=APP_NAME)
        self.set_size_request(640, 480)

        self.colors = ColorState()
        self._restore_window_size()
        self.canvas = Canvas(document or Document(), self.colors)
        self.canvas.connect("color-picked", self._on_color_picked)
        self.canvas.connect("resize-preview", self._on_resize_preview)
        self.canvas.connect("floating-changed", self._on_floating_changed)
        self.canvas.connect("selection-changed", lambda *_args: self._sync_selection_actions())
        self.canvas.connect("selection-changed", lambda *_args: self._show_selection_size())
        self.canvas.connect("zoom-changed", self._on_zoom_changed)
        self.canvas.connect("pointer-moved", self._on_pointer_moved)
        self.canvas.connect("pointer-left", lambda *_args: self._cursor_label.set_label(""))
        self.canvas.connect("message", lambda _canvas, message: self.show_toast(message))
        self._closing = False
        # A copy of unsaved work in Tempera's data folder, so a crash does not
        # lose it. Counting changes tells whether the last copy is out of date.
        self._recovery = recovery.RecoverySlot()
        self._changes = 0
        self._kept_changes: int | None = None
        self._recovery_timer = GLib.timeout_add_seconds(
            recovery.INTERVAL, self._keep_recovery_copy
        )
        # Ended when the window closes, not when it is destroyed: GTK only
        # destroys it once nothing holds it, which may be never.
        self.connect("destroy", self._end_recovery)
        self._busy = False
        self._typing = False
        self._syncing_size = False
        self._last_jpeg_quality = 90

        self._title = Adw.WindowTitle(title=APP_NAME)
        self.toasts = Adw.ToastOverlay()
        self._recent_menu = Gio.Menu()
        # Widgets whose tooltip names a shortcut: (widget, text, action).
        self._shortcut_tooltips: list[tuple[Gtk.Widget, str, str]] = []
        self._color_bar = ColorBar(self.colors)
        self._add_shortcut_tooltip(self._color_bar.swap_button, "Swap colors", "win.swap-colors")
        # Where the palette can go: position -> (slot it sits in, strip to show).
        self._palette_slots: dict[str, tuple[Gtk.Box, Gtk.Widget | None]] = {}

        # The sidebars and bottom bar sit in one frame with the header's colour,
        # and the canvas is inset in it as a card, so no separator lines are
        # needed where they meet. The bottom bar is part of the content rather
        # than a toolbar-view bar, which would paint it a colour of its own.
        chrome = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        chrome.add_css_class("tempera-chrome")
        chrome.append(self._build_content())
        chrome.append(self._build_bottom_bar())

        toolbars = Adw.ToolbarView()
        toolbars.add_top_bar(self._build_header())
        toolbars.set_content(chrome)
        self._place_palette(load_palette_position())

        self.toasts.set_child(toolbars)
        self.set_content(self.toasts)

        self._sync_tool_options()
        self.sync_interface_size()
        self._install_actions()
        self._restore_preferences()
        self._watch_document()
        self._refresh_recent_menu()
        self.connect("close-request", self._on_close_request)

    # UI construction

    def _build_header(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar()
        header.set_title_widget(self._title)

        for icon, action, tooltip in (
            ("tempera-new-symbolic", "win.new", "New image"),
            ("document-open-symbolic", "win.open", "Open image"),
            ("tempera-save-symbolic", "win.save", "Save"),
        ):
            button = Gtk.Button(icon_name=icon)
            self._add_shortcut_tooltip(button, tooltip, action)
            button.set_action_name(action)
            header.pack_start(button)

        history = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        history.add_css_class("linked")
        for icon, action, tooltip in (
            ("tempera-undo-symbolic", "win.undo", "Undo"),
            ("tempera-redo-symbolic", "win.redo", "Redo"),
        ):
            button = Gtk.Button(icon_name=icon)
            self._add_shortcut_tooltip(button, tooltip, action)
            button.set_action_name(action)
            history.append(button)

        menu = Gio.Menu()
        edit_section = Gio.Menu()
        edit_section.append(_("Select All"), "win.select-all")
        edit_section.append(_("Cut"), "win.cut")
        edit_section.append(_("Copy"), "win.copy")
        edit_section.append(_("Paste"), "win.paste")
        menu.append_section(None, edit_section)
        image_section = Gio.Menu()
        image_section.append(_("Resize Image…"), "win.scale")
        image_section.append(_("Crop to Selection"), "win.crop")
        image_section.append(_("Rotate Clockwise"), "win.rotate-cw")
        image_section.append(_("Rotate Counterclockwise"), "win.rotate-ccw")
        image_section.append(_("Flip Horizontal"), "win.flip-horizontal")
        image_section.append(_("Flip Vertical"), "win.flip-vertical")
        menu.append_section(None, image_section)
        view_section = Gio.Menu()
        view_section.append(_("Zoom In"), "win.zoom-in")
        view_section.append(_("Zoom Out"), "win.zoom-out")
        view_section.append(_("Reset Zoom"), "win.zoom-reset")
        view_section.append(_("Zoom to Fit"), "win.zoom-fit")
        view_section.append(_("Show Pixel Grid"), "win.pixel-grid")
        palette_menu = Gio.Menu()
        palette_menu.append(_("Bottom"), "win.palette-position::bottom")
        palette_menu.append(_("Left"), "win.palette-position::left")
        palette_menu.append(_("Right"), "win.palette-position::right")
        view_section.append_submenu(_("Palette Position"), palette_menu)
        menu.append_section(None, view_section)
        file_section = Gio.Menu()
        file_section.append_submenu(_("Recent Files"), self._recent_menu)
        file_section.append(_("Save As…"), "win.save-as")
        file_section.append(_("Print…"), "win.print")
        file_section.append(_("Canvas Size…"), "win.resize")
        menu.append_section(None, file_section)
        app_section = Gio.Menu()
        app_section.append(_("Preferences"), "win.preferences")
        app_section.append(_("Keyboard Shortcuts"), "win.shortcuts")
        app_section.append(_("About {app}").format(app=APP_NAME), "app.about")
        app_section.append(_("Quit"), "app.quit")
        menu.append_section(None, app_section)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text=_("Main menu"))
        menu_button.set_menu_model(menu)
        menu_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Main menu")])

        # Shown while an image is being read or written, which happens off the
        # UI thread so that a large file does not freeze the window.
        self._busy_spinner = Adw.Spinner(visible=False, tooltip_text=_("Working…"))

        header.pack_end(menu_button)
        header.pack_end(history)
        header.pack_end(self._busy_spinner)
        return header

    def _build_bottom_bar(self) -> Gtk.Widget:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        # Held at the height the palette gives it, even when the palette is
        # elsewhere; sync_interface_size() sets it.
        self._bottom_bar = bar

        # Holds the palette when it sits at the bottom; empty otherwise. It
        # scrolls sideways rather than hold the window wider than the screen
        # at a big interface size.
        bottom_slot = Gtk.Box()
        bottom_scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_width=True,
            propagate_natural_height=True,
        )
        bottom_scroller.set_child(bottom_slot)
        bar.append(bottom_scroller)

        # Expands so the status items stay on the right wherever the palette is.
        # How big the selection is, beside the pointer position.
        self._selection_label = Gtk.Label()
        self._selection_label.add_css_class("numeric")
        self._selection_label.add_css_class("dim-label")
        bar.append(self._selection_label)

        self._cursor_label = Gtk.Label(hexpand=True, xalign=1)
        self._cursor_label.add_css_class("numeric")
        self._cursor_label.add_css_class("dim-label")
        bar.append(self._cursor_label)

        self._zoom_label = Gtk.Label()
        self._zoom_label.add_css_class("numeric")
        zoom_button = Gtk.Button()
        self._add_shortcut_tooltip(zoom_button, "Reset zoom", "win.zoom-reset")
        zoom_button.set_child(self._zoom_label)
        zoom_button.add_css_class("flat")
        zoom_button.set_valign(Gtk.Align.CENTER)
        zoom_button.set_action_name("win.zoom-reset")
        # Scrolling over the zoom level steps through the zoom presets. Discrete,
        # so a touchpad swipe moves one level at a time rather than racing.
        zoom_scroll = Gtk.EventControllerScroll(
            flags=Gtk.EventControllerScrollFlags.VERTICAL
            | Gtk.EventControllerScrollFlags.DISCRETE
        )
        zoom_scroll.connect("scroll", self._on_zoom_label_scroll)
        zoom_button.add_controller(zoom_scroll)
        bar.append(zoom_button)
        self._on_zoom_changed(self.canvas, self.canvas.zoom)

        # The canvas size lives here rather than in the header subtitle, which
        # renders too small to read at larger interface font sizes.
        self._canvas_size_label = Gtk.Label()
        self._canvas_size_label.add_css_class("numeric")
        button = Gtk.Button()
        self._add_shortcut_tooltip(button, "Canvas size", "win.resize")
        button.set_child(self._canvas_size_label)
        button.add_css_class("flat")
        button.set_valign(Gtk.Align.CENTER)
        button.set_margin_end(12)
        button.set_action_name("win.resize")
        bar.append(button)

        self._palette_slots["bottom"] = (bottom_slot, None)
        return bar

    def _build_content(self) -> Gtk.Widget:
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        content.append(self._build_sidebar())

        self._canvas_card = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self._canvas_card.add_css_class("tempera-canvas-area")
        self._canvas_card.set_child(CanvasFrame(self.canvas))
        # Middle-drag to pan and pinch to zoom belong to the scrolling area.
        self.canvas.attach_to_viewport(self._canvas_card)
        content.append(self._canvas_card)

        right_slot, right_strip = self._build_palette_strip()
        content.append(right_strip)
        self._palette_slots["right"] = (right_slot, right_strip)
        return content

    def _build_palette_strip(self) -> tuple[Gtk.Box, Gtk.Widget]:
        """A column right of the canvas for the palette, hidden while it is elsewhere.

        Returns the slot the palette goes in and the strip to show. The strip
        scrolls, like the sidebar, when the window is too short for it.
        """
        slot = Gtk.Box()
        slot.add_css_class("tempera-sidebar")
        strip = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            propagate_natural_width=True,
            visible=False,
        )
        strip.set_child(slot)
        return slot, strip

    def _build_sidebar(self) -> Gtk.Widget:
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        sidebar.add_css_class("tempera-sidebar")
        self._sidebar = sidebar

        tools = Gtk.Grid(row_spacing=6, column_spacing=6, halign=Gtk.Align.CENTER)
        for index, tool in enumerate(TOOL_CLASSES):
            button = Gtk.ToggleButton(icon_name=tool.icon_name)
            self._add_shortcut_tooltip(button, tool.label, f"win.tool::{tool.id}")
            button.add_css_class("tempera-tool")
            button.set_action_name("win.tool")
            button.set_action_target_value(GLib.Variant.new_string(tool.id))
            tools.attach(button, index % 2, index // 2, 1, 1)
        sidebar.append(tools)

        sidebar.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        self._size_label = Gtk.Label(xalign=0)
        self._size_label.add_css_class("caption")
        self._size_label.set_ellipsize(Pango.EllipsizeMode.END)
        sidebar.append(self._size_label)

        self._size_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, *BRUSH_SIZE_RANGE, 1
        )
        self._size_scale.set_value(self.canvas.brush_size)
        self._size_scale.set_draw_value(False)
        self._size_scale.connect("value-changed", self._on_size_changed)
        sidebar.append(self._size_scale)
        self._sync_size_scale()

        # Each tool's own options. They live in a stack so that the sidebar is
        # as wide as the widest of them whichever tool is in hand, rather than
        # growing and shrinking as tools are picked.
        self._tool_options = Gtk.Stack(hhomogeneous=True, vhomogeneous=False)
        self._tool_options.add_named(Gtk.Box(), "none")
        sidebar.append(self._tool_options)

        shape_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        shape_grid = Gtk.Grid(row_spacing=2, column_spacing=2, halign=Gtk.Align.CENTER)
        for index, shape in enumerate(SHAPE_CLASSES):
            button = Gtk.ToggleButton(icon_name=shape.icon_name)
            button.add_css_class("flat")
            self._add_shortcut_tooltip(button, shape.label, f"win.shape::{shape.id}")
            button.set_action_name("win.shape")
            button.set_action_target_value(GLib.Variant.new_string(shape.id))
            shape_grid.attach(button, index % 3, index // 3, 1, 1)
        shape_box.append(shape_grid)
        # The fill is the secondary colour, shown beside the option: white,
        # the colour it starts as, would otherwise look like no fill at all.
        fill_row = Gtk.Box(spacing=6)
        # The check expands to push the swatch to the end; saying outright that
        # the row does not stops that spreading up and widening the sidebar.
        fill_row.set_hexpand(False)
        self._fill_check = _option_check(_("Fill shape"))
        self._fill_check.set_hexpand(True)
        self._fill_check.connect("toggled", self._on_fill_toggled)
        fill_row.append(self._fill_check)
        self._fill_swatch = Swatch(self.colors.secondary)
        self._fill_swatch.set_valign(Gtk.Align.CENTER)
        self._fill_swatch.connect("picked", lambda *_args: self._color_bar.choose(primary=False))
        fill_row.append(self._fill_swatch)
        shape_box.append(fill_row)
        self.colors.connect("changed", lambda *_args: self._sync_fill_swatch())
        self._sync_fill_swatch()
        self._tool_options.add_named(shape_box, "shape")

        self._erase_check = _option_check(_("Erase to nothing"))
        self._erase_check.set_tooltip_text(
            _("Rub back to nothing instead of the secondary colour")
        )
        self._erase_check.connect(
            "toggled", lambda check: setattr(self.canvas, "erase_to_transparency", check.get_active())
        )
        self._tool_options.add_named(self._erase_check, "eraser")

        tolerance_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._tolerance_label = Gtk.Label(xalign=0)
        self._tolerance_label.add_css_class("caption")
        tolerance_box.append(self._tolerance_label)
        self._tolerance_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, *TOLERANCE_RANGE, 1
        )
        self._tolerance_scale.set_value(self.canvas.fill_tolerance)
        # The number rides on the slider, so the caption above stays short and
        # the sidebar stays narrow.
        self._tolerance_scale.set_draw_value(True)
        self._tolerance_scale.connect("value-changed", self._on_tolerance_changed)
        tolerance_box.append(self._tolerance_scale)
        self._tool_options.add_named(tolerance_box, "fill")
        self._show_tolerance(self.canvas.fill_tolerance)

        density_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        density_label = Gtk.Label(label=_("Density"), xalign=0)
        density_label.add_css_class("caption")
        density_box.append(density_label)
        self._density_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, *DENSITY_RANGE, 1
        )
        self._density_scale.set_value(self.canvas.airbrush_density)
        self._density_scale.set_draw_value(True)
        self._density_scale.set_tooltip_text(_("How thickly the airbrush sprays"))
        self._density_scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Density")])
        self._density_scale.connect(
            "value-changed",
            lambda scale: setattr(self.canvas, "airbrush_density", int(scale.get_value())),
        )
        density_box.append(self._density_scale)
        self._tool_options.add_named(density_box, "airbrush")

        # A caption of our own rather than a GtkFontDialogButton, whose label
        # grows the sidebar to fit whatever font name it is showing. It leaves
        # the size out, because that is what the slider above is for.
        font_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._font_label = Gtk.Label(label=font_without_size(self.canvas.font), xalign=0)
        self._font_label.add_css_class("caption")
        self._font_label.set_ellipsize(Pango.EllipsizeMode.END)
        font_box.append(self._font_label)

        self._font_button = Gtk.Button(
            label=_("Font…"), tooltip_text=_("Typeface for the text tool")
        )
        self._font_button.update_property(
            [Gtk.AccessibleProperty.DESCRIPTION], [_("Typeface for the text tool")]
        )
        self._font_button.connect("clicked", self._choose_font)
        font_box.append(self._font_button)
        self._tool_options.add_named(font_box, "text")

        # The palette's place when it is on the left: under the tool options.
        left_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, visible=False)
        left_section.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        left_slot = Gtk.Box(halign=Gtk.Align.CENTER)
        left_section.append(left_slot)
        sidebar.append(left_section)
        self._palette_slots["left"] = (left_slot, left_section)

        # Scrolls rather than squeezing when the window is too short for it all,
        # which the palette makes likelier. Its width does not follow the
        # content: a long option label would otherwise widen the whole sidebar
        # whenever that tool was picked.
        scrolled = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            propagate_natural_width=True,
        )
        scrolled.set_child(sidebar)
        return scrolled

    # Actions

    def _install_actions(self) -> None:
        simple_actions = {
            "new": self._action_new,
            "open": self._action_open,
            "save": lambda *_args: self._save(),
            "save-as": lambda *_args: self._save_as(),
            "print": lambda *_args: self._print(),
            "undo": self._action_undo,
            "redo": lambda *_args: self.canvas.document.redo(),
            "select-all": lambda *_args: self._select_all(),
            "cut": lambda *_args: self._cut(),
            "copy": lambda *_args: self._copy(),
            "paste": lambda *_args: self._paste(),
            "swap-colors": lambda *_args: self.colors.swap(),
            "size-up": lambda *_args: self._step_size(1),
            "size-down": lambda *_args: self._step_size(-1),
            "shortcuts": lambda *_args: ShortcutsDialog(self.get_application()).present(self),
            "preferences": lambda *_args: PreferencesDialog(self._set_interface_size).present(self),
            "clear-recent": lambda *_args: self._clear_recent(),
            "resize": lambda *_args: self._prompt_canvas_size(),
            "scale": lambda *_args: self._prompt_scale_image(),
            "zoom-in": lambda *_args: self.canvas.zoom_in(),
            "zoom-out": lambda *_args: self.canvas.zoom_out(),
            "zoom-reset": lambda *_args: self.canvas.reset_zoom(),
            "zoom-fit": lambda *_args: self.canvas.zoom_to_fit(),
            "crop": lambda *_args: self.canvas.crop_to_selection(),
            "rotate-cw": lambda *_args: self._transform_image(lambda d: d.rotate(True)),
            "rotate-ccw": lambda *_args: self._transform_image(lambda d: d.rotate(False)),
            "flip-horizontal": lambda *_args: self._transform_image(lambda d: d.flip(True)),
            "flip-vertical": lambda *_args: self._transform_image(lambda d: d.flip(False)),
        }
        for name, callback in simple_actions.items():
            action = Gio.SimpleAction.new(name, None)
            if name in IMAGE_ACTIONS:
                callback = self._unless_dragging(callback)
            action.connect("activate", callback)
            self.add_action(action)

        tool_action = Gio.SimpleAction.new_stateful(
            "tool", GLib.VariantType.new("s"), GLib.Variant.new_string("pencil")
        )
        # Swapping tools mid-stroke would hand the release to a tool that never saw the press.
        tool_action.connect("change-state", self._unless_dragging(self._on_tool_changed))
        self.add_action(tool_action)

        shape_action = Gio.SimpleAction.new_stateful(
            "shape", GLib.VariantType.new("s"), GLib.Variant.new_string(DEFAULT_SHAPE)
        )
        shape_action.connect("change-state", self._unless_dragging(self._on_shape_changed))
        self.add_action(shape_action)

        grid_action = Gio.SimpleAction.new_stateful(
            "pixel-grid", None, GLib.Variant.new_boolean(False)
        )
        grid_action.connect("change-state", self._on_pixel_grid_changed)
        self.add_action(grid_action)

        palette_action = Gio.SimpleAction.new_stateful(
            "palette-position",
            GLib.VariantType.new("s"),
            GLib.Variant.new_string(self._palette_position),
        )
        palette_action.connect("change-state", self._on_palette_position_changed)
        self.add_action(palette_action)

        open_recent_action = Gio.SimpleAction.new("open-recent", GLib.VariantType.new("s"))
        open_recent_action.connect("activate", self._unless_dragging(self._action_open_recent))
        self.add_action(open_recent_action)

        shortcuts.apply_accels(self.get_application())

        clipboard = self.get_clipboard()
        clipboard.connect("changed", lambda *_args: self._sync_paste_action())
        self._sync_paste_action()
        self._sync_selection_actions()

    def _unless_dragging(self, callback):
        """Wrap an action handler so it does nothing while a mouse button is held."""

        def handler(*args):
            if not self.canvas.is_dragging:
                callback(*args)

        return handler

    def _set_busy(self, busy: bool) -> None:
        """Show that a file is being read or written, and let only one run at a time."""
        self._busy = busy
        self._busy_spinner.set_visible(busy)

    def _on_tool_changed(self, action, value: GLib.Variant) -> None:
        self.canvas.commit_floating()
        action.set_state(value)
        self.canvas.select_tool(value.get_string())
        self._sync_tool_options()
        self._sync_size_scale()

    def _on_shape_changed(self, action, value: GLib.Variant) -> None:
        """Picking a shape, from the grid or its key, also takes up the Shapes tool."""
        shape_id = value.get_string()
        if shape_id not in SHAPE_IDS:
            return
        self.canvas.select_shape(shape_id)
        action.set_state(value)
        self.lookup_action("tool").change_state(GLib.Variant.new_string(SHAPES_TOOL_ID))
        self._sync_tool_options()

    def _on_pixel_grid_changed(self, action, value: GLib.Variant) -> None:
        action.set_state(value)
        self.canvas.show_pixel_grid = value.get_boolean()
        if value.get_boolean() and not self.canvas.pixel_grid_visible:
            self.show_toast(
                _("The pixel grid shows from {zoom}% zoom").format(
                    zoom=round(PIXEL_GRID_ZOOM * 100)
                )
            )

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
        for name, (slot, strip) in self._palette_slots.items():
            if strip is not None:
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
        # The strip's padding already spaces the card from the right edge.
        if position == "right":
            self._canvas_card.add_css_class("tempera-palette-beside")
        else:
            self._canvas_card.remove_css_class("tempera-palette-beside")
        self._palette_position = position

    def _set_interface_size(self, size: int) -> None:
        """Draw the whole app at a new size, every window of it, and remember it."""
        interface_size.apply(size)
        save_settings({"interface-size": interface_size.current()})
        for window in self.get_application().get_windows():
            if isinstance(window, TemperaWindow):
                window.sync_interface_size()

    def sync_interface_size(self) -> None:
        """Size what is set in code rather than by the stylesheets."""
        self._sidebar.set_size_request(interface_size.scaled(SIDEBAR_WIDTH), -1)
        self._bottom_bar.set_size_request(-1, interface_size.scaled(BOTTOM_BAR_HEIGHT))
        self.canvas.sync_interface_size()

    def _step_size(self, step: int) -> None:
        """[ and ]: a bigger or smaller brush, or bigger or smaller text."""
        self._size_scale.set_value(self._size_scale.get_value() + step)

    def _on_size_changed(self, scale: Gtk.Scale) -> None:
        if self._syncing_size:
            return
        size = int(scale.get_value())
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
        self._size_scale.set_range(*(FONT_SIZE_RANGE if text else BRUSH_SIZE_RANGE))
        self._size_scale.set_value(size)
        self._syncing_size = False
        self._show_size(size)

    def _show_size(self, size: int) -> None:
        unit = _("pt") if self.canvas.supports_font else _("px")
        self._size_label.set_label(_("Size: {size} {unit}").format(size=size, unit=unit))

    def _sync_fill_swatch(self) -> None:
        color = self.colors.secondary
        self._fill_swatch.color = color
        self._fill_swatch.set_label_text(
            _("Fill colour, the secondary colour: {color}").format(color=describe(color))
        )

    def _on_fill_toggled(self, check: Gtk.CheckButton) -> None:
        self.canvas.fill_shapes = check.get_active()

    def _on_tolerance_changed(self, scale: Gtk.Scale) -> None:
        self.canvas.fill_tolerance = int(scale.get_value())
        self._show_tolerance(self.canvas.fill_tolerance)

    def _show_tolerance(self, tolerance: int) -> None:
        self._tolerance_label.set_label(_("Tolerance"))
        self._tolerance_scale.set_tooltip_text(
            _("How far a fill spreads into colours near the one you clicked: {value}").format(
                value=tolerance
            )
        )

    def _sync_tool_options(self) -> None:
        """Show the options belonging to the tool in hand, and none of the others."""
        canvas = self.canvas
        page = "none"
        if canvas.supports_fill:
            page = "shape"
            # A line, arrow or curve has no inside to fill.
            self._fill_check.set_sensitive(canvas.shapes.fillable)
            self._fill_swatch.set_sensitive(canvas.shapes.fillable)
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

    def _on_color_picked(self, canvas, color, button) -> None:
        # The color arrives on loan from the signal and is freed as soon as the
        # emission ends, so it has to be copied before it is kept.
        color = color.copy()
        if button == Gdk.BUTTON_SECONDARY:
            self.colors.secondary = color
        else:
            self.colors.primary = color

    # Document lifecycle

    def _watch_document(self) -> None:
        document = self.canvas.document
        document.connect("state-changed", lambda *_args: self._sync_state())
        document.connect("content-changed", lambda *_args: self._note_change())
        self._note_change()
        self._sync_state()

    # Crash recovery

    def _note_change(self) -> None:
        self._changes += 1

    def _keep_recovery_copy(self) -> bool:
        """Keep a fresh copy of unsaved work, when there is any the last copy lacks."""
        document = self.canvas.document
        if not document.modified:
            self._forget_recovery_copy()
        elif self._kept_changes != self._changes:
            self._kept_changes = self._changes
            self._recovery.save(
                document.surface,
                {
                    "title": document.title,
                    "file": document.file.get_uri() if document.file is not None else None,
                },
            )
        return GLib.SOURCE_CONTINUE

    def _forget_recovery_copy(self) -> None:
        if self._kept_changes is not None:
            self._kept_changes = None
            self._recovery.clear()

    def _end_recovery(self, *_args) -> None:
        """A normal close: saved, or the changes were thrown away on purpose."""
        if self._recovery_timer:
            GLib.source_remove(self._recovery_timer)
            self._recovery_timer = 0
        self._recovery.close()

    def is_untouched(self) -> bool:
        """Whether this is a blank window nobody has drawn in, which a recovered image may take over."""
        document = self.canvas.document
        return (
            document.file is None
            and not document.modified
            and not document.can_undo
            and not self.canvas.has_floating
        )

    def show_recovered(self, document: Document) -> None:
        """Take over an image brought back after a crash, and keep a copy of it straight away."""
        self._set_document(document)
        self._keep_recovery_copy()

    def _set_document(self, document: Document) -> None:
        self.canvas.document = document
        self._watch_document()
        # A photo larger than the window opens zoomed out to fit.
        self.canvas.fit_if_too_large()

    def _sync_state(self) -> None:
        document = self.canvas.document
        if not document.modified:
            # Saved, or undone back to how it was saved: nothing to recover.
            self._forget_recovery_copy()
        marker = " •" if document.modified else ""
        self._title.set_title(f"{document.title}{marker}")
        # While a paste or a text box floats this counts out the size a commit
        # would leave.
        width, height = self.canvas.pending_size
        self._canvas_size_label.set_label(_("{width} × {height} px").format(width=width, height=height))
        # Undo also takes back what has not been stamped down yet.
        self.lookup_action("undo").set_enabled(document.can_undo or self.canvas.has_floating)
        self.lookup_action("redo").set_enabled(document.can_redo)

    def _on_floating_changed(self, *_args) -> None:
        self._sync_state()
        self._sync_typing_accels()

    def _sync_typing_accels(self) -> None:
        """Give the one-key shortcuts back and forth as a text box comes and goes."""
        if self.canvas.is_typing == self._typing:
            return
        self._typing = self.canvas.is_typing
        shortcuts.apply_accels(self.get_application())

    def _add_shortcut_tooltip(self, widget: Gtk.Widget, text: str, action: str) -> None:
        self._shortcut_tooltips.append((widget, text, action))
        widget.set_tooltip_text(shortcuts.tooltip(text, action))
        # A tooltip is only a description; a button showing an icon needs a name
        # of its own for a screen reader to have anything to read out.
        widget.update_property([Gtk.AccessibleProperty.LABEL], [text])

    def refresh_shortcut_tooltips(self) -> None:
        """Show the current keys after the user changes a shortcut."""
        for widget, text, action in self._shortcut_tooltips:
            widget.set_tooltip_text(shortcuts.tooltip(text, action))

    def _on_resize_preview(self, canvas, width: int, height: int) -> None:
        """Count out the pending size while a resize grip is being dragged."""
        self._canvas_size_label.set_label(_("{width} × {height} px").format(width=width, height=height))

    def _on_zoom_label_scroll(self, controller, dx: float, dy: float) -> bool:
        if dy < 0:
            self.canvas.zoom_in()
        elif dy > 0:
            self.canvas.zoom_out()
        return Gdk.EVENT_STOP

    def _on_zoom_changed(self, canvas, zoom: float) -> None:
        self._zoom_label.set_label(f"{round(zoom * 100)}%")

    def _on_pointer_moved(self, canvas, x: float, y: float) -> None:
        self._cursor_label.set_label(_("{x}, {y} px").format(x=round(x), y=round(y)))
        self._cursor_label.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [_("Pointer at {x}, {y} pixels").format(x=round(x), y=round(y))],
        )

    def _transform_image(self, apply) -> None:
        """Whatever floats or is selected does not survive a rotate or flip."""
        self.canvas.commit_floating()
        self.canvas.clear_selection()
        apply(self.canvas.document)

    # Clipboard

    def _sync_paste_action(self) -> None:
        self.lookup_action("paste").set_enabled(has_image(self.get_clipboard()))

    def _show_selection_size(self) -> None:
        size = self.canvas.selection_size
        self._selection_label.set_label(
            "" if size is None else _("Selection {width} × {height}").format(
                width=size[0], height=size[1]
            )
        )

    def _sync_selection_actions(self) -> None:
        # There is nothing to cut or crop to without a selection.
        self.lookup_action("cut").set_enabled(self.canvas.has_selection)
        self.lookup_action("crop").set_enabled(self.canvas.has_selection)

    def _put_on_clipboard(self, surface) -> None:
        texture = texture_from_surface(surface)
        self.get_clipboard().set_content(Gdk.ContentProvider.new_for_value(texture))
        # The clipboard's own notification is asynchronous; do not wait for it.
        self._sync_paste_action()

    def _select_all(self) -> None:
        self.lookup_action("tool").change_state(GLib.Variant.new_string("select"))
        self.canvas.select_all()

    def _copy(self) -> None:
        self.canvas.commit_floating()
        # A selection narrows the copy down to itself; otherwise it is the canvas.
        selection = self.canvas.selection_surface()
        self._put_on_clipboard(selection or self.canvas.document.surface)
        self.show_toast(_("Copied the selection") if selection else _("Copied to clipboard"))

    def _cut(self) -> None:
        self.canvas.commit_floating()
        selection = self.canvas.selection_surface()
        if selection is None:
            return
        self._put_on_clipboard(selection)
        self.canvas.delete_selection()
        self.show_toast(_("Cut the selection"))

    def _paste(self) -> None:
        read_image(self.get_clipboard(), self.canvas.begin_paste, self.show_toast)

    def _action_undo(self, *_args) -> None:
        # A paste or a text box has not been stamped down yet, so undo drops it.
        if not self.canvas.cancel_floating():
            self.canvas.document.undo()

    def show_toast(self, message: str) -> None:
        # Messages carry file names and loader errors, which are not markup.
        self.toasts.add_toast(Adw.Toast(title=message, use_markup=False))

    def _confirm_discard(self, proceed) -> None:
        # A paste or text still floating counts as a change, but is not landed
        # yet: Cancel has to leave the image exactly as it was.
        document = self.canvas.document
        if not document.modified and not self.canvas.has_pending_floating:
            proceed()
            return

        dialog = Adw.AlertDialog(
            heading=_("Save changes?"),
            body=_("“{name}” has unsaved changes.").format(name=document.title),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("discard", _("Discard"))
        dialog.add_response("save", _("Save"))
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == "discard":
                proceed()
            elif response == "save":
                self._save(proceed)

        dialog.connect("response", on_response)
        dialog.present(self)

    def _action_new(self, *_args) -> None:
        self._confirm_discard(self._prompt_new_size)

    def _prompt_size(
        self, heading, body, size, accept_id, accept_label, on_accept, extra=None
    ) -> None:
        """Ask for a width/height pair, then hand it to on_accept."""
        spins = []
        for value in size:
            spin = Gtk.SpinButton.new_with_range(1, MAX_SIZE, 1)
            spin.set_value(value)
            # Wide enough for the largest allowed size in any interface font.
            spin.set_width_chars(len(str(MAX_SIZE)) + 1)
            spins.append(spin)
        width_spin, height_spin = spins

        grid = Gtk.Grid(row_spacing=6, column_spacing=12, margin_top=12)
        grid.attach(Gtk.Label(label=_("Width"), xalign=1), 0, 0, 1, 1)
        grid.attach(width_spin, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label=_("Height"), xalign=1), 0, 1, 1, 1)
        grid.attach(height_spin, 1, 1, 1, 1)
        if extra is not None:
            grid.attach(extra, 0, 2, 2, 1)

        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.set_extra_child(grid)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response(accept_id, accept_label)
        dialog.set_response_appearance(accept_id, Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response(accept_id)
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == accept_id:
                on_accept(int(width_spin.get_value()), int(height_spin.get_value()))

        dialog.connect("response", on_response)
        dialog.present(self)

    def _prompt_new_size(self) -> None:
        transparent = Gtk.CheckButton(label=_("Transparent background"))
        transparent.set_tooltip_text(_("Start with nothing rather than white"))

        def create(width: int, height: int) -> None:
            fill = TRANSPARENT if transparent.get_active() else WHITE
            self._set_document(Document(new_surface(width, height, fill)))

        self._prompt_size(
            _("New image"),
            _("Choose a canvas size in pixels."),
            (DEFAULT_WIDTH, DEFAULT_HEIGHT),
            "create",
            _("Create"),
            create,
            extra=transparent,
        )

    def _prompt_canvas_size(self) -> None:
        self.canvas.commit_floating()
        document = self.canvas.document

        self._prompt_size(
            _("Canvas size"),
            _("The image keeps its top-left corner; extra space is filled with white."),
            (document.width, document.height),
            "resize",
            _("Resize"),
            document.resize,
        )

    def _prompt_scale_image(self) -> None:
        """Ask for a new size for the picture itself, in pixels or as a percentage."""
        self.canvas.commit_floating()
        self.canvas.clear_selection()
        document = self.canvas.document
        original = (document.width, document.height)

        pixels = Gtk.ToggleButton(label=_("Pixels"), active=True)
        percent = Gtk.ToggleButton(label=_("Percent"), group=pixels)
        units = Gtk.Box(halign=Gtk.Align.CENTER, margin_top=12)
        units.add_css_class("linked")
        units.append(pixels)
        units.append(percent)

        spins = [Gtk.SpinButton.new_with_range(1, MAX_SIZE, 1) for _side in original]
        width_spin, height_spin = spins
        for spin, side in zip(spins, original):
            spin.set_value(side)
            spin.set_width_chars(len(str(MAX_SIZE)) + 1)
        keep_ratio = Gtk.CheckButton(label=_("Keep aspect ratio"), active=True)

        syncing = False

        def in_percent() -> bool:
            return percent.get_active()

        def follow(changed: Gtk.SpinButton, other: Gtk.SpinButton, index: int) -> None:
            """Keep the other side in proportion while the ratio is locked."""
            nonlocal syncing
            if syncing or not keep_ratio.get_active():
                return
            syncing = True
            if in_percent():
                other.set_value(changed.get_value())
            else:
                other.set_value(
                    scaled_side(original[1 - index], changed.get_value() * 100 / original[index])
                )
            syncing = False

        width_spin.connect("value-changed", lambda spin: follow(spin, height_spin, 0))
        height_spin.connect("value-changed", lambda spin: follow(spin, width_spin, 1))

        def switch_units(*_args) -> None:
            nonlocal syncing
            syncing = True
            for spin, side in zip(spins, original):
                value = spin.get_value()
                if in_percent():
                    spin.set_range(1, 1000)
                    spin.set_value(round(value * 100 / side))
                else:
                    spin.set_range(1, MAX_SIZE)
                    spin.set_value(scaled_side(side, value))
            syncing = False

        percent.connect("toggled", switch_units)

        grid = Gtk.Grid(row_spacing=6, column_spacing=12, margin_top=12)
        grid.attach(Gtk.Label(label=_("Width"), xalign=1), 0, 0, 1, 1)
        grid.attach(width_spin, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label=_("Height"), xalign=1), 0, 1, 1, 1)
        grid.attach(height_spin, 1, 1, 1, 1)
        grid.attach(keep_ratio, 0, 2, 2, 1)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.append(units)
        content.append(grid)

        dialog = Adw.AlertDialog(
            heading=_("Resize image"),
            body=_("The whole picture is stretched or shrunk to the new size."),
        )
        dialog.set_extra_child(content)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("scale", _("Resize"))
        dialog.set_response_appearance("scale", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("scale")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response != "scale":
                return
            values = [spin.get_value() for spin in spins]
            if in_percent():
                values = [scaled_side(side, value) for side, value in zip(original, values)]
            document.scale(int(values[0]), int(values[1]))

        dialog.connect("response", on_response)
        dialog.present(self)

    def _action_open(self, *_args) -> None:
        self._confirm_discard(self._show_open_dialog)

    def _show_open_dialog(self) -> None:
        if self._busy:
            return
        dialog = Gtk.FileDialog(title=_("Open Image"), filters=image_filters())

        def on_done(source, result):
            try:
                file = source.open_finish(result)
            except GLib.Error:
                return
            self._open_file(file, _("Could not open image: {message}"))

        dialog.open(self, None, on_done)

    def _open_file(self, file: Gio.File, error_format: str, on_error=None) -> None:
        """Read an image in the background and show it, or say why it could not be."""
        self._set_busy(True)

        def on_document(document: Document) -> None:
            self._set_busy(False)
            self._set_document(document)
            self._remember_recent(file)

        def on_error_message(message: str) -> None:
            self._set_busy(False)
            self.show_toast(error_format.format(message=message))
            if on_error is not None:
                on_error()

        load_document_async(file, on_document, on_error_message)

    def _refresh_recent_menu(self) -> None:
        self._recent_menu.remove_all()
        recent = load_recent()
        if not recent:
            self._recent_menu.append(_("No Recent Files"), None)
            return
        files = Gio.Menu()
        for uri in recent:
            item = Gio.MenuItem.new(Gio.File.new_for_uri(uri).get_basename(), None)
            item.set_action_and_target_value("win.open-recent", GLib.Variant.new_string(uri))
            files.append_item(item)
        self._recent_menu.append_section(None, files)
        clearing = Gio.Menu()
        clearing.append(_("Clear Recent Files"), "win.clear-recent")
        self._recent_menu.append_section(None, clearing)

    def _clear_recent(self) -> None:
        clear_recent()
        self._refresh_recent_menu()
        self.show_toast(_("Cleared the recent files"))

    def _remember_recent(self, file: Gio.File) -> None:
        remember_recent(file)
        self._refresh_recent_menu()

    def _action_open_recent(self, action, param: GLib.Variant) -> None:
        uri = param.get_string()

        def proceed():
            file = Gio.File.new_for_uri(uri)

            def forget():
                forget_recent(uri)
                self._refresh_recent_menu()

            self._open_file(
                file,
                _("Could not open “{name}”: {{message}}").format(name=file.get_basename()),
                forget,
            )

        self._confirm_discard(proceed)

    def _save(self, then=None) -> None:
        if self._busy:
            return
        # What gets written should match what is on screen.
        self.canvas.commit_floating()
        document = self.canvas.document
        if document.file is None or format_for(document.file) is None:
            # Never saved, or opened from a format such as GIF that Tempera
            # cannot write back: ask where, rather than overwrite it as PNG.
            self._save_as(then)
            return
        # Ctrl+S keeps the quality already chosen; only Save As asks for it.
        self._write_now(document.file, then, self._last_jpeg_quality)

    def _print(self) -> None:
        # What gets printed should match what is on screen.
        self.canvas.commit_floating()
        document = self.canvas.document

        def on_print(size: str, orientation) -> None:
            save_settings({"print-size": size})
            job = printing.PrintJob(document.surface, document.title, size, orientation)

            def on_error(message: str) -> None:
                self.show_toast(_("Could not print: {message}").format(message=message))

            printing.print_image(self, job, on_error)

        printing.PrintDialog(
            document.surface, load_setting("print-size", printing.DEFAULT_SIZE), on_print
        ).present(self)

    def _save_as(self, then=None) -> None:
        if self._busy:
            return
        self.canvas.commit_floating()
        document = self.canvas.document
        dialog = Gtk.FileDialog(title=_("Save Image"), filters=image_filters())
        if document.file is None:
            dialog.set_initial_name("Untitled.png")
        else:
            dialog.set_initial_name(save_as_name(document.file))

        def on_done(source, result):
            try:
                chosen = source.save_finish(result)
            except GLib.Error:
                return
            file = with_default_extension(chosen)
            if not file.equal(chosen) and file.query_exists(None):
                # The dialog only asked about replacing the name as typed.
                self._confirm_replace(file, lambda: self._write(file, then))
            else:
                self._write(file, then)

        dialog.save(self, None, on_done)

    def _confirm_replace(self, file: Gio.File, proceed) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Replace “{name}”?").format(name=file.get_basename()),
            body=_("A file with this name already exists. Saving will overwrite it."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("replace", _("Replace"))
        dialog.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == "replace":
                proceed()

        dialog.connect("response", on_response)
        dialog.present(self)

    def _write(self, file: Gio.File, then=None) -> None:
        if format_for(file) == "jpeg":
            self._prompt_jpeg_quality(lambda quality: self._write_now(file, then, quality))
        else:
            self._write_now(file, then, None)

    def _prompt_jpeg_quality(self, on_accept) -> None:
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        scale.set_value(self._last_jpeg_quality)
        scale.set_draw_value(True)
        scale.set_hexpand(True)
        scale.set_size_request(220, -1)

        dialog = Adw.AlertDialog(
            heading=_("JPEG Quality"),
            body=_("Lower values make a smaller file but lose more detail."),
        )
        dialog.set_extra_child(scale)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("save", _("Save"))
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("save")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == "save":
                self._last_jpeg_quality = int(scale.get_value())
                on_accept(self._last_jpeg_quality)

        dialog.connect("response", on_response)
        dialog.present(self)

    def _write_now(self, file: Gio.File, then, quality: int | None) -> None:
        self._set_busy(True)

        def on_saved() -> None:
            self._set_busy(False)
            self.show_toast(_("Saved {name}").format(name=file.get_basename()))
            self._remember_recent(file)
            if then is not None:
                then()

        def on_error(message: str) -> None:
            self._set_busy(False)
            self.show_toast(_("Could not save image: {message}").format(message=message))

        arguments = {} if quality is None else {"quality": quality}
        save_document_async(self.canvas.document, file, on_saved, on_error, **arguments)

    # Preferences that outlive the window

    def _restore_window_size(self) -> None:
        width = _whole(load_setting("window-width"), 1120)
        height = _whole(load_setting("window-height"), 800)
        self.set_default_size(width, height)
        if load_setting("window-maximized") == "1":
            self.maximize()

    def _restore_preferences(self) -> None:
        """Put back the tool, sizes, font and colours from the last time."""
        tool = load_setting("tool")
        shape = load_setting("shape")
        if tool in SHAPE_IDS:
            # Tempera 1.0 had a tool for each shape.
            tool, shape = SHAPES_TOOL_ID, tool
        if shape in SHAPE_IDS:
            self.lookup_action("shape").change_state(GLib.Variant.new_string(shape))
        if any(tool == candidate.id for candidate in TOOL_CLASSES):
            self.lookup_action("tool").change_state(GLib.Variant.new_string(tool))
        self.canvas.brush_size = _whole(
            load_setting("brush-size"), self.canvas.brush_size, BRUSH_SIZE_RANGE
        )
        font = load_setting("font")
        if font:
            self.canvas.set_font(font)
            self._font_label.set_label(font_without_size(font))
        self.canvas.fill_tolerance = _whole(
            load_setting("fill-tolerance"), self.canvas.fill_tolerance, TOLERANCE_RANGE
        )
        self._tolerance_scale.set_value(self.canvas.fill_tolerance)
        self._density_scale.set_value(
            _whole(load_setting("airbrush-density"), self.canvas.airbrush_density, DENSITY_RANGE)
        )
        if load_setting("pixel-grid") == "1":
            self.lookup_action("pixel-grid").change_state(GLib.Variant.new_boolean(True))
        self._last_jpeg_quality = _whole(load_setting("jpeg-quality"), 90, (1, 100))
        for key, attribute in (("primary-color", "primary"), ("secondary-color", "secondary")):
            spec = load_setting(key)
            color = Gdk.RGBA()
            if spec and color.parse(spec):
                setattr(self.colors, attribute, color)
        recent = [rgba(spec) for spec in load_setting("recent-colors").split()]
        self.colors.recent = [color for color in recent if color is not None][:MAX_RECENT_COLORS]
        self._color_bar.refresh()
        self._sync_size_scale()

    def _save_preferences(self) -> None:
        width, height = self.get_default_size()
        save_settings(
            {
                "window-width": width,
                "window-height": height,
                "window-maximized": "1" if self.is_maximized() else "0",
                "tool": self.canvas.active_tool.id,
                "shape": self.canvas.shapes.shape.id,
                "brush-size": self.canvas.brush_size,
                "font": self.canvas.font,
                "fill-tolerance": self.canvas.fill_tolerance,
                "airbrush-density": self.canvas.airbrush_density,
                "pixel-grid": "1" if self.canvas.show_pixel_grid else "0",
                "jpeg-quality": self._last_jpeg_quality,
                "primary-color": self.colors.primary.to_string(),
                "secondary-color": self.colors.secondary.to_string(),
                "recent-colors": " ".join(color.to_string() for color in self.colors.recent),
            }
        )

    def _on_close_request(self, *_args) -> bool:
        if self._closing:
            self._end_recovery()
            return False
        self._save_preferences()

        # With nothing to ask about, let this close go ahead. Calling close()
        # from inside the handler instead does nothing, since GTK ignores a
        # close while it is still deciding on this one.
        if not self.canvas.document.modified and not self.canvas.has_pending_floating:
            self._end_recovery()
            return False

        def close():
            self._closing = True
            self.close()

        self._confirm_discard(close)
        return True
