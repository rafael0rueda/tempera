# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Keyboard shortcuts: the defaults, the user's changes to them, and applying both.

Accelerators belong to the application, so a change reaches every open window at
once. Only what differs from the defaults is saved, which lets a later version
change a default for everyone who has not picked their own key.
"""

from __future__ import annotations

from dataclasses import dataclass

from gi.repository import Gdk, Gtk

from . import settings
from .i18n import _
from .tools import SHAPE_CLASSES, TOOL_CLASSES


@dataclass(frozen=True)
class Shortcut:
    action: str
    title: str
    defaults: tuple[str, ...]


TOOL_KEYS = {
    "pencil": "p",
    "brush": "b",
    "airbrush": "a",
    "eraser": "e",
    "text": "t",
    "fill": "f",
    "picker": "k",
    "select": "s",
    "lasso": "<Shift>s",
}

# Each shape has a key that also takes up the Shapes tool, so the Shapes
# button itself needs none.
SHAPE_KEYS = {
    "line": "l",
    "curve": "c",
    "arrow": "w",
    "rectangle": "r",
    "rounded-rectangle": "u",
    "ellipse": "o",
    "triangle": "i",
    "star": "h",
    "polygon": "g",
}

# Actions saved under another name by an older Tempera: 1.0 had a tool for
# each of the first three shapes.
_RENAMED = {f"win.tool::{shape}": f"win.shape::{shape}" for shape in ("line", "rectangle", "ellipse")}

SHORTCUT_GROUPS: list[tuple[str, list[Shortcut]]] = [
    (
        _("File"),
        [
            Shortcut("win.new", _("New Image"), ("<Control>n",)),
            Shortcut("win.open", _("Open Image"), ("<Control>o",)),
            Shortcut("win.save", _("Save"), ("<Control>s",)),
            Shortcut("win.save-as", _("Save As"), ("<Control><Shift>s",)),
            Shortcut("win.print", _("Print"), ("<Control>p",)),
        ],
    ),
    (
        _("Edit"),
        [
            Shortcut("win.undo", _("Undo"), ("<Control>z",)),
            Shortcut("win.redo", _("Redo"), ("<Control><Shift>z", "<Control>y")),
            Shortcut("win.select-all", _("Select All"), ("<Control>a",)),
            Shortcut("win.cut", _("Cut"), ("<Control>x",)),
            Shortcut("win.copy", _("Copy"), ("<Control>c",)),
            Shortcut("win.paste", _("Paste"), ("<Control>v",)),
        ],
    ),
    (
        _("Image"),
        [
            Shortcut("win.resize", _("Canvas Size"), ("<Control>e",)),
            Shortcut("win.scale", _("Resize Image"), ("<Control>r",)),
            Shortcut("win.crop", _("Crop to Selection"), ()),
            Shortcut("win.rotate-cw", _("Rotate Clockwise"), ()),
            Shortcut("win.rotate-ccw", _("Rotate Counterclockwise"), ("<Control><Shift>r",)),
            Shortcut("win.flip-horizontal", _("Flip Horizontal"), ()),
            Shortcut("win.flip-vertical", _("Flip Vertical"), ()),
        ],
    ),
    (
        _("View"),
        [
            Shortcut("win.zoom-in", _("Zoom In"), ("<Control>plus", "<Control>equal", "<Control>KP_Add")),
            Shortcut("win.zoom-out", _("Zoom Out"), ("<Control>minus", "<Control>KP_Subtract")),
            Shortcut("win.zoom-reset", _("Reset Zoom"), ("<Control>0", "<Control>KP_0")),
            Shortcut("win.zoom-fit", _("Zoom to Fit"), ("<Control>9", "<Control>KP_9")),
            Shortcut("win.pixel-grid", _("Show Pixel Grid"), ("<Control>g",)),
            Shortcut("win.layers-panel", _("Show Layers"), ("<Control>l",)),
        ],
    ),
    (
        _("Layers"),
        [
            Shortcut("win.add-layer", _("New Layer"), ("<Control><Shift>n",)),
            Shortcut("win.duplicate-layer", _("Duplicate Layer"), ("<Control><Shift>d",)),
            Shortcut("win.delete-layer", _("Delete Layer"), ()),
            Shortcut("win.rename-layer", _("Rename Layer"), ("F2",)),
            Shortcut("win.raise-layer", _("Move Layer Up"), ("<Control>bracketright",)),
            Shortcut("win.lower-layer", _("Move Layer Down"), ("<Control>bracketleft",)),
            Shortcut("win.layer-above", _("Select Layer Above"), ("<Alt>bracketright",)),
            Shortcut("win.layer-below", _("Select Layer Below"), ("<Alt>bracketleft",)),
            Shortcut("win.merge-layer-down", _("Merge Down"), ("<Control>m",)),
            Shortcut("win.flatten-image", _("Flatten Image"), ()),
        ],
    ),
    (
        _("Tools"),
        [
            Shortcut(
                f"win.tool::{tool.id}",
                tool.label,
                (TOOL_KEYS[tool.id],) if tool.id in TOOL_KEYS else (),
            )
            for tool in TOOL_CLASSES
        ],
    ),
    (
        _("Shapes"),
        [
            Shortcut(f"win.shape::{shape.id}", shape.label, (SHAPE_KEYS[shape.id],))
            for shape in SHAPE_CLASSES
        ],
    ),
    (
        _("Colors"),
        [
            Shortcut("win.swap-colors", _("Swap Colors"), ("x",)),
            Shortcut("win.size-down", _("Smaller Brush or Text"), ("bracketleft",)),
            Shortcut("win.size-up", _("Bigger Brush or Text"), ("bracketright",)),
        ],
    ),
    (
        _("Application"),
        [
            Shortcut("win.preferences", _("Preferences"), ("<Control>comma",)),
            Shortcut("win.shortcuts", _("Keyboard Shortcuts"), ("<Control>question",)),
            Shortcut("app.quit", _("Quit"), ("<Control>q",)),
        ],
    ),
]

SHORTCUTS = {shortcut.action: shortcut for _group, items in SHORTCUT_GROUPS for shortcut in items}

# Keys the canvas handles itself while something is selected, pasted or typed.
# They are listed for reference but cannot be changed.
CANVAS_KEYS = [
    (_("Nudge a selection or paste"), _("Hold Shift to move 10 pixels"), "Left Right Up Down"),
    (_("Land a paste"), None, "Return"),
    (_("Land typed text"), None, "<Control>Return"),
    (_("Drop a selection, discard a paste or text"), None, "Escape"),
    (_("Clear a selection"), None, "Delete"),
]

_RESERVED_KEYS = {
    Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down,
    Gdk.KEY_KP_Left, Gdk.KEY_KP_Right, Gdk.KEY_KP_Up, Gdk.KEY_KP_Down,
    Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter,
    Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab, Gdk.KEY_KP_Tab,
    Gdk.KEY_Escape, Gdk.KEY_BackSpace, Gdk.KEY_Delete, Gdk.KEY_KP_Delete,
}

_COMMAND_MODIFIERS = (
    Gdk.ModifierType.CONTROL_MASK
    | Gdk.ModifierType.ALT_MASK
    | Gdk.ModifierType.SUPER_MASK
    | Gdk.ModifierType.META_MASK
)

# While a new key is being recorded, no shortcut may fire.
_suspended = False


# Reading and checking accelerators


def normalize(accel: str) -> str | None:
    """One spelling per key combination, or None if it does not parse."""
    ok, keyval, mods = Gtk.accelerator_parse(accel)
    if not ok or keyval == 0:
        return None
    return Gtk.accelerator_name(keyval, mods)


def label(accel: str) -> str:
    """How an accelerator reads to a person, e.g. "Ctrl+N"."""
    _ok, keyval, mods = Gtk.accelerator_parse(accel)
    return Gtk.accelerator_get_label(keyval, mods)


def is_bare(accel: str) -> bool:
    """Whether a key types a character in a text box: no Ctrl, Alt or Super held."""
    _ok, _keyval, mods = Gtk.accelerator_parse(accel)
    return not mods & _COMMAND_MODIFIERS


def accelerator_from_key(keyval: int, state: Gdk.ModifierType, consumed: Gdk.ModifierType) -> str:
    """Turn a key press into an accelerator the way the user thinks of it.

    Shift+S stays Shift+S rather than becoming a capital S, while a key the
    layout needs Shift for, such as "?", drops the Shift it used up.
    """
    mods = state & Gtk.accelerator_get_default_mod_mask()
    lower = Gdk.keyval_to_lower(keyval)
    if lower != Gdk.keyval_to_upper(keyval):
        keyval = lower
    else:
        mods &= ~(consumed & Gdk.ModifierType.SHIFT_MASK)
    return Gtk.accelerator_name(keyval, mods)


def problem_with(accel: str) -> str | None:
    """Why an accelerator cannot be used as a shortcut, or None if it can."""
    ok, keyval, mods = Gtk.accelerator_parse(accel)
    if not ok or keyval == 0:
        return _("That key cannot be used as a shortcut.")
    if keyval in _RESERVED_KEYS:
        return _(
            "{key} is kept for the canvas and dialogs, so it cannot be a shortcut."
        ).format(key=label(accel))
    if not Gtk.accelerator_valid(keyval, mods):
        return _("That key cannot be used as a shortcut.")
    return None


# The user's shortcuts


# The last overrides read and what they came to once checked, since checking
# every key again for each tooltip adds up.
_checked: tuple[dict[str, list[str]], dict[str, list[str]]] | None = None


def _overrides() -> dict[str, list[str]]:
    """The user's changes that are still usable, as a copy the caller may change."""
    global _checked
    saved = settings.load_shortcut_overrides()
    if _checked is None or _checked[0] != saved:
        _checked = (saved, _check(saved))
    return {action: list(keys) for action, keys in _checked[1].items()}


def _check(saved: dict[str, list[str]]) -> dict[str, list[str]]:
    overrides = {}
    for action, accels in saved.items():
        action = _RENAMED.get(action, action)
        if action not in SHORTCUTS:
            continue
        normalized = [normalize(accel) for accel in accels]
        # A damaged entry falls back to the default rather than half-applying.
        if all(accel is not None and problem_with(accel) is None for accel in normalized):
            overrides[action] = normalized
    return overrides


def keys_for(action: str, overrides: dict[str, list[str]] | None = None) -> list[str]:
    if overrides is None:
        overrides = _overrides()
    if action in overrides:
        return list(overrides[action])
    return list(SHORTCUTS[action].defaults)


def is_customized(action: str) -> bool:
    return action in _overrides()


def any_customized() -> bool:
    return bool(_overrides())


def find_conflict(accel: str, action: str) -> Shortcut | None:
    """Another action that already answers to this key."""
    wanted = normalize(accel)
    overrides = _overrides()
    for other in SHORTCUTS.values():
        if other.action == action:
            continue
        if wanted in (normalize(key) for key in keys_for(other.action, overrides)):
            return other
    return None


def _set_keys(overrides: dict[str, list[str]], action: str, keys: list[str]) -> None:
    defaults = [normalize(key) for key in SHORTCUTS[action].defaults]
    if [normalize(key) for key in keys] == defaults:
        overrides.pop(action, None)
    else:
        overrides[action] = keys


def assign(application: Gtk.Application, action: str, accel: str | None) -> None:
    """Give an action a single key (None disables it), taking the key from any other action."""
    overrides = _overrides()
    if accel is not None:
        accel = normalize(accel)
        conflict = find_conflict(accel, action)
        if conflict is not None:
            remaining = [
                key for key in keys_for(conflict.action, overrides) if normalize(key) != accel
            ]
            _set_keys(overrides, conflict.action, remaining)
    _set_keys(overrides, action, [] if accel is None else [accel])
    settings.save_shortcut_overrides(overrides)
    shortcuts_changed(application)


def reset(application: Gtk.Application, action: str | None = None) -> None:
    """Back to the default keys for one action, or for all of them.

    A default key another action has since been given stays with that action,
    so a reset never leaves two actions sharing a key.
    """
    overrides = _overrides()
    actions = list(overrides) if action is None else [action]
    for name in actions:
        overrides.pop(name, None)
    for name in actions:
        taken = {
            normalize(key)
            for other in SHORTCUTS
            if other != name
            for key in keys_for(other, overrides)
        }
        defaults = [key for key in SHORTCUTS[name].defaults if normalize(key) not in taken]
        _set_keys(overrides, name, defaults)
    settings.save_shortcut_overrides(overrides)
    shortcuts_changed(application)


# Applying them


def apply_accels(application: Gtk.Application) -> None:
    """Register every shortcut with the application.

    Bare keys are left out while any window is typing into a text box, so that
    typing an "s" does not switch to the select tool.
    """
    typing = any(
        getattr(getattr(window, "canvas", None), "is_typing", False)
        for window in application.get_windows()
    )
    overrides = _overrides()
    for action in SHORTCUTS:
        keys = [] if _suspended else keys_for(action, overrides)
        if typing:
            keys = [key for key in keys if not is_bare(key)]
        application.set_accels_for_action(action, keys)


def shortcuts_changed(application: Gtk.Application) -> None:
    apply_accels(application)
    for window in application.get_windows():
        refresh = getattr(window, "refresh_shortcut_tooltips", None)
        if refresh is not None:
            refresh()


def suspend(application: Gtk.Application, suspended: bool) -> None:
    global _suspended
    _suspended = suspended
    apply_accels(application)


def tooltip(text: str, action: str) -> str:
    keys = keys_for(action)
    return _("{text} ({key})").format(text=text, key=label(keys[0])) if keys else text
