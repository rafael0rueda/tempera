# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from gi.repository import Gdk, Graphene, Gtk

from .color import ColorState


class ToolIcon(Gtk.Widget):
    """A tool's icon, with the part that paints — a tip, a drip, a spray — in the primary colour.

    The icon itself follows the theme like any other; only the tip is drawn
    here, in whatever colour the tool would paint with now.
    """

    def __init__(self, icon_name: str, tip_icon_name: str, colors: ColorState):
        super().__init__()
        self._icon = Gtk.Image(icon_name=icon_name)
        self._icon.set_parent(self)
        self.tip_icon_name = tip_icon_name
        self._colors = colors
        self._watch = colors.connect("changed", lambda *_args: self.queue_draw())

    def do_dispose(self) -> None:
        if self._watch:
            self._colors.disconnect(self._watch)
            self._watch = 0
        self._icon.unparent()

    def do_get_request_mode(self) -> Gtk.SizeRequestMode:
        return Gtk.SizeRequestMode.CONSTANT_SIZE

    def do_measure(self, orientation: Gtk.Orientation, for_size: int):
        return self._icon.measure(orientation, for_size)

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        self._icon.allocate(width, height, baseline, None)

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        self.snapshot_child(self._icon, snapshot)
        if not self.tip_icon_name:
            return
        # The size the icon is drawn at, centred as the image centres it.
        width, height = self.get_width(), self.get_height()
        size = min(width, height)
        _minimum, natural, _, _ = self._icon.measure(Gtk.Orientation.HORIZONTAL, -1)
        size = min(size, natural) or size
        theme = Gtk.IconTheme.get_for_display(self.get_display())
        tip = theme.lookup_icon(
            self.tip_icon_name, None, size, self.get_scale_factor(), self.get_direction(), 0
        )
        snapshot.save()
        point = Graphene.Point()
        point.init((width - size) / 2, (height - size) / 2)
        snapshot.translate(point)
        tip.snapshot_symbolic(snapshot, size, size, [self.tip_color])
        snapshot.restore()

    @property
    def tip_color(self) -> Gdk.RGBA:
        return self._colors.primary
