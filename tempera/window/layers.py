# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The layer actions, and showing or hiding the layers panel."""

from __future__ import annotations

from gi.repository import Adw, Gio, GLib, Gtk

from ..document import MAX_LAYERS, Document
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

        panel = Gio.SimpleAction.new_stateful("layers-panel", None, GLib.Variant.new_boolean(False))
        panel.connect("change-state", self._on_layers_panel_changed)
        self.add_action(panel)
        self._sync_layer_actions()

    def _arrange(self, change) -> None:
        self.canvas.commit_floating()
        document = self.canvas.document
        count = len(document.layers)
        if change(document) is False and count >= MAX_LAYERS:
            self.show_toast(_("A picture can have at most {count} layers").format(count=MAX_LAYERS))
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
            "add-layer": count < MAX_LAYERS,
            "duplicate-layer": count < MAX_LAYERS,
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
        dialog = Adw.AlertDialog(heading=_("Rename Layer"))
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("rename", _("Rename"))
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            name = entry.get_text().strip()
            if response == "rename" and name and index < len(document.layers):
                document.rename_layer(index, name)

        dialog.connect("response", on_response)
        dialog.present(self)
        entry.grab_focus()

    # The panel

    def show_layers_panel(self) -> None:
        self.lookup_action("layers-panel").change_state(GLib.Variant.new_boolean(True))

    def _on_layers_panel_changed(self, action, value: GLib.Variant) -> None:
        action.set_state(value)
        self._layers_strip.set_visible(value.get_boolean())
