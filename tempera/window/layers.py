# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The layer actions, and showing or hiding the layers panel."""

from __future__ import annotations

from gi.repository import Adw, Gio, GLib, Gtk

from ..document import Document
from ..i18n import _

# The actions that change which layers there are or their order. Like the
# edits to the image, they wait until a button is let go, and land whatever
# floats first, on the layer it was placed on.
ARRANGING_ACTIONS = {
    "add-layer": lambda document: document.add_layer(),
    "duplicate-layer": lambda document: document.duplicate_layer(),
    "delete-layer": lambda document: document.delete_layer(),
    "raise-layer": lambda document: document.move_layer(document.current, document.current + 1),
    "lower-layer": lambda document: document.move_layer(document.current, document.current - 1),
    "merge-layer-down": lambda document: document.merge_down(),
    "flatten-image": lambda document: document.flatten(),
}


class LayersMixin:
    """The actions on layers, and the panel that shows them."""

    def _install_layer_actions(self) -> None:
        for name, change in ARRANGING_ACTIONS.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect(
                "activate", self._unless_dragging(lambda *_args, change=change: self._arrange(change))
            )
            self.add_action(action)

        move = Gio.SimpleAction.new("move-layer", GLib.VariantType.new("(ii)"))
        move.connect("activate", self._unless_dragging(self._on_move_layer))
        self.add_action(move)

        for name, step in (("layer-above", 1), ("layer-below", -1)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", self._unless_dragging(lambda *_args, step=step: self._step_layer(step)))
            self.add_action(action)

        rename = Gio.SimpleAction.new("rename-layer", None)
        rename.connect("activate", self._unless_dragging(lambda *_args: self._prompt_layer_name()))
        self.add_action(rename)

        show = Gio.SimpleAction.new("show-layer", None)
        show.connect("activate", self._unless_dragging(lambda *_args: self._show_layer()))
        self.add_action(show)

        panel = Gio.SimpleAction.new_stateful("layers-panel", None, GLib.Variant.new_boolean(False))
        panel.connect("change-state", self._on_layers_panel_changed)
        self.add_action(panel)
        self._sync_layer_actions()

    def _arrange(self, change) -> None:
        self.canvas.commit_floating()
        document = self.canvas.document
        count = len(document.layers)
        limit = document.layer_limit
        if change(document) is False and count >= limit:
            self.show_toast(
                _("A picture this size can have at most {count} layers").format(count=limit)
            )
        elif len(document.layers) > count:
            # A new layer is easy to lose track of with the panel hidden.
            self.show_layers_panel()

    def _on_move_layer(self, action, value: GLib.Variant) -> None:
        index, to = value.unpack()
        self.canvas.commit_floating()
        self.canvas.document.move_layer(index, to)

    def _step_layer(self, step: int) -> None:
        document = self.canvas.document
        index = document.current + step
        if 0 <= index < len(document.layers):
            self.canvas.select_layer(index)

    def _sync_layer_actions(self, *_args) -> None:
        """Offer only what makes sense for the layers there are, and the current one."""
        document = self.canvas.document
        count, current = len(document.layers), document.current
        enabled = {
            "add-layer": count < document.layer_limit,
            "duplicate-layer": count < document.layer_limit,
            "delete-layer": count > 1,
            "flatten-image": count > 1,
            "raise-layer": current < count - 1,
            "layer-above": current < count - 1,
            "lower-layer": current > 0,
            "layer-below": current > 0,
            "merge-layer-down": current > 0,
        }
        for name, value in enabled.items():
            self.lookup_action(name).set_enabled(value)
        self._show_current_layer(document)

    def _show_current_layer(self, document: Document) -> None:
        """Name the layer being painted on in the status bar, once there is more than one."""
        layer = document.layer
        self._layer_label.set_visible(len(document.layers) > 1)
        self._layer_label.set_label(
            layer.name if layer.shows else _("{name} (hidden)").format(name=layer.name)
        )
        self._layer_label.set_tooltip_text(_("The layer being painted on"))

    def _say_layer_hidden(self) -> None:
        """Say why a press painted nothing, and offer to put that right."""
        if self._hidden_toast is not None:
            # One at a time, however many presses there were.
            self._hidden_toast.dismiss()
        toast = Adw.Toast(
            title=_("“{name}” is hidden, so nothing was painted on it").format(
                name=self.canvas.document.layer.name
            ),
            use_markup=False,
            button_label=_("Show Layer"),
            action_name="win.show-layer",
        )
        toast.connect("dismissed", lambda *_args: setattr(self, "_hidden_toast", None))
        self._hidden_toast = toast
        self.toasts.add_toast(toast)

    def _show_layer(self) -> None:
        document = self.canvas.document
        index = document.current
        document.set_layer_visible(index, True)
        if document.layers[index].opacity <= 0:
            document.set_layer_opacity(index, 1.0)

    def _watch_layers(self, document: Document) -> None:
        document.connect("layers-changed", self._sync_layer_actions)
        self._layers_panel.set_document(document)
        self._sync_layer_actions()
        if len(document.layers) > 1:
            self.show_layers_panel()

    def _prompt_layer_name(self) -> None:
        document = self.canvas.document
        index = document.current
        entry = Gtk.Entry(text=document.layer.name, activates_default=True)
        entry.update_property([Gtk.AccessibleProperty.LABEL], [_("Layer name")])

        def rename() -> None:
            name = entry.get_text().strip()
            if name and index < len(document.layers):
                document.rename_layer(index, name)

        self.ask(_("Rename Layer"), "", "rename", _("Rename"), rename, extra=entry)
        entry.grab_focus()

    # The panel

    def show_layers_panel(self) -> None:
        self.lookup_action("layers-panel").change_state(GLib.Variant.new_boolean(True))

    def _on_layers_panel_changed(self, action, value: GLib.Variant) -> None:
        action.set_state(value)
        self._layers_strip.set_visible(value.get_boolean())
