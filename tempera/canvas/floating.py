# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""What hovers over the canvas until it lands: a paste, a text box, or a shape."""

from __future__ import annotations

import math
from dataclasses import dataclass

import cairo
from gi.repository import Gdk, Gio, GLib

from ..clipboard import surface_from_texture
from ..document import MAX_SIZE
from ..file_io import load_surface_async
from ..i18n import _
from ..interface_size import scaled
from ..regions import without_color
from ..text import TextBox
from ..tools.base import rect_handles

# Breathing room between the typed text and its dashed outline.
TEXT_PADDING = 3
CARET_BLINK_MS = 530
CUT_OFF_MESSAGE = _("Part of the image was cut off: a canvas can be at most {size} × {size} px").format(
    size=MAX_SIZE
)
# Arrow-key nudge for a selection or floating paste, in image pixels; Shift steps further.
NUDGE_STEP = 1
NUDGE_STEP_FAST = 10


# The rotate grip sits this far above the middle of a paste's top edge, in
# image pixels at the default interface size, like the other grips.
ROTATE_GRIP_OFFSET = 22
# Holding Shift turns a paste in steps of this many degrees.
ROTATE_SNAP_DEGREES = 15
# How far a paste can be skewed: past this it is a sliver.
MAX_SHEAR = 3.0
# Grips that skew rather than stretch, with Ctrl held.
SIDE_GRIPS = ("n", "s", "e", "w")


Point = tuple[float, float]


def rotate_grip(x: float, y: float, width: float, height: float) -> tuple[Point, Point]:
    """Where the rotate grip of an upright box sits, and the middle of the edge its
    stalk runs from: above the top, or below the bottom when there is no room
    above, where the canvas could not be reached."""
    reach = scaled(ROTATE_GRIP_OFFSET)
    middle = x + width / 2
    if y - reach >= 0:
        return (middle, y - reach), (middle, y)
    return (middle, y + height + reach), (middle, y + height)


@dataclass
class FloatingPaste:
    """Pasted pixels hovering over the canvas until they are stamped down.

    It is a box: `x`, `y` is its top-left corner as it would be upright, its
    size is the surface's times the scale, and it may be turned by `angle` and
    skewed by `shear_x` and `shear_y` about its middle.
    """

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
    # The pixels as they were lifted or pasted, before a transparent
    # selection left a colour out of `surface`.
    original: cairo.ImageSurface | None = None
    # Turned clockwise, in radians, and skewed: a shear_x of 1 slides the
    # bottom edge one box height right of the top, a shear_y of 1 the right
    # edge one box width down from the left.
    angle: float = 0.0
    shear_x: float = 0.0
    shear_y: float = 0.0

    def __post_init__(self) -> None:
        if self.original is None:
            self.original = self.surface

    def leave_out(self, color: Gdk.RGBA | None) -> None:
        """Make the pixels of one colour see-through, or with None bring them all back."""
        self.surface = self.original if color is None else without_color(self.original, color)

    @property
    def width(self) -> int:
        return round(self.surface.get_width() * self.scale_x)

    @property
    def height(self) -> int:
        return round(self.surface.get_height() * self.scale_y)

    @property
    def transformed(self) -> bool:
        """Whether it is turned or skewed, rather than an upright box."""
        return self.angle != 0 or self.shear_x != 0 or self.shear_y != 0

    # Geometry. The box's own frame has (0, 0) at its top-left and runs to
    # (box_width, box_height); the image's frame is image pixels.

    @property
    def box_size(self) -> tuple[float, float]:
        return self.surface.get_width() * self.scale_x, self.surface.get_height() * self.scale_y

    @property
    def center(self) -> tuple[float, float]:
        width, height = self.box_size
        return self.x + width / 2, self.y + height / 2

    def _linear(self) -> tuple[float, float, float, float]:
        """The turn and skew as a 2 × 2 matrix (xx, xy, yx, yy): the rotation after the shear."""
        cos, sin = math.cos(self.angle), math.sin(self.angle)
        kx, ky = self.shear_x, self.shear_y
        return cos - sin * ky, cos * kx - sin, sin + cos * ky, sin * kx + cos

    def matrix(self) -> cairo.Matrix:
        """From the box's frame to the image's."""
        xx, xy, yx, yy = self._linear()
        width, height = self.box_size
        cx, cy = self.center
        return cairo.Matrix(
            xx, yx, xy, yy, cx - (xx * width / 2 + xy * height / 2), cy - (yx * width / 2 + yy * height / 2)
        )

    def to_image(self, u: float, v: float) -> tuple[float, float]:
        return self.matrix().transform_point(u, v)

    def to_box(self, x: float, y: float) -> tuple[float, float]:
        inverse = self.matrix()
        inverse.invert()
        return inverse.transform_point(x, y)

    def corners(self) -> list[tuple[float, float]]:
        width, height = self.box_size
        return [self.to_image(u, v) for u, v in ((0, 0), (width, 0), (width, height), (0, height))]

    def bounds(self) -> tuple[float, float, float, float]:
        """The upright rectangle around it, as (x, y, width, height)."""
        if not self.transformed:
            return self.x, self.y, self.width, self.height
        xs = [x for x, _y in self.corners()]
        ys = [y for _x, y in self.corners()]
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)

    def contains(self, x: float, y: float) -> bool:
        if not self.transformed:
            return self.x <= x <= self.x + self.width and self.y <= y <= self.y + self.height
        u, v = self.to_box(x, y)
        width, height = self.box_size
        return 0 <= u <= width and 0 <= v <= height

    def handles(self) -> dict[str, Point]:
        """The grips: eight to stretch it, turning with it, and one beyond it to turn it by."""
        width, height = self.box_size
        if not self.transformed:
            grips = rect_handles(self.x, self.y, self.width, self.height)
        else:
            grips = {name: self.to_image(u - self.x, v - self.y)
                     for name, (u, v) in rect_handles(self.x, self.y, width, height).items()}
        grips["rotate"] = self.rotate_grip()[0]
        return grips

    def rotate_grip(self) -> tuple[Point, Point]:
        """Where the grip that turns it sits, and the middle of the edge its stalk
        runs from: beyond the top edge as it now lies, whichever way that is,
        or beyond the bottom one when that would be off the canvas."""
        if not self.transformed:
            return rotate_grip(self.x, self.y, self.width, self.height)
        width, height = self.box_size
        middle = self.to_image(width / 2, height / 2)
        reach = scaled(ROTATE_GRIP_OFFSET)
        for v in (0, height):
            edge = self.to_image(width / 2, v)
            length = math.hypot(edge[0] - middle[0], edge[1] - middle[1]) or 1.0
            grip = (
                edge[0] + (edge[0] - middle[0]) / length * reach,
                edge[1] + (edge[1] - middle[1]) / length * reach,
            )
            if grip[0] >= 0 and grip[1] >= 0:
                break
        return grip, edge

    def move_to(self, x: float, y: float) -> None:
        # Never past the top-left: the canvas only ever grows right and down, so
        # the image keeps the same anchor a resize would give it.
        self.x = max(0.0, x)
        self.y = max(0.0, y)

    # Turning, skewing and stretching, each worked out from how it was when
    # the grip was taken hold of, so the pointer alone says where it is.

    def rotate_from(
        self, grabbed: FloatingPaste, start: tuple[float, float], point: tuple[float, float], snap: bool
    ) -> None:
        cx, cy = grabbed.center
        turned = math.atan2(point[1] - cy, point[0] - cx) - math.atan2(start[1] - cy, start[0] - cx)
        angle = grabbed.angle + turned
        if snap:
            step = math.radians(ROTATE_SNAP_DEGREES)
            angle = round(angle / step) * step
        # Kept between -180° and 180°, and exactly upright when it comes back round.
        angle = math.remainder(angle, 2 * math.pi)
        self.angle = 0.0 if abs(angle) < 1e-9 else angle

    def skew_from(
        self, grabbed: FloatingPaste, handle: str, start: tuple[float, float], point: tuple[float, float]
    ) -> None:
        """Slide one side along itself, the side facing it staying put."""
        cos, sin = math.cos(grabbed.angle), math.sin(grabbed.angle)
        dx, dy = point[0] - start[0], point[1] - start[1]
        width, height = grabbed.box_size
        cx, cy = grabbed.center
        if handle in ("n", "s"):
            # Along the box's own across, turned with it.
            moved = dx * cos + dy * sin
            shear_x = grabbed.shear_x + (moved if handle == "s" else -moved) / height
            shear_y = grabbed.shear_y
            shift = (cos * moved / 2, sin * moved / 2)
        else:
            moved = -dx * sin + dy * cos
            shear_x = grabbed.shear_x
            shear_y = grabbed.shear_y + (moved if handle == "e" else -moved) / width
            shift = (-sin * moved / 2, cos * moved / 2)
        shear_x = max(-MAX_SHEAR, min(shear_x, MAX_SHEAR))
        shear_y = max(-MAX_SHEAR, min(shear_y, MAX_SHEAR))
        if 1 - shear_x * shear_y < 0.2:
            # Skewed both ways at once, it would fold flat.
            return
        self.shear_x, self.shear_y = shear_x, shear_y
        self.x = cx + shift[0] - width / 2
        self.y = cy + shift[1] - height / 2

    def resize_from(self, grabbed: FloatingPaste, handle: str, point: tuple[float, float]) -> None:
        """Stretch it along its own sides as they lie, the grip following the pointer
        and the sides it does not touch staying put."""
        width, height = grabbed.box_size
        u, v = grabbed.to_box(*point)
        left, top, right, bottom = 0.0, 0.0, width, height
        if "w" in handle:
            left = min(u, right - 1)
        elif "e" in handle:
            right = max(u, left + 1)
        if "n" in handle:
            top = min(v, bottom - 1)
        elif "s" in handle:
            bottom = max(v, top + 1)
        new_width, new_height = min(right - left, MAX_SIZE), min(bottom - top, MAX_SIZE)
        cx, cy = grabbed.to_image((left + right) / 2, (top + bottom) / 2)
        self.scale_x = new_width / self.surface.get_width()
        self.scale_y = new_height / self.surface.get_height()
        self.x, self.y = cx - new_width / 2, cy - new_height / 2

    # Landing

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

    def landing(self) -> tuple[cairo.ImageSurface, int, int]:
        """The pixels as they will land, and where their top-left corner goes."""
        if not self.transformed:
            return self.rendered(), round(self.x), round(self.y)
        left, top, width, height = self.bounds()
        # What lies above or left of the canvas is lost: it only grows right and down.
        x0, y0 = max(0, math.floor(left)), max(0, math.floor(top))
        x1, y1 = math.ceil(left + width), math.ceil(top + height)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, x1 - x0), max(1, y1 - y0))
        cr = cairo.Context(surface)
        cr.translate(-x0, -y0)
        cr.transform(self.matrix())
        cr.scale(self.scale_x, self.scale_y)
        cr.set_source_surface(self.surface, 0, 0)
        # Turned, pixels no longer line up with pixels; blending them reads
        # better than the jagged edges picking the nearest would give.
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        cr.rectangle(0, 0, self.surface.get_width(), self.surface.get_height())
        cr.fill()
        return surface, x0, y0

    def paint(self, cr: cairo.Context) -> None:
        """Draw the pixels where they float, for the preview."""
        cr.save()
        cr.transform(self.matrix())
        cr.scale(self.scale_x, self.scale_y)
        cr.set_source_surface(self.surface, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_GOOD if self.transformed else cairo.FILTER_NEAREST)
        cr.rectangle(0, 0, self.surface.get_width(), self.surface.get_height())
        cr.fill()
        cr.restore()


class FloatingMixin:
    """A paste, a text box or a shape still being placed, and the keys that move or land them."""

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
            x, y, width, height = self._paste.bounds()
            return x, y, math.ceil(width), math.ceil(height)
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
        context = self._make_context(self._shape_button)
        self._document.begin_change()
        self.active_tool.finish(context)
        self._document.finish_change()
        self.colors.remember(*self.active_tool.colors_used(context))
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
        self._paste.leave_out(self._left_out_color())
        self._paste.move_to(x, y)
        self.grab_focus()
        self._sync_content_size()
        self.queue_draw()
        self.emit("floating-changed")

    # Transparent selection

    @property
    def transparent_selection(self) -> bool:
        return self._transparent_selection

    @transparent_selection.setter
    def transparent_selection(self, value: bool) -> None:
        self._transparent_selection = value
        self._refresh_left_out()

    def _left_out_color(self) -> Gdk.RGBA | None:
        """The colour a transparent selection leaves out of what it moves or pastes:
        the secondary, as in Paint, where it is the background colour."""
        return self.colors.secondary if self._transparent_selection else None

    def _refresh_left_out(self) -> None:
        """Show a floating paste with the colour left out as it is now."""
        if self._paste is None:
            return
        self._paste.leave_out(self._left_out_color())
        self.queue_draw()

    def commit_paste(self) -> bool:
        """Stamp the floating image into the document, growing the canvas to fit."""
        if self._paste is None:
            return False
        paste, self._paste = self._paste, None
        pixels, x, y = paste.landing()
        cut_off = self._document.paste(
            pixels, x, y, erase=paste.source, erase_mask=paste.source_mask
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
        if surface is not None:
            if self._document.paste(surface, round(text.x), round(text.y)):
                self.emit("message", CUT_OFF_MESSAGE)
            self.colors.remember(text.color)
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
        if self._working:
            # A fill is still painting; Delete or a nudge would paint under it.
            return False
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
