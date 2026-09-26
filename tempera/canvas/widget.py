# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The canvas widget itself, assembled from the parts in this package."""

from __future__ import annotations


from gi.repository import Gdk, Gio, GObject, Gtk

from ..color import ColorState
from ..document import Document
from ..i18n import _
from ..interface_size import scaled
from ..selection import Selection
from ..text import DEFAULT_FONT, TextBox
from ..tools import (
    AIRBRUSH_TOOL_ID,
    DEFAULT_DENSITY,
    DEFAULT_TOLERANCE,
    ERASER_TOOL_ID,
    FILL_TOOL_ID,
    SHAPES_TOOL_ID,
    TEXT_TOOL_ID,
    Tool,
    ToolContext,
    create_tools,
)
from .floating import FloatingMixin, FloatingPaste
from .pointer import HANDLE_MARGIN, PointerMixin
from .render import RenderMixin
from .selecting import SelectionMixin
from .view import PIXEL_GRID_ZOOM, ZoomMixin


class Canvas(
    PointerMixin, FloatingMixin, SelectionMixin, ZoomMixin, RenderMixin, Gtk.DrawingArea
):
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
        self._outline_shapes = True
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
        # A slow press, such as a fill, still at work off the UI thread, and
        # where the button was let go if that happened first.
        self._working = False
        self._pending_release: tuple[float, float] | None = None

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
        """Whether a stroke, move or resize is under way: a button is held, or a fill still at work."""
        return self._drag_origin is not None or self._working

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

    @property
    def outline_shapes(self) -> bool:
        return self._outline_shapes

    @outline_shapes.setter
    def outline_shapes(self, value: bool) -> None:
        self._outline_shapes = value
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
