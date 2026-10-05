# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Keyboard Shortcuts window: every shortcut, and a way to change it."""

from __future__ import annotations

from gi.repository import Adw, Gdk, Gtk

from . import shortcuts
from .i18n import _
from .shortcuts import CANVAS_KEYS, SHORTCUT_GROUPS, Shortcut


class ShortcutsDialog(Adw.PreferencesDialog):
    def __init__(self, application: Gtk.Application):
        super().__init__(title=_("Keyboard Shortcuts"), search_enabled=True)
        self._application = application
        # action -> (key label, reset button)
        self._rows: dict[str, tuple[Adw.ShortcutLabel, Gtk.Button]] = {}

        page = Adw.PreferencesPage()
        for title, items in SHORTCUT_GROUPS:
            group = Adw.PreferencesGroup(title=title)
            for shortcut in items:
                group.add(self._build_row(shortcut))
            page.add(group)

        canvas_group = Adw.PreferencesGroup(
            title=_("On the Canvas"),
            description=_(
                "Used while something is selected, pasted or typed. These cannot be changed."
            ),
        )
        for title, subtitle, accelerator in CANVAS_KEYS:
            row = Adw.ActionRow(title=title, subtitle=subtitle or "")
            row.add_suffix(Adw.ShortcutLabel(accelerator=accelerator, valign=Gtk.Align.CENTER))
            canvas_group.add(row)
        page.add(canvas_group)

        reset_group = Adw.PreferencesGroup()
        self._reset_all_row = Adw.ButtonRow(title=_("Reset All Shortcuts"))
        self._reset_all_row.add_css_class("destructive-action")
        self._reset_all_row.connect("activated", lambda *_args: self._confirm_reset_all())
        reset_group.add(self._reset_all_row)
        page.add(reset_group)

        self.add(page)
        self._sync()

    def _build_row(self, shortcut: Shortcut) -> Adw.ActionRow:
        row = Adw.ActionRow(title=shortcut.title, activatable=True)
        row.connect("activated", lambda *_args: self._record(shortcut))

        reset = Gtk.Button(
            icon_name="tempera-undo-symbolic",
            tooltip_text=_("Reset to default"),
            valign=Gtk.Align.CENTER,
        )
        reset.update_property([Gtk.AccessibleProperty.LABEL], [_("Reset to default")])
        reset.add_css_class("flat")
        reset.connect("clicked", lambda *_args: self._reset(shortcut))
        row.add_suffix(reset)

        keys = Adw.ShortcutLabel(disabled_text=_("None"), valign=Gtk.Align.CENTER)
        row.add_suffix(keys)

        self._rows[shortcut.action] = (keys, reset)
        return row

    def _sync(self) -> None:
        for action, (keys, reset) in self._rows.items():
            keys.set_accelerator(" ".join(shortcuts.keys_for(action)))
            reset.set_visible(shortcuts.is_customized(action))
        self._reset_all_row.set_sensitive(shortcuts.any_customized())

    # Recording a new key

    def _record(self, shortcut: Shortcut) -> None:
        prompt = Adw.AlertDialog(
            heading=_("Set Shortcut"),
            body=_("Press the new shortcut for “{name}”.").format(name=shortcut.title),
        )
        hint = Gtk.Label(label=_("Esc cancels, Backspace removes the shortcut"), wrap=True)
        hint.add_css_class("dim-label")
        prompt.set_extra_child(hint)
        prompt.add_response("cancel", _("Cancel"))
        chosen: list[str | None] = []

        # Capture phase, so the dialog's own keys (Esc, Enter, Tab) come here
        # first; the application's shortcuts are switched off meanwhile.
        controller = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)

        def on_key(controller, keyval, keycode, state) -> bool:
            event = controller.get_current_event()
            if event.is_modifier():
                return Gdk.EVENT_PROPAGATE
            mods = state & Gtk.accelerator_get_default_mod_mask()
            if not mods and keyval == Gdk.KEY_Escape:
                prompt.close()
                return Gdk.EVENT_STOP
            if not mods and keyval == Gdk.KEY_BackSpace:
                chosen.append(None)
                prompt.close()
                return Gdk.EVENT_STOP
            accel = shortcuts.accelerator_from_key(keyval, state, event.get_consumed_modifiers())
            problem = shortcuts.problem_with(accel)
            if problem is not None:
                hint.set_label(problem)
                hint.remove_css_class("dim-label")
                hint.add_css_class("error")
                return Gdk.EVENT_STOP
            chosen.append(accel)
            prompt.close()
            return Gdk.EVENT_STOP

        controller.connect("key-pressed", on_key)
        prompt.add_controller(controller)

        def on_closed(*_args):
            shortcuts.suspend(self._application, False)
            if chosen:
                self._assign(shortcut, chosen[0])

        prompt.connect("closed", on_closed)
        shortcuts.suspend(self._application, True)
        prompt.present(self)

    def _assign(self, shortcut: Shortcut, accel: str | None) -> None:
        conflict = None if accel is None else shortcuts.find_conflict(accel, shortcut.action)
        if conflict is None:
            shortcuts.assign(self._application, shortcut.action, accel)
            self._sync()
            return

        others = len(shortcuts.keys_for(conflict.action)) > 1
        consequence = (
            _("“{name}” keeps its other shortcuts.").format(name=conflict.title)
            if others
            else _("“{name}” will be left without a shortcut.").format(name=conflict.title)
        )
        dialog = Adw.AlertDialog(
            heading=_("Reassign Shortcut?"),
            body=_("{key} is already used by “{name}”. {consequence}").format(
                key=shortcuts.label(accel), name=conflict.title, consequence=consequence
            ),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("reassign", _("Reassign"))
        dialog.set_response_appearance("reassign", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("reassign")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == "reassign":
                shortcuts.assign(self._application, shortcut.action, accel)
                self._sync()

        dialog.connect("response", on_response)
        dialog.present(self)

    # Resetting

    def _reset(self, shortcut: Shortcut) -> None:
        shortcuts.reset(self._application, shortcut.action)
        self._sync()

    def _confirm_reset_all(self) -> None:
        dialog = Adw.AlertDialog(
            heading=_("Reset All Shortcuts?"),
            body=_("Every shortcut goes back to its default key."),
        )
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("reset", _("Reset"))
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == "reset":
                shortcuts.reset(self._application)
                self._sync()

        dialog.connect("response", on_response)
        dialog.present(self)
