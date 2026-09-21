# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import cairo
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Graphene, Gtk

from .clipboard import surface_from_texture
from .color import ColorState
from .document import MAX_SIZE, Document
from .file_io import load_surface_async
from .i18n import _
from .interface_size import scaled
from .selection import Selection
from .text import DEFAULT_FONT, TextBox
from .tools import (
    AIRBRUSH_TOOL_ID,
    DEFAULT_DENSITY,
    DEFAULT_TOLERANCE,
    ERASER_TOOL_ID,
    FILL_TOOL_ID,
    SELECTION_TOOL_IDS,
    SHAPES_TOOL_ID,
    TEXT_TOOL_ID,
    Tool,
    ToolContext,
    create_tools,
    draw_marquee,
)
from .tools.base import draw_outline_marquee, rect_handles

CHECKER_SIZE = 8
# Below this zoom the image is shrunk, where smoothing reads better than dropped
# pixels; at or above it every image pixel shows as a crisp square.
SMOOTH_ZOOM_BELOW = 1.0
# The resize grips, at the default interface size; they grow with it.
HANDLE_SIZE = 10
HANDLE_GRAB = 12
# Room around the image so the grips sitting on its edge are fully visible.
HANDLE_MARGIN = 8
ZOOM_MIN = 0.1
# The pixel grid shows from this zoom up; below it the lines would crowd out
# the pixels they outline.
PIXEL_GRID_ZOOM = 4.0
ZOOM_MAX = 8.0
# What Ctrl+Plus/Minus step through, and Ctrl+scroll rounds towards.
ZOOM_PRESETS = [0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 8.0]
# Multiplier per scroll-wheel notch while zooming.
ZOOM_SCROLL_FACTOR = 1.1
# The canvas margin set in style.css. Zoom to Fit leaves it on both sides, plus
# the strip the resize grips need.
CANVAS_MARGIN = 24
# How near, in screen pixels at the default interface size, a click must land
# to hit a point already placed, such as a polygon's first corner.
POINT_REACH = 6
# Breathing room between the typed text and its dashed outline.
TEXT_PADDING = 3
CARET_BLINK_MS = 530
# How far the pointer has to travel before a click inside a text box counts
# as dragging it somewhere else rather than placing the caret.
MOVE_THRESHOLD = 4
CUT_OFF_MESSAGE = _("Part of the image was cut off: a canvas can be at most {size} × {size} px").format(
    size=MAX_SIZE
)
# Arrow-key nudge for a selection or floating paste, in image pixels; Shift steps further.
NUDGE_STEP = 1
NUDGE_STEP_FAST = 10

HANDLE_CURSORS = {
    "e": "ew-resize",
    "w": "ew-resize",
    "n": "ns-resize",
    "s": "ns-resize",
    "ne": "nesw-resize",
    "sw": "nesw-resize",
    "nw": "nwse-resize",
    "se": "nwse-resize",
    "paste": "move",
    "text": "text",
    "selection": "move",
}


@dataclass
class FloatingPaste:
    """Pasted pixels hovering over the canvas until they are stamped down."""

    surface: cairo.ImageSurface
    x: float = 0.0
    y: float = 0.0
    # Where a lifted selection came from, painted over when the move lands so
    # that vacating the old place and filling the new one is one undo step.
    source: tuple[int, int, int, int] | None = None
    # For a hand-drawn selection, which pixels of that rectangle it took.
    source_mask: cairo.ImageSurface | None = None
    # A resize handle stretches the pixels rather than the surface itself, so
    # committing can resample once instead of every frame of the drag.
    scale_x: float = 1.0
    scale_y: float = 1.0

    @property
    def width(self) -> int:
        return round(self.surface.get_width() * self.scale_x)

    @property
    def height(self) -> int:
        return round(self.surface.get_height() * self.scale_y)

    def move_to(self, x: float, y: float) -> None:
        # Never past the top-left: the canvas only ever grows right and down, so
        # the image keeps the same anchor a resize would give it.
        self.x = max(0.0, x)
        self.y = max(0.0, y)

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height

    def rendered(self) -> cairo.ImageSurface:
        """The surface at its current on-canvas size, resampled if it was scaled."""
        if self.scale_x == 1.0 and self.scale_y == 1.0:
            return self.surface
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, self.width), max(1, self.height))
        cr = cairo.Context(surface)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.scale(self.scale_x, self.scale_y)
        cr.set_source_surface(self.surface, 0, 0)
        # Crisp pixels rather than a blurred blend — matches a stretched
        # selection in Paint, and keeps hard edges hard at any scale.
        cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()
        return surface


@cache
def _checker_pattern() -> cairo.SurfacePattern:
    """One 2 × 2 tile of the checkerboard, repeated by cairo.

    Drawing each square as its own rectangle came to half a million of them per
    frame on the largest canvas.
    """
    size = CHECKER_SIZE * 2
    tile = cairo.ImageSurface(cairo.FORMAT_RGB24, size, size)
    cr = cairo.Context(tile)
    cr.set_source_rgb(1, 1, 1)
    cr.paint()
    cr.set_source_rgb(0.9, 0.9, 0.9)
    cr.rectangle(CHECKER_SIZE, 0, CHECKER_SIZE, CHECKER_SIZE)
    cr.rectangle(0, CHECKER_SIZE, CHECKER_SIZE, CHECKER_SIZE)
    cr.fill()
    pattern = cairo.SurfacePattern(tile)
    pattern.set_extend(cairo.EXTEND_REPEAT)
    pattern.set_filter(cairo.FILTER_NEAREST)
    return pattern


def fit_zoom(image: tuple[int, int], viewport: tuple[int, int]) -> float:
    """The zoom at which an image just fits in the room available."""
    return min(viewport[0] / image[0], viewport[1] / image[1])


class Canvas(Gtk.DrawingArea):
    """Displays the document and routes pointer input to the active tool."""

    __gsignals__ = {
        "color-picked": (GObject.SignalFlags.RUN_FIRST, None, (Gdk.RGBA, int)),
        "resize-preview": (GObject.SignalFlags.RUN_FIRST, None, (int, int)),
        # A paste or a text box appeared, moved, changed or landed.
        "floating-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # A selection was made, moved out of, or dropped.
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "zoom-changed": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
        # The pointer moved over (or left) the canvas, in image-pixel coordinates.
        "pointer-moved": (GObject.SignalFlags.RUN_FIRST, None, (float, float)),
        "pointer-left": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # Something worth telling the user, such as a drop that could not be read.
        "message": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, document: Document, colors: ColorState):
        # An image to assistive technology: it holds a picture, and its label
        # says how big that picture is.
        super().__init__(accessible_role=Gtk.AccessibleRole.IMG)
        self.colors = colors
        self.tools = create_tools()
        self.active_tool: Tool = self.tools["pencil"]
        # A shape waiting to land is drawn afresh every frame, so a colour
        # picked now shows on it rather than only on the next shape.
        colors.connect("changed", lambda *_args: self._restyle_shape())
        self._brush_size = 4
        self._fill_shapes = False
        self.erase_to_transparency = False
        self.fill_tolerance = DEFAULT_TOLERANCE
        self.airbrush_density = DEFAULT_DENSITY
        self._show_pixel_grid = False
        self.font = DEFAULT_FONT
        self.zoom = 1.0

        self._document: Document | None = None
        self._document_handler = 0
        self._drag_origin: tuple[float, float] | None = None
        self._drag_context: ToolContext | None = None
        # The button that started a shape still waiting for more clicks; its
        # colours carry through every click until the shape lands.
        self._shape_button = Gdk.BUTTON_PRIMARY
        # The timer that keeps the airbrush spraying while it is held still.
        self._repeat_source = 0
        self._resize_handle: str | None = None
        # A grip on a pending shape, or the shape itself, is being dragged.
        self._shape_adjusting = False
        self._pan_origin: tuple[float, float] | None = None
        self._pinch_zoom = 1.0
        self._resize_size: tuple[int, int] | None = None
        self._paste: FloatingPaste | None = None
        self._paste_origin: tuple[float, float] | None = None
        self._paste_resize_handle: str | None = None
        self._paste_resize_origin: tuple[float, float, float, float] | None = None
        self._text: TextBox | None = None
        self._text_origin: tuple[float, float] | None = None
        self._text_moved = False
        self._selection: Selection | None = None
        self._caret_visible = True
        self._blink_source = 0
        # Raw widget-space pointer position, for Ctrl+scroll to zoom around.
        self._last_pointer: tuple[float, float] = (0.0, 0.0)

        # Anchored top-left like the image itself; CanvasFrame does the centering.
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.START)
        self.set_draw_func(self._draw)
        self.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        self.add_css_class("tempera-canvas")

        drag = Gtk.GestureDrag(button=0)
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        # Lets CanvasFrame re-centre an image that a drag resized.
        drag.connect_after("drag-end", lambda *_args: self.queue_resize())
        self.add_controller(drag)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        motion.connect("leave", self._on_leave)
        self.add_controller(motion)

        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self._on_scroll)
        self.add_controller(scroll)

        # Keys only mean something while something is floating over the canvas,
        # so it takes focus for the duration rather than claiming accelerators.
        self.set_focusable(True)
        self._keys = Gtk.EventControllerKey()
        self._keys.connect("key-pressed", self._on_key_pressed)
        self.add_controller(self._keys)

        # Attached to the key controller only while typing, since an input method
        # swallows every printable key it is offered — including the single-letter
        # tool shortcuts.
        self._im = Gtk.IMMulticontext()
        self._im.set_client_widget(self)
        self._im.connect("commit", self._on_im_commit)
        self._im.connect("preedit-changed", self._on_im_preedit_changed)

        drop = Gtk.DropTarget.new(Gdk.Texture, Gdk.DragAction.COPY)
        drop.set_gtypes([Gdk.Texture, Gdk.FileList, Gio.File])
        drop.connect("drop", self._on_drop)
        self.add_controller(drop)

        self.document = document

    @property
    def document(self) -> Document:
        return self._document

    @document.setter
    def document(self, value: Document) -> None:
        if self._document is not None and self._document_handler:
            self._document.disconnect(self._document_handler)
        # A selection or a paste belongs to the image it was made on, and
        # would land outside a smaller one.
        self.cancel_floating()
        self.set_selection(None)
        self._document = value
        self._document_handler = value.connect("content-changed", self._on_content_changed)
        self._sync_content_size()
        self.queue_draw()

    def _on_content_changed(self, *_args) -> None:
        # Undo/redo and resizing can swap in a differently sized surface.
        if self._selection is not None:
            document = self._document
            self.set_selection(self._selection.clamped(document.width, document.height))
        self._sync_content_size()
        self.queue_draw()

    def _sync_content_size(self) -> None:
        width, height = self._document.width, self._document.height
        if self._resize_size is not None:
            # Follow the drag so the pending outline stays inside the widget.
            width = max(width, self._resize_size[0])
            height = max(height, self._resize_size[1])
        bounds = self._floating_bounds()
        if bounds is not None:
            # A screenshot hanging off the edge stays visible before it lands.
            float_x, float_y, float_width, float_height = bounds
            width = max(width, round(float_x) + float_width)
            height = max(height, round(float_y) + float_height)
        # The margin scales with zoom too, so it stays big enough to fit the
        # (also zoomed) resize handles without clipping them at the edge.
        margin = round(scaled(HANDLE_MARGIN) * self.zoom)
        self.set_content_width(round(width * self.zoom) + margin)
        self.set_content_height(round(height * self.zoom) + margin)
        self.update_property(
            [Gtk.AccessibleProperty.LABEL],
            [
                _("Drawing canvas, {width} × {height} pixels").format(
                    width=self._document.width, height=self._document.height
                )
            ],
        )

    def sync_interface_size(self) -> None:
        """Redraw the grips, and the room kept for them, at the interface size now chosen."""
        self._sync_content_size()
        self.queue_draw()

    @property
    def is_dragging(self) -> bool:
        """Whether a button is held down: a stroke, move or resize is under way."""
        return self._drag_origin is not None

    def select_tool(self, tool_id: str) -> None:
        self.finish_shape()
        self.active_tool = self.tools[tool_id]
        # A selection outlives the tool that made it: Cut, Copy and Delete keep
        # working on it, and going back to the select tool picks it up again.

    @property
    def shapes(self):
        return self.tools[SHAPES_TOOL_ID]

    def select_shape(self, shape_id: str) -> None:
        """Pick the shape the Shapes tool draws, landing one still being placed."""
        self.finish_shape()
        self.shapes.select(shape_id)

    @property
    def supports_fill(self) -> bool:
        return self.active_tool.id == SHAPES_TOOL_ID

    @property
    def supports_font(self) -> bool:
        return self.active_tool.id == TEXT_TOOL_ID

    @property
    def supports_erase_mode(self) -> bool:
        return self.active_tool.id == ERASER_TOOL_ID

    @property
    def supports_density(self) -> bool:
        return self.active_tool.id == AIRBRUSH_TOOL_ID

    @property
    def brush_size(self) -> int:
        return self._brush_size

    @brush_size.setter
    def brush_size(self, value: int) -> None:
        self._brush_size = value
        self._restyle_shape()

    @property
    def fill_shapes(self) -> bool:
        return self._fill_shapes

    @fill_shapes.setter
    def fill_shapes(self, value: bool) -> None:
        self._fill_shapes = value
        self._restyle_shape()

    def _restyle_shape(self) -> None:
        """Show a change of colour, size or fill on a shape that has not landed yet."""
        if self.active_tool.in_progress:
            self.queue_draw()

    @property
    def show_pixel_grid(self) -> bool:
        return self._show_pixel_grid

    @show_pixel_grid.setter
    def show_pixel_grid(self, value: bool) -> None:
        self._show_pixel_grid = value
        self.queue_draw()

    @property
    def pixel_grid_visible(self) -> bool:
        """Whether the grid is on and zoomed in far enough to be drawn."""
        return self._show_pixel_grid and self.zoom >= PIXEL_GRID_ZOOM

    @property
    def supports_tolerance(self) -> bool:
        return self.active_tool.id == FILL_TOOL_ID

    def set_font(self, font: str) -> None:
        self.font = font
        if self._text is not None:
            self._text.font = font
            # The font button stole the focus on its way here.
            self.grab_focus()
            self._refresh_text()

    # Zoom

    def _to_image(self, x: float, y: float) -> tuple[float, float]:
        """Widget-space pointer coordinates, converted to image pixels."""
        return x / self.zoom, y / self.zoom

    def set_zoom(self, zoom: float, anchor: tuple[float, float] | None = None) -> None:
        """Change the zoom level, optionally keeping a widget-space point fixed.

        `anchor` is the point on screen (e.g. the pointer) that should still be
        over the same image pixel once the zoom changes.
        """
        zoom = max(ZOOM_MIN, min(zoom, ZOOM_MAX))
        if zoom == self.zoom:
            return
        old_zoom = self.zoom
        self.zoom = zoom
        self._sync_content_size()
        self.queue_draw()
        self.emit("zoom-changed", zoom)
        if anchor is not None:
            self._preserve_anchor(anchor, old_zoom, zoom)

    def _preserve_anchor(
        self, anchor: tuple[float, float], old_zoom: float, new_zoom: float
    ) -> None:
        scrolled = self.get_ancestor(Gtk.ScrolledWindow)
        if scrolled is None:
            return
        image_x, image_y = anchor[0] / old_zoom, anchor[1] / old_zoom
        horizontal, vertical = scrolled.get_hadjustment(), scrolled.get_vadjustment()
        # Captured now, before the resize below reaches the adjustments: once
        # their bounds shrink (zooming out), GTK clamps .value on its own as
        # part of that same update, so reading .value fresh from inside the
        # tick callback would nudge from the already-clamped position instead
        # of the one the pointer was actually anchored to.
        base_value = (horizontal.get_value(), vertical.get_value())
        # Centring moves the canvas as it grows or shrinks, and the scroll has to
        # absorb that too.
        base_offset = self._frame_offset()
        stale_bounds = (horizontal.get_upper(), vertical.get_upper())
        attempts = 0

        def adjust(widget, frame_clock) -> bool:
            nonlocal attempts
            attempts += 1
            settled = (horizontal.get_upper(), vertical.get_upper()) != stale_bounds
            if not settled and attempts < 10:
                return GLib.SOURCE_CONTINUE
            offset = self._frame_offset()
            horizontal.set_value(
                base_value[0] + offset[0] - base_offset[0] + image_x * (new_zoom - old_zoom)
            )
            vertical.set_value(
                base_value[1] + offset[1] - base_offset[1] + image_y * (new_zoom - old_zoom)
            )
            return GLib.SOURCE_REMOVE

        self.add_tick_callback(adjust)

    def _frame_offset(self) -> tuple[int, int]:
        parent = self.get_parent()
        return parent.offset if isinstance(parent, CanvasFrame) else (0, 0)

    def zoom_in(self) -> None:
        bigger = [level for level in ZOOM_PRESETS if level > self.zoom + 1e-9]
        self.set_zoom(bigger[0] if bigger else ZOOM_MAX)

    def zoom_out(self) -> None:
        smaller = [level for level in ZOOM_PRESETS if level < self.zoom - 1e-9]
        self.set_zoom(smaller[-1] if smaller else ZOOM_MIN)

    def reset_zoom(self) -> None:
        self.set_zoom(1.0)

    def _viewport_size(self) -> tuple[int, int]:
        scrolled = self.get_ancestor(Gtk.ScrolledWindow)
        if scrolled is None:
            return (0, 0)
        padding = 2 * CANVAS_MARGIN + scaled(HANDLE_MARGIN)
        return (scrolled.get_width() - padding, scrolled.get_height() - padding)

    def zoom_to_fit(self) -> bool:
        """Zoom so the whole image is in view. False while the window has no size yet."""
        width, height = self._viewport_size()
        if width <= 0 or height <= 0:
            return False
        self.set_zoom(fit_zoom((self._document.width, self._document.height), (width, height)))
        return True

    def fit_if_too_large(self) -> None:
        """Open a photo bigger than the window zoomed out, rather than showing a corner of it.

        Called as a document arrives, which may be before the window has been
        given its size; then it waits for the first frame that has one.
        """
        def fit(*_args) -> bool:
            width, height = self._viewport_size()
            if width <= 0 or height <= 0:
                return GLib.SOURCE_CONTINUE
            if self._document.width > width or self._document.height > height:
                self.zoom_to_fit()
            else:
                self.reset_zoom()
            return GLib.SOURCE_REMOVE

        if fit() is GLib.SOURCE_CONTINUE:
            self.add_tick_callback(fit)

    # Panning and pinching, on the scrolling area around the canvas

    def attach_to_viewport(self, scrolled: Gtk.ScrolledWindow) -> None:
        """Take middle-drag and pinch gestures from the area the canvas scrolls in.

        They belong there rather than on the canvas itself, which moves under
        the pointer as it scrolls, and whose own drag gesture is for drawing.
        """
        pan = Gtk.GestureDrag(
            button=Gdk.BUTTON_MIDDLE, propagation_phase=Gtk.PropagationPhase.CAPTURE
        )
        pan.connect("drag-begin", self._on_pan_begin)
        pan.connect("drag-update", self._on_pan_update)
        pan.connect("drag-end", self._on_pan_end)
        scrolled.add_controller(pan)

        pinch = Gtk.GestureZoom()
        pinch.connect("begin", self._on_pinch_begin)
        pinch.connect("scale-changed", self._on_pinch_changed)
        scrolled.add_controller(pinch)
        self._pinch_zoom = 1.0

    def _adjustments(self) -> tuple[Gtk.Adjustment, Gtk.Adjustment] | None:
        scrolled = self.get_ancestor(Gtk.ScrolledWindow)
        if scrolled is None:
            return None
        return scrolled.get_hadjustment(), scrolled.get_vadjustment()

    def _on_pan_begin(self, gesture, start_x, start_y) -> None:
        adjustments = self._adjustments()
        if adjustments is None:
            return
        self._pan_origin = tuple(adjustment.get_value() for adjustment in adjustments)
        self.set_cursor(Gdk.Cursor.new_from_name("grabbing"))

    def _on_pan_update(self, gesture, offset_x, offset_y) -> None:
        adjustments = self._adjustments()
        if adjustments is None or self._pan_origin is None:
            return
        # Drag the image with the pointer: the view goes the other way.
        for adjustment, origin, offset in zip(adjustments, self._pan_origin, (offset_x, offset_y)):
            adjustment.set_value(origin - offset)

    def _on_pan_end(self, gesture, offset_x, offset_y) -> None:
        self._pan_origin = None
        self._set_cursor(None)

    def _on_pinch_begin(self, gesture, sequence) -> None:
        self._pinch_zoom = self.zoom

    def _on_pinch_changed(self, gesture, scale: float) -> None:
        found, center = gesture.get_bounding_box_center()
        anchor = None
        if found:
            scrolled = self.get_ancestor(Gtk.ScrolledWindow)
            point = Graphene.Point()
            point.init(center.x, center.y)
            ok, here = scrolled.compute_point(self, point)
            if ok:
                anchor = (here.x, here.y)
        self.set_zoom(self._pinch_zoom * scale, anchor=anchor)

    def _on_scroll(self, controller, dx: float, dy: float) -> bool:
        if not controller.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK:
            return Gdk.EVENT_PROPAGATE
        self.set_zoom(self.zoom * ZOOM_SCROLL_FACTOR ** -dy, anchor=self._last_pointer)
        return Gdk.EVENT_STOP

    # Selection

    @property
    def selecting(self) -> bool:
        """Whether a selection tool is the one holding the pointer."""
        return self.active_tool.id in SELECTION_TOOL_IDS

    @property
    def has_selection(self) -> bool:
        return self._selection is not None

    @property
    def selection_size(self) -> tuple[int, int] | None:
        """How big the selection is, for the readout in the bottom bar."""
        if self._selection is None:
            return None
        return self._selection.width, self._selection.height

    def set_selection(self, selection: Selection | None) -> None:
        if selection == self._selection:
            return
        self._selection = selection
        self.queue_draw()
        self.emit("selection-changed")

    def select_region(self, x: float, y: float, width: float, height: float) -> None:
        """Take the rectangle the select tool just dragged out."""
        self.set_selection(
            Selection.from_rect(x, y, width, height, self._document.width, self._document.height)
        )
        if self._selection is not None:
            # Esc and Delete belong to the selection from here on.
            self.grab_focus()

    def select_outline(self, outline: list[tuple[float, float]]) -> None:
        """Take the outline the lasso just drew."""
        self.set_selection(
            Selection.from_outline(outline, self._document.width, self._document.height)
        )
        if self._selection is not None:
            self.grab_focus()

    def select_all(self) -> None:
        self.commit_floating()
        self.select_region(0, 0, self._document.width, self._document.height)

    def _selection_at(self, x: float, y: float) -> "Selection | None":
        """The selection under a point, when the select tool is there to grab it."""
        if not self.selecting or self._selection is None:
            return None
        return self._selection if self._selection.contains(x, y) else None

    def clear_selection(self) -> bool:
        if self._selection is None:
            return False
        self.set_selection(None)
        return True

    def selection_surface(self) -> cairo.ImageSurface | None:
        """A copy of the selected pixels, for the clipboard."""
        if self._selection is None:
            return None
        return self._selection.pixels(self._document.surface)

    def delete_selection(self) -> bool:
        if self._selection is None:
            return False
        self._document.erase(self._selection.rect, mask=self._selection.mask)
        self.set_selection(None)
        return True

    def crop_to_selection(self) -> bool:
        if self._selection is None:
            return False
        self._document.crop_to(*self._selection.rect, mask=self._selection.mask)
        self.set_selection(None)
        return True

    def _lift_selection(self, copy: bool) -> None:
        """Float the selected pixels so the drag can carry them somewhere else."""
        selection = self._selection
        surface = selection.pixels(self._document.surface)
        self.set_selection(None)
        self.begin_paste(
            surface,
            selection.x,
            selection.y,
            source=None if copy else selection.rect,
            source_mask=None if copy else selection.mask,
        )

    @staticmethod
    def _nudge_delta(keyval: int, state: Gdk.ModifierType) -> tuple[float, float] | None:
        step = NUDGE_STEP_FAST if state & Gdk.ModifierType.SHIFT_MASK else NUDGE_STEP
        if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
            return (-step, 0)
        if keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
            return (step, 0)
        if keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            return (0, -step)
        if keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            return (0, step)
        return None

    def _nudge_paste(self, delta: tuple[float, float]) -> None:
        self._paste.move_to(self._paste.x + delta[0], self._paste.y + delta[1])
        self._sync_content_size()
        self.queue_draw()
        self.emit("floating-changed")

    # Floating paste and text

    @property
    def has_floating(self) -> bool:
        return self._paste is not None or self._text is not None

    @property
    def is_typing(self) -> bool:
        return self._text is not None

    @property
    def has_pending_floating(self) -> bool:
        """Whether landing what floats would change the image: a paste, text with something typed, or a shape."""
        return (
            self._paste is not None
            or (self._text is not None and bool(self._text.text))
            or self.shape_in_progress
        )

    def _floating_bounds(self) -> tuple[float, float, int, int] | None:
        """Where the pending paste or text sits, or None when nothing floats."""
        if self._paste is not None:
            return self._paste.x, self._paste.y, self._paste.width, self._paste.height
        if self._text is not None:
            width, height = self._text.size
            if width > 0 and height > 0:
                return self._text.x, self._text.y, width, height
        return None

    @property
    def pending_size(self) -> tuple[int, int]:
        """The canvas size a commit would leave behind, for the size readout."""
        width, height = self._document.width, self._document.height
        bounds = self._floating_bounds()
        if bounds is None:
            return width, height
        float_x, float_y, float_width, float_height = bounds
        return (
            min(max(width, round(float_x) + float_width), MAX_SIZE),
            min(max(height, round(float_y) + float_height), MAX_SIZE),
        )

    def commit_floating(self) -> bool:
        """Land whatever hovers over the canvas — only ever one thing does."""
        return self.finish_shape() or self.commit_text() or self.commit_paste()

    def cancel_floating(self) -> bool:
        return self.cancel_shape() or self.cancel_text() or self.cancel_paste()

    # Shapes placed over several clicks

    @property
    def shape_in_progress(self) -> bool:
        return self.active_tool.in_progress

    def finish_shape(self) -> bool:
        """Draw a polygon or curve still being placed into the image, as one step to undo."""
        if not self.active_tool.in_progress or self.is_dragging:
            return False
        self._document.begin_change()
        self.active_tool.finish(self._make_context(self._shape_button))
        self._document.finish_change()
        self.queue_draw()
        self.emit("floating-changed")
        return True

    def cancel_shape(self) -> bool:
        if not self.active_tool.in_progress or self.is_dragging:
            return False
        self.active_tool.cancel()
        self.queue_draw()
        self.emit("floating-changed")
        return True

    def begin_paste(
        self,
        surface: cairo.ImageSurface,
        x: float = 0,
        y: float = 0,
        source: tuple[int, int, int, int] | None = None,
        source_mask: cairo.ImageSurface | None = None,
    ) -> None:
        """Float an image over the canvas until it is committed or discarded."""
        self.commit_floating()
        # Whatever was selected is not what is about to hover over the canvas.
        self.set_selection(None)
        self._paste = FloatingPaste(surface, source=source, source_mask=source_mask)
        self._paste.move_to(x, y)
        self.grab_focus()
        self._sync_content_size()
        self.queue_draw()
        self.emit("floating-changed")

    def commit_paste(self) -> bool:
        """Stamp the floating image into the document, growing the canvas to fit."""
        if self._paste is None:
            return False
        paste, self._paste = self._paste, None
        cut_off = self._document.paste(
            paste.rendered(),
            round(paste.x),
            round(paste.y),
            erase=paste.source,
            erase_mask=paste.source_mask,
        )
        if cut_off:
            self.emit("message", CUT_OFF_MESSAGE)
        self._sync_content_size()
        self.queue_draw()
        self.emit("floating-changed")
        return True

    def cancel_paste(self) -> bool:
        if self._paste is None:
            return False
        self._paste = None
        self._sync_content_size()
        self.queue_draw()
        self.emit("floating-changed")
        return True

    def begin_text(self, x: float, y: float, color: Gdk.RGBA) -> None:
        """Start a text box at a point on the canvas and take keyboard input."""
        self.commit_floating()
        self._text = TextBox(x, y, color, self.font)
        self.grab_focus()
        self._keys.set_im_context(self._im)
        self._im.focus_in()
        self._start_blink()
        self._sync_content_size()
        self.queue_draw()
        self.emit("floating-changed")

    def commit_text(self) -> bool:
        """Rasterise the typed text into the image, growing the canvas to fit."""
        if self._text is None:
            return False
        text, self._text = self._text, None
        # Only what the input method has committed lands; a half-composed
        # word does not.
        surface = text.render_surface()
        if surface is not None and self._document.paste(surface, round(text.x), round(text.y)):
            self.emit("message", CUT_OFF_MESSAGE)
        self._end_typing()
        return True

    def cancel_text(self) -> bool:
        if self._text is None:
            return False
        self._text = None
        self._end_typing()
        return True

    def _end_typing(self) -> None:
        self._text_origin = None
        self._text_moved = False
        self._stop_blink()
        self._im.focus_out()
        self._im.reset()
        self._keys.set_im_context(None)
        self._sync_content_size()
        self.queue_draw()
        self.emit("floating-changed")

    def _refresh_text(self) -> None:
        # A solid caret reads better than one caught mid-blink while the box is
        # being worked on.
        self._caret_visible = True
        self._sync_content_size()
        self.queue_draw()
        self.emit("floating-changed")

    def _start_blink(self) -> None:
        self._caret_visible = True
        if self._blink_source == 0:
            self._blink_source = GLib.timeout_add(CARET_BLINK_MS, self._blink)

    def _blink(self) -> bool:
        if self._text is None:
            self._blink_source = 0
            return GLib.SOURCE_REMOVE
        self._caret_visible = not self._caret_visible
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _stop_blink(self) -> None:
        if self._blink_source:
            GLib.source_remove(self._blink_source)
            self._blink_source = 0

    def _on_im_commit(self, im, text: str) -> None:
        if self._text is None:
            return
        self._text.insert(text)
        self._refresh_text()

    def _on_im_preedit_changed(self, im) -> None:
        """Show what an input method is still composing, such as Japanese before it is converted."""
        if self._text is None:
            return
        preedit, _attributes, cursor = im.get_preedit_string()
        self._text.set_preedit(preedit, cursor)
        self._refresh_text()

    def _on_key_pressed(self, controller, keyval, keycode, state) -> bool:
        if self._text is not None:
            return self._on_text_key(keyval, state)
        if self.active_tool.in_progress:
            if keyval == Gdk.KEY_Escape:
                return self.cancel_shape()
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter):
                return self.finish_shape()
            delta = self._nudge_delta(keyval, state)
            if delta is not None and self.active_tool.adjustable:
                self.active_tool.move_by(*delta)
                self.queue_draw()
                return True
            return False
        if self._paste is not None:
            if keyval == Gdk.KEY_Escape:
                return self.cancel_paste()
            if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                return self.commit_paste()
            delta = self._nudge_delta(keyval, state)
            if delta is not None:
                self._nudge_paste(delta)
                return True
            return False
        if self._selection is not None:
            if keyval == Gdk.KEY_Escape:
                return self.clear_selection()
            if keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete, Gdk.KEY_BackSpace):
                return self.delete_selection()
            delta = self._nudge_delta(keyval, state)
            if delta is not None:
                # The first nudge lifts it, same as dragging it would.
                self._lift_selection(False)
                self._nudge_paste(delta)
                return True
        return False

    def _on_text_key(self, keyval: int, state: Gdk.ModifierType) -> bool:
        """The editing keys; typed characters arrive through the input method."""
        text = self._text
        if keyval == Gdk.KEY_Escape:
            return self.cancel_text()
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter):
            # Return is a new line inside a text box, so landing it takes Ctrl.
            if state & Gdk.ModifierType.CONTROL_MASK:
                return self.commit_text()
            text.insert("\n")
        elif keyval == Gdk.KEY_BackSpace:
            text.backspace()
        elif keyval == Gdk.KEY_Delete:
            text.delete()
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
            text.move_caret(-1)
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
            text.move_caret(1)
        elif keyval in (Gdk.KEY_Up, Gdk.KEY_KP_Up):
            text.move_caret_line(-1)
        elif keyval in (Gdk.KEY_Down, Gdk.KEY_KP_Down):
            text.move_caret_line(1)
        elif keyval in (Gdk.KEY_Home, Gdk.KEY_KP_Home):
            text.move_caret_to_edge(False)
        elif keyval in (Gdk.KEY_End, Gdk.KEY_KP_End):
            text.move_caret_to_edge(True)
        else:
            # Ctrl+Z, Ctrl+S and the rest still belong to the window.
            return False
        self._refresh_text()
        return True

    def _on_drop(self, target, value, x: float, y: float) -> bool:
        x, y = self._to_image(x, y)
        if isinstance(value, Gdk.FileList):
            files = value.get_files()
            value = files[0] if files else None

        def paste_centred(surface: cairo.ImageSurface) -> None:
            # Drop where the pointer let go, centred on the pasted image.
            self.begin_paste(surface, x - surface.get_width() / 2, y - surface.get_height() / 2)

        if isinstance(value, Gdk.Texture):
            try:
                paste_centred(surface_from_texture(value))
            except GLib.Error as error:
                self.emit("message", error.message)
                return False
            return True
        if isinstance(value, Gio.File):
            # Read in the background: a dropped file can be large or on a slow disk.
            load_surface_async(value, paste_centred, lambda message: self.emit("message", message))
            return True
        return False

    # Resize grips

    def _handles(self) -> dict[str, tuple[float, float]]:
        if self._paste is not None:
            # Scales the pasted pixels rather than the canvas.
            return rect_handles(self._paste.x, self._paste.y, self._paste.width, self._paste.height)
        if self.active_tool.adjustable:
            # A shape that has been drawn but not landed: its own grips reshape it.
            return self.active_tool.handles()
        if self.has_floating or self.active_tool.in_progress:
            # A text box owns the pointer until it lands, and a shape being
            # placed takes every click, even on the edge of the image.
            return {}
        if self.selecting and self._selection is not None:
            # Scales the selected pixels in place.
            return rect_handles(*self._selection.rect)
        width, height = self._resize_size or (self._document.width, self._document.height)
        return {
            "e": (width, height / 2),
            "s": (width / 2, height),
            "se": (width, height),
        }

    def _paste_resized(self, x: float, y: float) -> tuple[float, float, float, float]:
        """New (x, y, width, height) for the floating paste, dragging one handle."""
        ox, oy, ow, oh = self._paste_resize_origin
        handle = self._paste_resize_handle
        left, right = ox, ox + ow
        top, bottom = oy, oy + oh
        if "w" in handle:
            left = max(0.0, min(x, right - 1))
        elif "e" in handle:
            right = min(max(x, left + 1), left + MAX_SIZE)
        if "n" in handle:
            top = max(0.0, min(y, bottom - 1))
        elif "s" in handle:
            bottom = min(max(y, top + 1), top + MAX_SIZE)
        return left, top, right - left, bottom - top

    def _resize_paste(self, x: float, y: float) -> None:
        left, top, width, height = self._paste_resized(x, y)
        self._paste.x, self._paste.y = left, top
        self._paste.scale_x = width / self._paste.surface.get_width()
        self._paste.scale_y = height / self._paste.surface.get_height()
        self._sync_content_size()
        self.queue_draw()
        self.emit("floating-changed")

    def _shape_reach(self) -> float:
        """How near a pending shape a press has to land to take hold of it."""
        return scaled(POINT_REACH) / self.zoom + self._brush_size / 2

    def _handle_box(self) -> tuple[float, float, float, float]:
        """The rectangle the handles belong to: a paste, a shape, a selection, or the image."""
        if self._paste is not None:
            return self._paste.x, self._paste.y, self._paste.width, self._paste.height
        bounds = self.active_tool.bounds() if self.active_tool.adjustable else None
        if bounds is not None:
            return bounds
        if self.selecting and self._selection is not None:
            return self._selection.rect
        return 0, 0, self._document.width, self._document.height

    def _handle_at(self, x: float, y: float) -> str | None:
        """The closest handle within reach, since a small selection or paste
        packs all 8 into less room than the grab tolerance around each one."""
        best: str | None = None
        best_distance = None
        box_x, box_y, box_width, box_height = self._handle_box()
        if box_x < x < box_x + box_width and box_y < y < box_y + box_height:
            # From inside, only the grip as drawn: the rest of a small selection
            # or paste is for dragging it somewhere else, and of the image for painting.
            grab = scaled(HANDLE_SIZE) / 2
        else:
            grab = scaled(HANDLE_GRAB)
        for name, (hx, hy) in self._handles().items():
            if abs(x - hx) <= grab and abs(y - hy) <= grab:
                distance = (x - hx) ** 2 + (y - hy) ** 2
                if best_distance is None or distance < best_distance:
                    best, best_distance = name, distance
        return best

    def _set_cursor(self, handle: str | None) -> None:
        if handle is not None and handle not in HANDLE_CURSORS:
            # A grip on one of a shape's own points, which goes anywhere.
            name = "move"
        else:
            name = HANDLE_CURSORS.get(handle, "crosshair")
        self.set_cursor(Gdk.Cursor.new_from_name(name))

    def _on_motion(self, controller, x, y) -> None:
        self._last_pointer = (x, y)
        x, y = self._to_image(x, y)
        self.emit("pointer-moved", x, y)
        if self._drag_origin is not None:
            return
        if self.active_tool.in_progress:
            # The side or bend still to come follows the pointer.
            self.active_tool.hover(x, y)
            self.queue_draw()
        handle = self._handle_at(x, y)
        if handle is not None:
            self._set_cursor(handle)
            return
        if self._paste is not None and self._paste.contains(x, y):
            self._set_cursor("paste")
            return
        if self.active_tool.adjustable and self.active_tool.contains(x, y, self._shape_reach()):
            self._set_cursor("selection")
            return
        if self._text is not None and self._text.contains(x, y, TEXT_PADDING):
            self._set_cursor("text")
            return
        if self._selection_at(x, y) is not None:
            self._set_cursor("selection")
            return
        self._set_cursor(None)

    def _on_leave(self, *_args) -> None:
        self._set_cursor(None)
        self.emit("pointer-left")

    def _resized_to(self, x: float, y: float) -> tuple[int, int]:
        width, height = self._document.width, self._document.height
        if self._resize_handle in ("e", "se"):
            width = round(x)
        if self._resize_handle in ("s", "se"):
            height = round(y)
        return max(1, min(width, MAX_SIZE)), max(1, min(height, MAX_SIZE))

    # Pointer input

    def _make_context(self, button: int) -> ToolContext:
        return ToolContext(
            surface=self._document.surface,
            primary=self.colors.primary,
            secondary=self.colors.secondary,
            button=button,
            size=self.brush_size,
            fill_shapes=self.fill_shapes,
            erase_to_transparency=self.erase_to_transparency,
            tolerance=self.fill_tolerance,
            density=self.airbrush_density,
            reach=scaled(POINT_REACH) / self.zoom,
            pick_color=lambda color, btn: self.emit("color-picked", color, btn),
            begin_text=self.begin_text,
            select_region=self.select_region,
            select_outline=self.select_outline,
        )

    def _on_drag_begin(self, gesture, start_x, start_y):
        if gesture.get_current_button() == Gdk.BUTTON_MIDDLE:
            # The middle button pans the view; it does not paint.
            return
        start_x, start_y = self._to_image(start_x, start_y)
        self._drag_origin = (start_x, start_y)

        if self._text is not None:
            if self._text.contains(start_x, start_y, TEXT_PADDING):
                # A click moves the caret, which leaves any half-composed word behind.
                self._im.reset()
                self._text.set_preedit("", 0)
                self._text_origin = (self._text.x, self._text.y)
                self._text_moved = False
                self.grab_focus()
            else:
                # Clicking away lands the text; the click itself does not draw.
                self.commit_text()
            return

        handle = self._handle_at(start_x, start_y)
        # Ctrl leaves the original where it is, so the drag copies instead of moves.
        copy = bool(gesture.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK)

        if self._paste is not None:
            if handle is not None:
                self._paste_resize_handle = handle
                self._paste_resize_origin = (
                    self._paste.x,
                    self._paste.y,
                    self._paste.width,
                    self._paste.height,
                )
                self._set_cursor(handle)
                return
            if self._paste.contains(start_x, start_y):
                self._paste_origin = (self._paste.x, self._paste.y)
                self._set_cursor("paste")
            else:
                # Clicking away lands the paste; the click itself does not draw.
                self.commit_paste()
            return

        if self.active_tool.adjustable:
            if handle is not None:
                self.active_tool.grab(handle, start_x, start_y)
                self._set_cursor(handle)
            elif self.active_tool.contains(start_x, start_y, self._shape_reach()):
                self.active_tool.grab(None, start_x, start_y)
                self._set_cursor("selection")
            else:
                # Pressing away lands the shape, and this same drag draws the
                # next one; a press that never moves just lands it.
                origin, self._drag_origin = self._drag_origin, None
                self.finish_shape()
                self._drag_origin = origin
            if self.active_tool.adjustable:
                self._shape_adjusting = True
                return

        # Grabbing a selection's own handle scales it in place, without a
        # separate gesture to first lift it the way moving it needs.
        if self.selecting and self._selection is not None and handle is not None:
            self._lift_selection(copy)
            self._paste_resize_handle = handle
            self._paste_resize_origin = (
                self._paste.x,
                self._paste.y,
                self._paste.width,
                self._paste.height,
            )
            self._set_cursor(handle)
            return

        # Only the select tool picks the pixels up; the others paint over them.
        if self._selection_at(start_x, start_y) is not None:
            self._lift_selection(copy)
            self._paste_origin = (self._paste.x, self._paste.y)
            self._set_cursor("paste")
            return

        if handle is not None:
            self._resize_handle = handle
            self._resize_size = (self._document.width, self._document.height)
            self._set_cursor(handle)
            self.queue_draw()
            return

        if not self.active_tool.in_progress:
            self._shape_button = gesture.get_current_button()
        self._drag_context = self._make_context(self._shape_button)
        if self.active_tool.mutates:
            self._document.begin_change()
        self.active_tool.press(self._drag_context, start_x, start_y)
        if self.active_tool.repeat_ms:
            self._repeat_source = GLib.timeout_add(self.active_tool.repeat_ms, self._on_repeat)
        self.queue_draw()

    def _on_repeat(self) -> bool:
        if self._drag_context is None:
            self._repeat_source = 0
            return GLib.SOURCE_REMOVE
        self.active_tool.repeat(self._drag_context)
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _stop_repeat(self) -> None:
        if self._repeat_source:
            GLib.source_remove(self._repeat_source)
            self._repeat_source = 0

    def _on_drag_update(self, gesture, offset_x, offset_y):
        if self._drag_origin is None:
            return
        offset_x, offset_y = offset_x / self.zoom, offset_y / self.zoom
        x, y = self._drag_origin[0] + offset_x, self._drag_origin[1] + offset_y

        if self._text_origin is not None:
            if not self._text_moved and max(abs(offset_x), abs(offset_y)) < MOVE_THRESHOLD:
                # Still small enough to be the wobble of a click placing the caret.
                return
            self._text_moved = True
            self._text.move_to(self._text_origin[0] + offset_x, self._text_origin[1] + offset_y)
            self._refresh_text()
            return

        if self._paste_resize_handle is not None:
            self._resize_paste(x, y)
            return

        if self._shape_adjusting:
            self.active_tool.drag_to(
                x, y, bool(gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK)
            )
            self.queue_draw()
            return

        if self._paste_origin is not None:
            self._paste.move_to(self._paste_origin[0] + offset_x, self._paste_origin[1] + offset_y)
            self._sync_content_size()
            self.queue_draw()
            self.emit("floating-changed")
            return

        if self._resize_handle is not None:
            self._resize_size = self._resized_to(x, y)
            self._sync_content_size()
            self.emit("resize-preview", *self._resize_size)
            self.queue_draw()
            return

        if self._drag_context is None:
            return

        self._drag_context.constrain = bool(
            gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK
        )
        self.active_tool.motion(self._drag_context, x, y)
        self.queue_draw()

    def _on_drag_end(self, gesture, offset_x, offset_y):
        if self._drag_origin is None:
            return
        offset_x, offset_y = offset_x / self.zoom, offset_y / self.zoom
        x, y = self._drag_origin[0] + offset_x, self._drag_origin[1] + offset_y

        if self._text_origin is not None:
            if not self._text_moved:
                # A click rather than a drag: put the caret where it landed.
                self._text.caret_at(x, y)
            self._text_origin = None
            self._text_moved = False
            self._drag_origin = None
            self._refresh_text()
            return

        if self._paste_resize_handle is not None:
            self._resize_paste(x, y)
            self._paste_resize_handle = None
            self._paste_resize_origin = None
            self._drag_origin = None
            return

        if self._shape_adjusting:
            self.active_tool.drag_to(
                x, y, bool(gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK)
            )
            self._shape_adjusting = False
            self._drag_origin = None
            self.queue_draw()
            return

        if self._paste_origin is not None or self._paste is not None:
            # A floating paste stays floating; the drag only moved it.
            self._paste_origin = None
            self._drag_origin = None
            return

        if self._resize_handle is not None:
            width, height = self._resized_to(x, y)
            self._resize_handle = None
            self._resize_size = None
            self._drag_origin = None
            self._document.resize(width, height)
            self._sync_content_size()
            self.queue_draw()
            return

        if self._drag_context is None:
            # The press landed a paste instead of starting a stroke.
            self._drag_origin = None
            return

        self._stop_repeat()
        self._drag_context.constrain = bool(
            gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK
        )
        self.active_tool.release(self._drag_context, x, y)
        if self.active_tool.mutates:
            self._document.finish_change()
        self._drag_origin = None
        self._drag_context = None
        if self.active_tool.in_progress:
            # Enter lands the shape and Esc drops it.
            self.grab_focus()
            self.emit("floating-changed")
        self.queue_draw()

    # Drawing

    def _draw(self, area, cr: cairo.Context, width: int, height: int, *_args):
        image_width, image_height = self._document.width, self._document.height

        # Everything below is laid out in image pixels; this one transform is
        # what makes it appear at the current zoom level on screen.
        cr.save()
        cr.scale(self.zoom, self.zoom)

        cr.save()
        cr.rectangle(0, 0, image_width, image_height)
        cr.clip()
        self._draw_checkerboard(cr)
        cr.set_source_surface(self._document.surface, 0, 0)
        if self.zoom >= SMOOTH_ZOOM_BELOW:
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()

        context = self._drag_context
        if context is None and self.active_tool.in_progress:
            context = self._make_context(self._shape_button)
        if context is not None:
            cr.save()
            self.active_tool.draw_preview(cr, context)
            cr.restore()
        cr.restore()

        if self.pixel_grid_visible:
            self._draw_pixel_grid(cr, image_width, image_height)

        # One screen pixel wide at any zoom, rather than one image pixel, which
        # zoomed in would cover the whole first row and column.
        outline = self.get_color()
        cr.save()
        cr.scale(1 / self.zoom, 1 / self.zoom)
        cr.set_source_rgba(outline.red, outline.green, outline.blue, 0.25)
        cr.set_line_width(1)
        screen_width = round(image_width * self.zoom)
        screen_height = round(image_height * self.zoom)
        cr.rectangle(0.5, 0.5, screen_width - 1, screen_height - 1)
        cr.stroke()
        cr.restore()

        accent = self._accent()
        frame = self.active_tool.frame() if self.active_tool.adjustable else None
        if frame is not None and frame[2] >= 1 and frame[3] >= 1:
            self._draw_dashed_rect(cr, accent, *frame)
        if self._resize_size is not None:
            self._draw_resize_preview(cr, accent, image_width, image_height)
        if self._paste is not None:
            self._draw_paste(cr, accent, image_width, image_height)
        if self._text is not None:
            self._draw_text(cr, accent, image_width, image_height)
        if self._selection is not None:
            if self._selection.outline is not None:
                cr.save()
                cr.rectangle(0, 0, image_width, image_height)
                cr.clip()
                draw_outline_marquee(cr, self._selection.outline)
                cr.restore()
            else:
                draw_marquee(cr, *self._selection.rect)
        self._draw_handles(cr, accent)
        cr.restore()

    def _draw_pixel_grid(self, cr: cairo.Context, image_width: int, image_height: int) -> None:
        """A line between every two pixels, drawn on screen pixels so it stays one pixel thin."""
        cr.save()
        cr.rectangle(0, 0, image_width, image_height)
        cr.clip()
        # Only the lines in view: a large image has far more than the screen shows.
        left, top, right, bottom = cr.clip_extents()
        zoom = self.zoom
        cr.scale(1 / zoom, 1 / zoom)
        for x in range(max(1, int(left)), min(image_width, int(right) + 1)):
            cr.move_to(round(x * zoom) + 0.5, top * zoom)
            cr.line_to(round(x * zoom) + 0.5, bottom * zoom)
        for y in range(max(1, int(top)), min(image_height, int(bottom) + 1)):
            cr.move_to(left * zoom, round(y * zoom) + 0.5)
            cr.line_to(right * zoom, round(y * zoom) + 0.5)
        cr.set_line_width(1)
        # A half-see-through grey darkens light pixels and lightens dark ones,
        # so the lines show on both without hiding the colours between them.
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.45)
        cr.stroke()
        cr.restore()

    @staticmethod
    def _accent() -> Gdk.RGBA:
        return Adw.StyleManager.get_default().get_accent_color_rgba()

    @staticmethod
    def _draw_dashed_rect(
        cr: cairo.Context, accent: Gdk.RGBA, x: float, y: float, width: float, height: float
    ) -> None:
        cr.save()
        cr.set_source_rgba(accent.red, accent.green, accent.blue, 1.0)
        cr.set_line_width(1)
        cr.set_dash([4, 3])
        cr.rectangle(x + 0.5, y + 0.5, width - 1, height - 1)
        cr.stroke()
        cr.restore()

    @staticmethod
    def _draw_overhang(
        cr: cairo.Context,
        x: float,
        y: float,
        width: float,
        height: float,
        image_width: int,
        image_height: int,
    ) -> None:
        """Fill the part of a rectangle that hangs off the image with white.

        That is the colour the canvas grows with, so the preview of a paste or a
        text box matches what committing it produces.
        """
        cr.save()
        cr.rectangle(x, y, width, height)
        cr.clip()
        # Even-odd over both rectangles leaves exactly the overhanging part.
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(x, y, width, height)
        cr.rectangle(0, 0, image_width, image_height)
        cr.set_source_rgb(1, 1, 1)
        cr.fill()
        cr.restore()

    def _draw_resize_preview(
        self, cr: cairo.Context, accent: Gdk.RGBA, image_width: int, image_height: int
    ) -> None:
        width, height = self._resize_size
        cr.save()

        # Even-odd over both rectangles tints exactly what is being added or cropped.
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(0, 0, image_width, image_height)
        cr.rectangle(0, 0, width, height)
        cr.set_source_rgba(accent.red, accent.green, accent.blue, 0.25)
        cr.fill()
        cr.restore()

        self._draw_dashed_rect(cr, accent, 0, 0, width, height)

    def _draw_paste(
        self, cr: cairo.Context, accent: Gdk.RGBA, image_width: int, image_height: int
    ) -> None:
        paste = self._paste
        if paste.source is not None:
            # The pixels are on their way out of here; show the white they leave behind.
            cr.save()
            cr.set_source_rgb(1, 1, 1)
            if paste.source_mask is None:
                cr.rectangle(*paste.source)
                cr.fill()
            else:
                cr.mask_surface(paste.source_mask, paste.source[0], paste.source[1])
            cr.restore()

        self._draw_overhang(
            cr, paste.x, paste.y, paste.width, paste.height, image_width, image_height
        )

        cr.save()
        cr.rectangle(paste.x, paste.y, paste.width, paste.height)
        cr.clip()
        cr.translate(paste.x, paste.y)
        cr.scale(paste.scale_x, paste.scale_y)
        cr.set_source_surface(paste.surface, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()
        cr.restore()

        self._draw_dashed_rect(cr, accent, paste.x, paste.y, paste.width, paste.height)

    def _draw_text(
        self, cr: cairo.Context, accent: Gdk.RGBA, image_width: int, image_height: int
    ) -> None:
        text = self._text
        width, height = text.size
        if width > 0 and height > 0:
            self._draw_overhang(cr, text.x, text.y, width, height, image_width, image_height)
            text.render(cr)

        # The outline sits outside the glyphs, and outside what gets rasterised.
        self._draw_dashed_rect(
            cr,
            accent,
            text.x - TEXT_PADDING,
            text.y - TEXT_PADDING,
            width + 2 * TEXT_PADDING,
            height + 2 * TEXT_PADDING,
        )

        if self._caret_visible:
            caret_x, caret_y, caret_height = text.caret_rect()
            cr.set_source_rgba(
                text.color.red, text.color.green, text.color.blue, text.color.alpha
            )
            cr.rectangle(caret_x, caret_y, 1, caret_height)
            cr.fill()

    def _draw_handles(self, cr: cairo.Context, accent: Gdk.RGBA) -> None:
        size = scaled(HANDLE_SIZE)
        half = size / 2
        for hx, hy in self._handles().values():
            cr.rectangle(hx - half, hy - half, size, size)
            cr.set_source_rgba(accent.red, accent.green, accent.blue, 1.0)
            cr.fill_preserve()
            # A white keyline keeps the grip readable on top of dark artwork.
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(1)
            cr.stroke()

    @staticmethod
    def _draw_checkerboard(cr: cairo.Context) -> None:
        """Fill the current clip with the transparency checkerboard."""
        cr.save()
        cr.set_source(_checker_pattern())
        cr.paint()
        cr.restore()



class CanvasFrame(Gtk.Widget):
    """Centres the canvas in whatever room the scrolled window gives it.

    The offset is held while a button is down or a paste is floating: a resize
    grip or an overhanging paste grows the canvas, and re-centring then would
    slide the image out from under the pointer. It catches up once they end.
    """

    def __init__(self, canvas: Canvas):
        super().__init__()
        self.canvas = canvas
        canvas.set_parent(self)
        self.offset = (0, 0)
        canvas.connect("floating-changed", lambda *_args: self.queue_resize())

    def _held(self) -> bool:
        return self.canvas.is_dragging or self.canvas.has_floating

    def do_dispose(self) -> None:
        self.canvas.unparent()

    def do_get_request_mode(self) -> Gtk.SizeRequestMode:
        return Gtk.SizeRequestMode.CONSTANT_SIZE

    def do_measure(self, orientation: Gtk.Orientation, for_size: int):
        minimum, natural, _, _ = self.canvas.measure(orientation, -1)
        if self._held():
            # Room for the canvas to grow from where it is pinned, not from 0.
            offset = self.offset[0 if orientation == Gtk.Orientation.HORIZONTAL else 1]
            minimum, natural = minimum + offset, natural + offset
        return minimum, natural, -1, -1

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        _, child_width, _, _ = self.canvas.measure(Gtk.Orientation.HORIZONTAL, -1)
        _, child_height, _, _ = self.canvas.measure(Gtk.Orientation.VERTICAL, -1)
        if not self._held():
            self.offset = (max(0, (width - child_width) // 2), max(0, (height - child_height) // 2))
        x, y = self.offset
        allocation = Gdk.Rectangle()
        allocation.x, allocation.y = x, y
        allocation.width, allocation.height = child_width, child_height
        self.canvas.size_allocate(allocation, -1)
