# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The main window, assembled from the parts in this package."""

from __future__ import annotations

from dataclasses import replace

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .. import APP_NAME, interface_size, recovery, shortcuts
from ..canvas import PIXEL_GRID_ZOOM, Canvas
from ..color import ColorBar, ColorState
from ..document import Document
from ..i18n import _
from ..settings import load_palette_position, save_settings
from ..preferences import PreferencesDialog
from ..shortcuts_dialog import ShortcutsDialog
from ..text import ALIGNMENTS, TEXT_SWITCHES
from ..tools import DEFAULT_SHAPE, SHAPE_IDS, SHAPES_TOOL_ID
from .edit import EditMixin
from .files import FilesMixin
from .header import HeaderMixin
from .image_dialogs import ImageDialogsMixin
from .layers import LayersMixin
from .layout import LayoutMixin
from .options_bar import ToolOptionsMixin
from .session import SessionMixin

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


class TemperaWindow(
    HeaderMixin,
    ToolOptionsMixin,
    LayoutMixin,
    EditMixin,
    ImageDialogsMixin,
    FilesMixin,
    SessionMixin,
    LayersMixin,
    Adw.ApplicationWindow,
):
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
        # The picture already told that saving it as PNG or JPEG merges its layers.
        self._told_of_merging: Document | None = None

        self._title = Adw.WindowTitle(title=APP_NAME)
        self.toasts = Adw.ToastOverlay()
        self._recent_menu = Gio.Menu()
        # Widgets whose tooltip names a shortcut: (widget, text, action).
        self._shortcut_tooltips: list[tuple[Gtk.Widget, str, str]] = []
        self._color_bar = ColorBar(self.colors)
        self._add_shortcut_tooltip(self._color_bar.swap_button, "Swap colors", "win.swap-colors")
        # Where the palette can go: position -> (slot it sits in, strip to show).
        self._palette_slots: dict[str, tuple[Gtk.Box, Gtk.Widget | None]] = {}

        toolbars = Adw.ToolbarView()
        toolbars.add_top_bar(self._build_header())
        toolbars.set_content(self._build_body())
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

        # How text looks, each a switch the options bar and its key share.
        for name in TEXT_SWITCHES:
            switch = Gio.SimpleAction.new_stateful(f"text-{name}", None, GLib.Variant.new_boolean(False))
            switch.connect("change-state", self._on_text_switch_changed, name)
            self.add_action(switch)
        align = Gio.SimpleAction.new_stateful(
            "text-align", GLib.VariantType.new("s"), GLib.Variant.new_string("left")
        )
        align.connect("change-state", self._on_text_align_changed)
        self.add_action(align)

        transparent_action = Gio.SimpleAction.new_stateful(
            "transparent-selection", None, GLib.Variant.new_boolean(False)
        )
        transparent_action.connect("change-state", self._on_transparent_selection_changed)
        self.add_action(transparent_action)

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

        self._install_layer_actions()
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
        self._sync_selection_button(value.get_string())
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

    def _on_text_switch_changed(self, action, value: GLib.Variant, name: str) -> None:
        action.set_state(value)
        self.canvas.text_style = replace(self.canvas.text_style, **{name: value.get_boolean()})

    def _on_text_align_changed(self, action, value: GLib.Variant) -> None:
        if value.get_string() not in ALIGNMENTS:
            return
        action.set_state(value)
        self.canvas.text_style = replace(self.canvas.text_style, align=value.get_string())

    def _on_transparent_selection_changed(self, action, value: GLib.Variant) -> None:
        action.set_state(value)
        self.canvas.transparent_selection = value.get_boolean()

    def _on_pixel_grid_changed(self, action, value: GLib.Variant) -> None:
        action.set_state(value)
        self.canvas.show_pixel_grid = value.get_boolean()
        if value.get_boolean() and not self.canvas.pixel_grid_visible:
            self.show_toast(
                _("The pixel grid shows from {zoom}% zoom").format(
                    zoom=round(PIXEL_GRID_ZOOM * 100)
                )
            )

    def _set_interface_size(self, size: int) -> None:
        """Draw the whole app at a new size, every window of it, and remember it."""
        interface_size.apply(size)
        save_settings({"interface-size": interface_size.current()})
        for window in self.get_application().get_windows():
            if isinstance(window, TemperaWindow):
                window.sync_interface_size()

    def _on_color_picked(self, canvas, color, button) -> None:
        # The color arrives on loan from the signal and is freed as soon as the
        # emission ends, so it has to be copied before it is kept.
        color = color.copy()
        if button == Gdk.BUTTON_SECONDARY:
            self.colors.secondary = color
        else:
            self.colors.primary = color

    def _watch_document(self) -> None:
        document = self.canvas.document
        document.connect("state-changed", lambda *_args: self._sync_state())
        document.connect("content-changed", lambda *_args: self._note_change())
        self._watch_layers(document)
        self._note_change()
        self._sync_state()

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
        self._show_canvas_size(*self.canvas.pending_size)
        # Undo also takes back what has not been stamped down yet.
        self.lookup_action("undo").set_enabled(
            document.can_undo or self.canvas.has_floating or self.canvas.shape_in_progress
        )
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

    def show_toast(self, message: str) -> None:
        # Messages carry file names and loader errors, which are not markup.
        self.toasts.add_toast(Adw.Toast(title=message, use_markup=False))
