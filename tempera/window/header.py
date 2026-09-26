# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The header bar and the main menu."""

from __future__ import annotations

from gi.repository import Adw, Gio, GLib, Gtk

from .. import APP_NAME
from ..i18n import _


def _custom_menu_item(name: str) -> Gio.MenuItem:
    """A place in a menu for a widget of our own, added to the popover under this name."""
    item = Gio.MenuItem.new(None, None)
    item.set_attribute_value("custom", GLib.Variant.new_string(name))
    return item


class HeaderMixin:
    """The header bar, with the main menu and its rows of buttons."""

    def _build_header(self) -> Adw.HeaderBar:
        header = Adw.HeaderBar()
        header.set_title_widget(self._title)

        for icon, action, tooltip in (
            ("tempera-new-symbolic", "win.new", "New image"),
            ("tempera-open-symbolic", "win.open", "Open image"),
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
        image_section.append(_("Canvas Size…"), "win.resize")
        image_section.append(_("Crop to Selection"), "win.crop")
        image_section.append_item(_custom_menu_item("transform"))
        menu.append_section(None, image_section)
        view_section = Gio.Menu()
        view_section.append_item(_custom_menu_item("zoom"))
        view_section.append(_("Show Pixel Grid"), "win.pixel-grid")
        palette_menu = Gio.Menu()
        palette_menu.append(_("Left"), "win.palette-position::left")
        palette_menu.append(_("Right"), "win.palette-position::right")
        palette_menu.append(_("Bottom"), "win.palette-position::bottom")
        view_section.append_submenu(_("Palette Position"), palette_menu)
        menu.append_section(None, view_section)
        file_section = Gio.Menu()
        file_section.append_submenu(_("Recent Files"), self._recent_menu)
        file_section.append(_("Save As…"), "win.save-as")
        file_section.append(_("Print…"), "win.print")
        menu.append_section(None, file_section)
        app_section = Gio.Menu()
        app_section.append(_("Preferences"), "win.preferences")
        app_section.append(_("Keyboard Shortcuts"), "win.shortcuts")
        app_section.append(_("About {app}").format(app=APP_NAME), "app.about")
        app_section.append(_("Quit"), "app.quit")
        menu.append_section(None, app_section)

        self._main_menu = Gtk.PopoverMenu.new_from_model(menu)
        self._main_menu.add_child(self._build_transform_row(), "transform")
        self._main_menu.add_child(self._build_zoom_row(), "zoom")
        menu_button = Gtk.MenuButton(
            icon_name="open-menu-symbolic", tooltip_text=_("Main menu"), primary=True
        )
        menu_button.set_popover(self._main_menu)
        menu_button.update_property([Gtk.AccessibleProperty.LABEL], [_("Main menu")])

        # Shown while an image is being read or written, which happens off the
        # UI thread so that a large file does not freeze the window.
        self._busy_spinner = Adw.Spinner(visible=False, tooltip_text=_("Working…"))

        header.pack_end(menu_button)
        header.pack_end(history)
        header.pack_end(self._busy_spinner)
        return header

    def _build_transform_row(self) -> Gtk.Widget:
        """Rotate and flip, as a row of buttons in the menu. A click closes the menu."""
        row = Gtk.Box(spacing=4, homogeneous=True, margin_top=4, margin_bottom=2)
        row.add_css_class("tempera-menu-row")
        for icon, text, action in (
            ("tempera-rotate-left-symbolic", "Rotate Counterclockwise", "win.rotate-ccw"),
            ("tempera-rotate-right-symbolic", "Rotate Clockwise", "win.rotate-cw"),
            ("tempera-flip-horizontal-symbolic", "Flip Horizontal", "win.flip-horizontal"),
            ("tempera-flip-vertical-symbolic", "Flip Vertical", "win.flip-vertical"),
        ):
            button = Gtk.Button(icon_name=icon, hexpand=True)
            self._add_shortcut_tooltip(button, text, action)
            button.set_action_name(action)
            button.connect("clicked", lambda *_args: self._main_menu.popdown())
            row.append(button)
        return row

    def _build_zoom_row(self) -> Gtk.Widget:
        """Zoom out, reset and in, and zoom to fit, in the menu. It stays open to click again."""
        row = Gtk.Box(spacing=6, margin_top=2, margin_bottom=4)
        row.add_css_class("tempera-menu-row")
        steps = Gtk.Box(hexpand=True)
        steps.add_css_class("linked")
        self._menu_zoom_label = Gtk.Label()
        self._menu_zoom_label.add_css_class("numeric")
        for icon, text, action in (
            ("tempera-zoom-out-symbolic", "Zoom out", "win.zoom-out"),
            (None, "Reset zoom", "win.zoom-reset"),
            ("tempera-zoom-in-symbolic", "Zoom in", "win.zoom-in"),
        ):
            if icon is None:
                button = Gtk.Button(child=self._menu_zoom_label, hexpand=True)
            else:
                button = Gtk.Button(icon_name=icon)
            self._add_shortcut_tooltip(button, text, action)
            button.set_action_name(action)
            steps.append(button)
        row.append(steps)
        fit = Gtk.Button(icon_name="tempera-zoom-fit-symbolic")
        self._add_shortcut_tooltip(fit, "Zoom to fit", "win.zoom-fit")
        fit.set_action_name("win.zoom-fit")
        row.append(fit)
        return row
