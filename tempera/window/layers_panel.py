# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The layers panel: the layers of the picture, top first, and the buttons to arrange them."""

from __future__ import annotations

from typing import Callable

import cairo
from gi.repository import Gdk, Gio, GLib, GObject, Graphene, Gsk, Gtk, Pango

from ..canvas import Canvas
from ..canvas.tiles import surface_texture
from ..document import Document, Layer
from ..i18n import _
from ..interface_size import scaled

# The thumbnail's box, at the default interface size; the picture keeps its
# shape inside it.
THUMBNAIL_WIDTH = 48
THUMBNAIL_HEIGHT = 36
# How long after a change the thumbnails catch up, so a run of quick changes
# redraws them once.
THUMBNAIL_DELAY_MS = 150
CHECKER_SIZE = 4


def thumbnail(surface: cairo.ImageSurface, width: int, height: int) -> Gdk.Texture:
    """The layer shrunk to fit a box, keeping its shape."""
    scale = min(width / surface.get_width(), height / surface.get_height())
    small = cairo.ImageSurface(
        cairo.FORMAT_ARGB32,
        max(1, round(surface.get_width() * scale)),
        max(1, round(surface.get_height() * scale)),
    )
    cr = cairo.Context(small)
    cr.scale(scale, scale)
    cr.set_source_surface(surface, 0, 0)
    # Averages what it shrinks, so thin lines still show; a few milliseconds
    # even for the largest canvas.
    cr.get_source().set_filter(cairo.FILTER_GOOD)
    cr.paint()
    small.flush()
    return surface_texture(small, 0, 0, small.get_width(), small.get_height())


class LayerThumbnail(Gtk.Widget):
    """A small picture of one layer, over a checkerboard where it is see-through."""

    def __init__(self):
        super().__init__(valign=Gtk.Align.CENTER, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.texture: Gdk.Texture | None = None
        self.add_css_class("tempera-layer-thumbnail")

    def set_texture(self, texture: Gdk.Texture | None) -> None:
        self.texture = texture
        self.queue_draw()

    def do_measure(self, orientation: Gtk.Orientation, for_size: int):
        size = scaled(THUMBNAIL_WIDTH if orientation == Gtk.Orientation.HORIZONTAL else THUMBNAIL_HEIGHT)
        return size, size, -1, -1

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        if self.texture is None:
            return
        width, height = self.get_width(), self.get_height()
        scale = min(width / self.texture.get_width(), height / self.texture.get_height())
        shown_width, shown_height = self.texture.get_width() * scale, self.texture.get_height() * scale
        bounds = Graphene.Rect().init(
            round((width - shown_width) / 2), round((height - shown_height) / 2), shown_width, shown_height
        )
        snapshot.push_clip(bounds)
        light = Gdk.RGBA(red=1, green=1, blue=1, alpha=1)
        dark = Gdk.RGBA(red=0.8, green=0.8, blue=0.8, alpha=1)
        snapshot.append_color(light, bounds)
        tile = CHECKER_SIZE * 2
        snapshot.push_repeat(bounds, Graphene.Rect().init(0, 0, tile, tile))
        snapshot.append_color(dark, Graphene.Rect().init(0, 0, CHECKER_SIZE, CHECKER_SIZE))
        snapshot.append_color(dark, Graphene.Rect().init(CHECKER_SIZE, CHECKER_SIZE, CHECKER_SIZE, CHECKER_SIZE))
        snapshot.pop()
        snapshot.append_scaled_texture(self.texture, Gsk.ScalingFilter.LINEAR, bounds)
        snapshot.pop()


class LayerDrag(GObject.Object):
    """What a row carries when it is dragged to another place in the list."""

    def __init__(self, index: int):
        super().__init__()
        self.index = index


class LayerRow(Gtk.ListBoxRow):
    """One layer: whether it shows, a picture of it, and its name."""

    def __init__(self, panel: LayersPanel, layer: Layer, index: int):
        super().__init__()
        self.panel = panel
        self.layer = layer
        self.index = index
        self.add_css_class("tempera-layer-row")

        box = Gtk.Box(spacing=8)
        self.eye = Gtk.ToggleButton(valign=Gtk.Align.CENTER)
        self.eye.add_css_class("flat")
        self.eye.add_css_class("circular")
        self.eye.add_css_class("tempera-layer-eye")
        self.eye.connect("toggled", self._on_eye_toggled)
        box.append(self.eye)

        self.thumbnail = LayerThumbnail()
        box.append(self.thumbnail)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, hexpand=True)
        # A long name is cut short rather than let it widen the panel.
        self.name = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=1)
        text.append(self.name)
        # Shown only for a layer that is not fully opaque.
        self.opacity = Gtk.Label(xalign=0)
        self.opacity.add_css_class("caption")
        self.opacity.add_css_class("dim-label")
        self.opacity.add_css_class("numeric")
        text.append(self.opacity)
        box.append(text)
        self.set_child(box)

        # A double click renames the layer.
        click = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        click.connect("pressed", self._on_pressed)
        self.add_controller(click)

        # Dragged onto another row, the layer moves to its place.
        source = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        source.connect("prepare", self._on_drag_prepare)
        source.connect("drag-begin", self._on_drag_begin)
        self.add_controller(source)
        target = Gtk.DropTarget.new(LayerDrag.__gtype__, Gdk.DragAction.MOVE)
        target.connect("enter", lambda *_args: self._highlight(True))
        target.connect("leave", lambda *_args: self._highlight(False))
        target.connect("drop", self._on_drop)
        self.add_controller(target)

        self._syncing = False
        self.sync()

    def sync(self) -> None:
        """Show the layer's name, visibility and opacity as they are now."""
        layer = self.layer
        self.name.set_label(layer.name)
        self._syncing = True
        self.eye.set_active(layer.visible)
        self._syncing = False
        self.eye.set_icon_name("view-reveal-symbolic" if layer.visible else "view-conceal-symbolic")
        tip = _("Hide layer") if layer.visible else _("Show layer")
        self.eye.set_tooltip_text(tip)
        self.eye.update_property([Gtk.AccessibleProperty.LABEL], [tip])
        percent = round(layer.opacity * 100)
        self.opacity.set_label(_("{percent}%").format(percent=percent))
        self.opacity.set_visible(percent < 100)
        if not layer.visible:
            description = _("{name}, hidden").format(name=layer.name)
        elif percent < 100:
            description = _("{name}, {percent}% opacity").format(name=layer.name, percent=percent)
        else:
            description = layer.name
        self.update_property([Gtk.AccessibleProperty.LABEL], [description])

    def _on_eye_toggled(self, button: Gtk.ToggleButton) -> None:
        if not self._syncing:
            self.panel.document.set_layer_visible(self.index, button.get_active())

    def _on_pressed(self, gesture, presses: int, x: float, y: float) -> None:
        if presses == 2:
            self.panel.select(self.index)
            self.activate_action("win.rename-layer", None)

    def _on_drag_prepare(self, source, x: float, y: float):
        return Gdk.ContentProvider.new_for_value(LayerDrag(self.index))

    def _on_drag_begin(self, source, drag) -> None:
        source.set_icon(Gtk.WidgetPaintable.new(self), 0, 0)

    def _highlight(self, on: bool) -> Gdk.DragAction:
        if on:
            self.add_css_class("tempera-drop-target")
        else:
            self.remove_css_class("tempera-drop-target")
        return Gdk.DragAction.MOVE

    def _on_drop(self, target, value: LayerDrag, x: float, y: float) -> bool:
        self._highlight(False)
        if value.index == self.index:
            return False
        self.activate_action("win.move-layer", GLib.Variant("(ii)", (value.index, self.index)))
        return True


class LayersPanel(Gtk.Box):
    """The layers of the picture, top first as they stack, with the current one
    selected, its opacity, and the buttons to arrange them."""

    def __init__(self, canvas: Canvas, add_tooltip: Callable[[Gtk.Widget, str, str], None]):
        # Not wider than asked for, whatever its rows and slider would take:
        # the room to spare is the canvas's.
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=False)
        self.add_css_class("tempera-layers-panel")
        self.canvas = canvas
        self.document: Document | None = None
        self._handlers: list[int] = []
        self._rows: list[LayerRow] = []
        # Each layer's thumbnail, with the surface it was made from.
        self._thumbnails: dict[Layer, tuple[cairo.ImageSurface, Gdk.Texture]] = {}
        self._thumbnail_timer = 0
        self._selecting = False

        heading = Gtk.Label(label=_("Layers"), xalign=0)
        heading.add_css_class("heading")
        heading.add_css_class("tempera-panel-heading")
        self.append(heading)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class("navigation-sidebar")
        self.list.update_property([Gtk.AccessibleProperty.LABEL], [_("Layers")])
        self.list.connect("row-selected", self._on_row_selected)
        scroller = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vexpand=True
        )
        scroller.set_child(self.list)
        self.append(scroller)

        # The current layer's opacity: its name and value above, the slider
        # the whole width of the panel beneath.
        opacity = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        opacity.add_css_class("tempera-layer-opacity")
        heading_row = Gtk.Box()
        caption = Gtk.Label(label=_("Opacity"), xalign=0, hexpand=True)
        caption.add_css_class("dim-label")
        heading_row.append(caption)
        self.opacity_value = Gtk.Label(xalign=1)
        self.opacity_value.add_css_class("numeric")
        heading_row.append(self.opacity_value)
        opacity.append(heading_row)
        self.opacity_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.opacity_scale.set_draw_value(False)
        self.opacity_scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Layer opacity")])
        self.opacity_scale.connect("value-changed", self._on_opacity_changed)
        opacity.append(self.opacity_scale)
        self.append(opacity)

        buttons = Gtk.Box(spacing=2, homogeneous=True)
        buttons.add_css_class("tempera-layer-buttons")
        for icon, text, action in (
            ("tempera-layer-add-symbolic", "New Layer", "win.add-layer"),
            ("tempera-layer-duplicate-symbolic", "Duplicate Layer", "win.duplicate-layer"),
            ("tempera-layer-up-symbolic", "Move Layer Up", "win.raise-layer"),
            ("tempera-layer-down-symbolic", "Move Layer Down", "win.lower-layer"),
            ("tempera-layer-delete-symbolic", "Delete Layer", "win.delete-layer"),
        ):
            button = Gtk.Button(icon_name=icon)
            button.add_css_class("flat")
            add_tooltip(button, text, action)
            button.set_action_name(action)
            buttons.append(button)
        more = Gio.Menu()
        more.append(_("Rename Layer…"), "win.rename-layer")
        more.append(_("Merge Down"), "win.merge-layer-down")
        more.append(_("Flatten Image"), "win.flatten-image")
        more_button = Gtk.MenuButton(icon_name="view-more-symbolic", menu_model=more)
        more_button.add_css_class("flat")
        more_button.set_tooltip_text(_("More layer actions"))
        more_button.update_property([Gtk.AccessibleProperty.LABEL], [_("More layer actions")])
        buttons.append(more_button)
        self.append(buttons)

        self.set_document(canvas.document)

    def set_document(self, document: Document) -> None:
        if self.document is not None:
            for handler in self._handlers:
                self.document.disconnect(handler)
        self.document = document
        self._thumbnails.clear()
        self._handlers = [
            document.connect("layers-changed", lambda *_args: self.sync()),
            document.connect("content-changed", self._on_content_changed),
        ]
        self.sync()

    def sync_interface_size(self) -> None:
        """Thumbnails the size the interface is drawn at now."""
        self._thumbnails.clear()
        for row in self._rows:
            row.thumbnail.queue_resize()
        self._schedule_thumbnails()

    def select(self, index: int) -> None:
        """Make a layer the current one, the way clicking its row does."""
        self.canvas.select_layer(index)

    # Keeping up with the document

    def sync(self) -> None:
        """Show the layers as they are now: rebuilt if they came, went or moved, updated if not."""
        document = self.document
        layers = list(reversed(document.layers))
        if [row.layer for row in self._rows] != layers:
            for row in self._rows:
                self.list.remove(row)
            count = len(document.layers)
            self._rows = [LayerRow(self, layer, count - 1 - position) for position, layer in enumerate(layers)]
            for row in self._rows:
                self.list.append(row)
            self._schedule_thumbnails()
        else:
            for row in self._rows:
                row.sync()
        self._selecting = True
        self.list.select_row(self._rows[len(self._rows) - 1 - document.current])
        self._selecting = False
        self._sync_opacity()

    def _sync_opacity(self) -> None:
        percent = round(self.document.layer.opacity * 100)
        self._selecting = True
        self.opacity_scale.set_value(percent)
        self._selecting = False
        self.opacity_value.set_label(_("{percent}%").format(percent=percent))

    def _on_row_selected(self, listbox, row: LayerRow | None) -> None:
        if self._selecting or row is None:
            return
        self.select(row.index)
        # Landing what floated may have changed nothing, or selecting may
        # have been refused: show whichever layer is current now.
        if self.document.current != row.index:
            self.sync()

    def _on_opacity_changed(self, scale: Gtk.Scale) -> None:
        if self._selecting:
            return
        percent = round(scale.get_value())
        self.opacity_value.set_label(_("{percent}%").format(percent=percent))
        self.document.set_layer_opacity(self.document.current, percent / 100)

    # Thumbnails

    def _on_content_changed(self, document: Document) -> None:
        damage = document.damage
        if damage is None:
            self._thumbnails.clear()
        else:
            for layer, _rect in damage:
                self._thumbnails.pop(layer, None)
        self._schedule_thumbnails()

    def _schedule_thumbnails(self) -> None:
        if self._thumbnail_timer == 0:
            self._thumbnail_timer = GLib.timeout_add(THUMBNAIL_DELAY_MS, self._refresh_thumbnails)

    def _refresh_thumbnails(self) -> bool:
        self._thumbnail_timer = 0
        width, height = scaled(THUMBNAIL_WIDTH), scaled(THUMBNAIL_HEIGHT)
        # Bigger on a high-resolution screen, to stay sharp there.
        scale = max(1, self.get_scale_factor())
        present = set()
        for row in self._rows:
            layer = row.layer
            present.add(layer)
            kept = self._thumbnails.get(layer)
            # A new surface, as a rotation gives every layer, is a change too.
            if kept is None or kept[0] is not layer.surface:
                layer.surface.flush()
                kept = (layer.surface, thumbnail(layer.surface, width * scale, height * scale))
                self._thumbnails[layer] = kept
            row.thumbnail.set_texture(kept[1])
        for layer in [layer for layer in self._thumbnails if layer not in present]:
            del self._thumbnails[layer]
        return GLib.SOURCE_REMOVE
