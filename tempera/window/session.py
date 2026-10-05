# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""What outlives the window: crash recovery copies and remembered preferences."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from gi.repository import Gdk, GLib

from ..color import MAX_RECENT_COLORS, rgba
from ..color_editor import MAX_CUSTOM_COLORS
from ..document import DEFAULT_HEIGHT, DEFAULT_WIDTH, MAX_SIZE, Document
from ..i18n import _
from ..settings import load_setting, save_settings
from ..text import ALIGNMENTS, TEXT_SWITCHES, font_without_size
from ..tools import DENSITY_RANGE, SHAPE_IDS, SHAPES_TOOL_ID, TOOL_CLASSES
from .options_bar import BRUSH_SIZE_RANGE, TOLERANCE_RANGE


@dataclass
class Option:
    """One thing remembered from one session to the next."""

    # What it is saved under in the settings file.
    key: str
    # How it is now, as text.
    read: Callable[[], str]
    # Put it back from saved text: empty when nothing was saved, and possibly
    # nonsense from a damaged settings file, which is to be ignored.
    restore: Callable[[str], None]


def _whole(text: str, fallback: int, limits: tuple[int, int] | None = None) -> int:
    """A remembered number, ignoring anything a damaged settings file may hold."""
    try:
        value = int(text)
    except ValueError:
        return fallback
    if limits is not None:
        value = max(limits[0], min(value, limits[1]))
    return value


class SessionMixin:
    """Crash recovery copies, and the preferences put back when a window opens."""

    def _note_change(self) -> None:
        self._changes += 1

    def _keep_recovery_copy(self, done=None) -> bool:
        """Keep a fresh copy of unsaved work, when there is any the last copy lacks.

        `done` hears how it went: None, or why the copy could not be kept.
        """
        document = self.canvas.document
        if not document.modified:
            self._forget_recovery_copy()
        elif self._kept_changes != self._changes:
            self._kept_changes = self._changes

            def kept(error: str | None) -> None:
                self._say_recovery_failed(error)
                if done is not None:
                    done(error)

            self._recovery.save(
                document,
                {
                    "title": document.title,
                    "file": document.file.get_uri() if document.file is not None else None,
                },
                kept,
            )
        return GLib.SOURCE_CONTINUE

    def _say_recovery_failed(self, error: str | None) -> None:
        """Say that work is no longer being kept safe: once, not every half minute."""
        if error is None:
            self._recovery_failed = False
        elif not self._recovery_failed:
            self._recovery_failed = True
            self.show_toast(
                _("Could not keep a recovery copy of unsaved work: {message}").format(message=error)
            )

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

    def show_recovered(self, document: Document, done=None) -> None:
        """Take over an image brought back after a crash, and keep a copy of it straight away.

        `done` hears how keeping it went: None, or why it could not be kept.
        """
        self._set_document(document)
        self._keep_recovery_copy(done)

    def _restore_window_size(self) -> None:
        width = _whole(load_setting("window-width"), 1120)
        height = _whole(load_setting("window-height"), 800)
        self.set_default_size(width, height)
        if load_setting("window-maximized") == "1":
            self.maximize()

    def _switch(self, key: str, action: str | None = None) -> Option:
        """A yes or no kept by an action, such as whether the pixel grid shows."""
        action = self.lookup_action(action or key)

        def restore(text: str) -> None:
            if text in ("0", "1"):
                action.change_state(GLib.Variant.new_boolean(text == "1"))

        return Option(key, lambda: "1" if action.get_state().get_boolean() else "0", restore)

    def _choice(self, key: str, values: tuple[str, ...] | None = None) -> Option:
        """One of a few named choices kept by an action, such as how outlines are drawn."""
        action = self.lookup_action(key)

        def restore(text: str) -> None:
            if text and (values is None or text in values):
                action.change_state(GLib.Variant.new_string(text))

        return Option(key, lambda: action.get_state().get_string(), restore)

    def _number(self, key: str, attribute: str, scale, limits: tuple[int, int]) -> Option:
        """A whole number the canvas works to, set with a slider, such as how far a fill spreads."""

        def restore(text: str) -> None:
            if text:
                # The slider tells the canvas.
                scale.set_value(_whole(text, getattr(self.canvas, attribute), limits))

        return Option(key, lambda: str(getattr(self.canvas, attribute)), restore)

    def _colors(self, key: str, attribute: str, limit: int) -> Option:
        """A row of colours, such as those painted with lately."""

        def restore(text: str) -> None:
            colors = [rgba(spec) for spec in text.split()]
            setattr(self.colors, attribute, [color for color in colors if color is not None][:limit])

        return Option(
            key, lambda: " ".join(color.to_string() for color in getattr(self.colors, attribute)), restore
        )

    def _color(self, key: str, attribute: str) -> Option:
        def restore(text: str) -> None:
            color = Gdk.RGBA()
            if text and color.parse(text):
                setattr(self.colors, attribute, color)

        return Option(key, lambda: getattr(self.colors, attribute).to_string(), restore)

    def _options(self) -> list[Option]:
        """Everything remembered from one session to the next, in the order it is put back.

        Each is declared once, here: the key it is saved under, how it reads
        as text, and how that text is put back. Saving and restoring both go
        through this list, so nothing can be saved and never restored.
        """
        canvas = self.canvas

        def restore_tool(text: str) -> None:
            if any(text == candidate.id for candidate in TOOL_CLASSES):
                self.lookup_action("tool").change_state(GLib.Variant.new_string(text))

        def restore_shape(text: str) -> None:
            if text in SHAPE_IDS:
                self.lookup_action("shape").change_state(GLib.Variant.new_string(text))

        def restore_brush_size(text: str) -> None:
            canvas.brush_size = _whole(text, canvas.brush_size, BRUSH_SIZE_RANGE)

        def restore_font(text: str) -> None:
            if text:
                canvas.set_font(text)
                self._font_label.set_label(font_without_size(text))

        def restore_fill(text: str) -> None:
            canvas.fill_shapes = text == "1"

        def restore_outline(text: str) -> None:
            # Never neither: a shape with no outline and no fill is nothing at all.
            canvas.outline_shapes = text != "0" or not canvas.fill_shapes

        def restore_erasing(text: str) -> None:
            self._erase_check.set_active(text == "1")

        def restore_layers_panel(text: str) -> None:
            if text == "1":
                self.show_layers_panel()

        def restore_jpeg_quality(text: str) -> None:
            self._last_jpeg_quality = _whole(text, 90, (1, 100))

        def restore_new_image(text: str) -> None:
            width, height, transparent = (text.split() + ["", "", ""])[:3]
            self._new_image = (
                _whole(width, DEFAULT_WIDTH, (1, MAX_SIZE)),
                _whole(height, DEFAULT_HEIGHT, (1, MAX_SIZE)),
                transparent == "1",
            )

        def new_image() -> str:
            width, height, transparent = self._new_image
            return f"{width} {height} {'1' if transparent else '0'}"

        return [
            Option("shape", lambda: canvas.shapes.shape.id, restore_shape),
            Option("tool", lambda: canvas.active_tool.id, restore_tool),
            Option("brush-size", lambda: str(canvas.brush_size), restore_brush_size),
            Option("font", lambda: canvas.font, restore_font),
            self._number("fill-tolerance", "fill_tolerance", self._tolerance_scale, TOLERANCE_RANGE),
            self._number("wand-tolerance", "wand_tolerance", self._wand_tolerance_scale, TOLERANCE_RANGE),
            Option("shape-fill", lambda: "1" if canvas.fill_shapes else "0", restore_fill),
            Option("shape-outline", lambda: "1" if canvas.outline_shapes else "0", restore_outline),
            self._number("airbrush-density", "airbrush_density", self._density_scale, DENSITY_RANGE),
            Option(
                "erase-to-nothing", lambda: "1" if canvas.erase_to_transparency else "0", restore_erasing
            ),
            self._switch("pixel-grid"),
            *(self._switch(f"text-{name}") for name in TEXT_SWITCHES),
            self._choice("text-align", ALIGNMENTS),
            self._choice("line-style"),
            self._choice("arrow-ends"),
            self._choice("shape-edges"),
            self._switch("transparent-selection"),
            Option(
                "layers-panel",
                lambda: "1" if self._layers_strip.get_visible() else "0",
                restore_layers_panel,
            ),
            Option("jpeg-quality", lambda: str(self._last_jpeg_quality), restore_jpeg_quality),
            Option("new-image", new_image, restore_new_image),
            self._color("primary-color", "primary"),
            self._color("secondary-color", "secondary"),
            self._colors("recent-colors", "recent", MAX_RECENT_COLORS),
            self._colors("custom-colors", "custom", MAX_CUSTOM_COLORS),
        ]

    def _restore_preferences(self) -> None:
        """Put back the tool, sizes, font and colours from the last time."""
        if load_setting("tool") in SHAPE_IDS:
            # Tempera 1.0 had a tool for each shape.
            save_settings({"shape": load_setting("tool"), "tool": SHAPES_TOOL_ID})
        for option in self._options():
            option.restore(load_setting(option.key))
        self._color_bar.refresh()
        self._sync_size_scale()
        self._sync_tool_options()

    def _save_preferences(self) -> None:
        width, height = self.get_default_size()
        save_settings(
            {
                "window-width": width,
                "window-height": height,
                "window-maximized": "1" if self.is_maximized() else "0",
                **{option.key: option.read() for option in self._options()},
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
