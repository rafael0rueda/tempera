# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""What outlives the window: crash recovery copies and remembered preferences."""

from __future__ import annotations

from gi.repository import Gdk, GLib

from ..color import MAX_RECENT_COLORS, rgba
from ..document import Document
from ..settings import load_setting, save_settings
from ..text import font_without_size
from ..tools import DENSITY_RANGE, SHAPE_IDS, SHAPES_TOOL_ID, TOOL_CLASSES
from .options_bar import BRUSH_SIZE_RANGE, TOLERANCE_RANGE


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

    def _keep_recovery_copy(self) -> bool:
        """Keep a fresh copy of unsaved work, when there is any the last copy lacks."""
        document = self.canvas.document
        if not document.modified:
            self._forget_recovery_copy()
        elif self._kept_changes != self._changes:
            self._kept_changes = self._changes
            self._recovery.save(
                document,
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
        self.canvas.fill_shapes = load_setting("shape-fill") == "1"
        self.canvas.outline_shapes = load_setting("shape-outline") != "0" or not self.canvas.fill_shapes
        self._density_scale.set_value(
            _whole(load_setting("airbrush-density"), self.canvas.airbrush_density, DENSITY_RANGE)
        )
        if load_setting("pixel-grid") == "1":
            self.lookup_action("pixel-grid").change_state(GLib.Variant.new_boolean(True))
        if load_setting("layers-panel") == "1":
            self.show_layers_panel()
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
        self._sync_tool_options()

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
                "shape-fill": "1" if self.canvas.fill_shapes else "0",
                "shape-outline": "1" if self.canvas.outline_shapes else "0",
                "font": self.canvas.font,
                "fill-tolerance": self.canvas.fill_tolerance,
                "airbrush-density": self.canvas.airbrush_density,
                "pixel-grid": "1" if self.canvas.show_pixel_grid else "0",
                "layers-panel": "1" if self._layers_strip.get_visible() else "0",
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
