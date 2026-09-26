# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import ctypes
import math
from dataclasses import dataclass

import cairo
from gi.repository import Gdk, GdkPixbuf, GObject

from .i18n import _

MAX_UNDO = 50
# An undo step keeps only the rectangle the edit changed, but a fill or a
# rotation changes all of it, so the history is also capped by memory: 50 whole
# steps of the largest canvas would take 12.8 GB. The newest step is always
# kept, whatever its size.
UNDO_BUDGET = 1024 * 1024 * 1024
DEFAULT_WIDTH = 800
DEFAULT_HEIGHT = 600
MAX_SIZE = 8192
# Each layer is a whole canvas of pixels, so this also bounds the memory a
# picture can take.
MAX_LAYERS = 100
WHITE = (1.0, 1.0, 1.0, 1.0)
TRANSPARENT = (0.0, 0.0, 0.0, 0.0)

_libc = ctypes.CDLL(None)
_libc.memcmp.restype = ctypes.c_int
_libc.memcmp.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t)


def new_surface(width: int, height: int, fill=(1.0, 1.0, 1.0, 1.0)) -> cairo.ImageSurface:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_rgba(*fill)
    cr.paint()
    return surface


def surface_from_pixbuf(pixbuf: GdkPixbuf.Pixbuf) -> cairo.ImageSurface:
    """Copy a pixbuf into a surface Tempera can draw on."""
    surface = new_surface(pixbuf.get_width(), pixbuf.get_height(), (0, 0, 0, 0))
    cr = cairo.Context(surface)
    Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.paint()
    return surface


def crop_surface(
    src: cairo.ImageSurface, x: int, y: int, width: int, height: int
) -> cairo.ImageSurface:
    """A copy of one rectangle of a surface, for lifting a selection out of it."""
    dst = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(dst)
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_surface(src, -x, -y)
    cr.paint()
    return dst


def keep_inside(surface: cairo.ImageSurface, mask: cairo.ImageSurface) -> None:
    """Make every pixel outside the mask transparent, in place."""
    cr = cairo.Context(surface)
    # Keeps the pixels as much as the mask covers them, and no more.
    cr.set_operator(cairo.OPERATOR_DEST_IN)
    cr.set_source_surface(mask, 0, 0)
    cr.paint()


def copy_surface(src: cairo.ImageSurface) -> cairo.ImageSurface:
    dst = cairo.ImageSurface(cairo.FORMAT_ARGB32, src.get_width(), src.get_height())
    cr = cairo.Context(dst)
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_surface(src, 0, 0)
    cr.paint()
    return dst


def surface_bytes(surface: cairo.ImageSurface) -> int:
    return surface.get_stride() * surface.get_height()


def _row_pointers(surface: cairo.ImageSurface) -> tuple[int, int]:
    """The address of a surface's pixels, and how far apart its rows are."""
    data = surface.get_data()
    return ctypes.addressof(ctypes.c_char.from_buffer(data)), surface.get_stride()


def changed_rect(
    before: cairo.ImageSurface, after: cairo.ImageSurface
) -> tuple[int, int, int, int] | None:
    """The smallest rectangle holding every pixel that differs, or None if none do.

    Both surfaces must be the same size. Rows are compared whole with memcmp; the
    left and right edges are then narrowed by halving, so a stroke across a big
    photo costs a few thousand comparisons rather than a walk over every byte.
    """
    width, height = after.get_width(), after.get_height()
    before.flush()
    after.flush()
    a, stride = _row_pointers(before)
    b, _stride = _row_pointers(after)
    row_bytes = width * 4

    def differs(y: int, start: int, end: int) -> bool:
        """Whether row y differs anywhere in pixels start to end, end excluded."""
        offset = y * stride + start * 4
        return _libc.memcmp(a + offset, b + offset, (end - start) * 4) != 0

    top = 0
    while top < height and _libc.memcmp(a + top * stride, b + top * stride, row_bytes) == 0:
        top += 1
    if top == height:
        return None
    bottom = height - 1
    while _libc.memcmp(a + bottom * stride, b + bottom * stride, row_bytes) == 0:
        bottom -= 1

    # Pixels left of `left` and right of `right` are known to match so far;
    # each row that differs outside them pushes them out.
    left, right = width, 0
    for y in range(top, bottom + 1):
        if left > 0 and differs(y, 0, left):
            low, high = 0, left - 1
            # The first differing pixel: the smallest n with a difference in [0, n].
            while low < high:
                middle = (low + high) // 2
                if differs(y, 0, middle + 1):
                    high = middle
                else:
                    low = middle + 1
            left = low
        if right < width and differs(y, right, width):
            low, high = right, width
            # One past the last differing pixel: the largest n with a difference in [n - 1, width).
            while low < high:
                middle = (low + high + 1) // 2
                if differs(y, middle - 1, width):
                    low = middle
                else:
                    high = middle - 1
            right = low
    return left, top, right - left, bottom - top + 1


def same_pixels(a: cairo.ImageSurface, b: cairo.ImageSurface) -> bool:
    """Whether two surfaces hold identical images.

    Compared with memcmp, since comparing the memoryviews from Python walks them
    a byte at a time: about 300 ms for the largest canvas against 10 ms.
    """
    if (a.get_width(), a.get_height()) != (b.get_width(), b.get_height()):
        return False
    a.flush()
    b.flush()
    a_data, b_data = a.get_data(), b.get_data()
    size = len(a_data)
    if size != len(b_data):
        return False
    a_buffer = (ctypes.c_char * size).from_buffer(a_data)
    b_buffer = (ctypes.c_char * size).from_buffer(b_data)
    return _libc.memcmp(a_buffer, b_buffer, size) == 0


def flatten(
    layers: list[Layer], x: int, y: int, width: int, height: int
) -> cairo.ImageSurface:
    """One rectangle of the picture as it shows: the visible layers, each at its
    opacity, one over another."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    for layer in layers:
        if layer.visible and layer.opacity > 0:
            cr.set_source_surface(layer.surface, -x, -y)
            cr.paint_with_alpha(layer.opacity)
    return surface


class Layer:
    """One sheet of the picture: its pixels, and how they show over the sheets beneath."""

    __slots__ = ("surface", "name", "visible", "opacity")

    def __init__(
        self, surface: cairo.ImageSurface, name: str, visible: bool = True, opacity: float = 1.0
    ):
        self.surface = surface
        self.name = name
        self.visible = visible
        self.opacity = opacity


@dataclass(frozen=True)
class LayerState:
    """How one layer stood at a point in the history."""

    layer: Layer
    surface: cairo.ImageSurface
    name: str
    visible: bool
    opacity: float

    @classmethod
    def of(cls, layer: Layer) -> LayerState:
        return cls(layer, layer.surface, layer.name, layer.visible, layer.opacity)

    def restore(self) -> Layer:
        layer = self.layer
        layer.surface, layer.name = self.surface, self.name
        layer.visible, layer.opacity = self.visible, self.opacity
        return layer


# What a change reports it touched, for the views to redraw: pairs of a layer
# and the rectangle of it that changed (None for all of it), or None when
# anything anywhere may have.
Damage = list[tuple[Layer, tuple[int, int, int, int] | None]] | None


class Patch:
    """A step of the history that puts back one rectangle of one layer's pixels.

    A change that altered nothing has no pixels at all.
    """

    __slots__ = ("layer", "x", "y", "pixels")

    def __init__(self, layer: Layer, x: int, y: int, pixels: cairo.ImageSurface | None):
        self.layer, self.x, self.y, self.pixels = layer, x, y, pixels

    @property
    def nbytes(self) -> int:
        return surface_bytes(self.pixels) if self.pixels is not None else 0

    @property
    def rect(self) -> tuple[int, int, int, int]:
        if self.pixels is None:
            return (self.x, self.y, 0, 0)
        return (self.x, self.y, self.pixels.get_width(), self.pixels.get_height())

    def damage(self) -> Damage:
        return [] if self.pixels is None else [(self.layer, self.rect)]

    def apply(self, document: Document) -> Patch:
        """Put the pixels back; returns the patch that reverses it."""
        if self.pixels is None:
            return self
        surface = self.layer.surface
        width, height = self.pixels.get_width(), self.pixels.get_height()
        reverse = Patch(self.layer, self.x, self.y, crop_surface(surface, self.x, self.y, width, height))
        cr = cairo.Context(surface)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_surface(self.pixels, self.x, self.y)
        cr.rectangle(self.x, self.y, width, height)
        cr.fill()
        return reverse


def patch_between(
    layer: Layer, before: cairo.ImageSurface, after: cairo.ImageSurface
) -> Patch | None:
    """What it takes to turn a layer's `after` back into `before`, or None if they are the same."""
    rect = changed_rect(before, after)
    if rect is None:
        return None
    return Patch(layer, rect[0], rect[1], crop_surface(before, *rect))


class StackChange:
    """A step of the history that puts back the layers: which there are, in what
    order, their surfaces and settings, and which one is current.

    It holds on to the surfaces rather than copies of them. An edit that makes
    new surfaces, such as a rotation, leaves the old ones as they were, and the
    steps taken since are undone before this one is, so each surface is back
    to how it was when this step was taken by the time it is needed again.
    """

    __slots__ = ("layers", "current", "nbytes")

    def __init__(self, layers: tuple[LayerState, ...], current: int):
        self.layers = layers
        self.current = current
        self.nbytes = 0

    @classmethod
    def of(cls, document: Document) -> StackChange:
        return cls(tuple(LayerState.of(layer) for layer in document.layers), document.current)

    def count_against(self, document: Document) -> None:
        """Count only the memory this step alone keeps: the surfaces no layer has any more."""
        live = {id(layer.surface) for layer in document.layers}
        self.nbytes = sum(
            surface_bytes(state.surface) for state in self.layers if id(state.surface) not in live
        )

    def differs_from(self, document: Document) -> bool:
        """Whether a layer came or went, or any was given a new surface, since this was taken."""
        if len(self.layers) != len(document.layers):
            return True
        return any(
            state.layer is not layer or state.surface is not layer.surface
            for state, layer in zip(self.layers, document.layers)
        )

    def apply(self, document: Document) -> StackChange:
        reverse = StackChange.of(document)
        document.layers = [state.restore() for state in self.layers]
        document.current = self.current
        reverse.count_against(document)
        return reverse


class Document(GObject.Object):
    """The painted image, as a stack of layers, plus its undo history.

    `surface` is the current layer's: the one the tools paint on. The layers
    are listed bottom first.
    """

    __gsignals__ = {
        "content-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # A layer came, went, moved or changed its settings, or another
        # became the current one.
        "layers-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(
        self, surface: cairo.ImageSurface | None = None, layers: list[Layer] | None = None
    ):
        super().__init__()
        if layers is None:
            layers = [Layer(surface or new_surface(DEFAULT_WIDTH, DEFAULT_HEIGHT), _("Background"))]
        self.layers: list[Layer] = list(layers)
        # The top layer, as for an image opened with several.
        self.current = len(self.layers) - 1
        self.file = None
        self._undo: list[Patch | StackChange] = []
        self._redo: list[Patch | StackChange] = []
        # How many undo steps deep the saved image sits, so undoing back to it
        # counts as unmodified. None once no undo or redo can reach it again.
        self._saved_depth: int | None = 0
        # The current layer as it was when begin_change() was called, and the
        # layers around it, until the change is committed and only the part it
        # altered is kept.
        self._before: cairo.ImageSurface | None = None
        self._before_layer: Layer | None = None
        self._before_stack: StackChange | None = None
        # What the last change touched, for views that redraw only that.
        self.damage: Damage = None
        # The step an opacity slider being dragged is adding up to.
        self._adjusting: StackChange | None = None

    @property
    def layer(self) -> Layer:
        """The layer the tools paint on."""
        return self.layers[self.current]

    @property
    def surface(self) -> cairo.ImageSurface:
        return self.layers[self.current].surface

    @property
    def width(self) -> int:
        return self.layers[0].surface.get_width()

    @property
    def height(self) -> int:
        return self.layers[0].surface.get_height()

    @property
    def title(self) -> str:
        return self.file.get_basename() if self.file else "Untitled"

    @property
    def modified(self) -> bool:
        return self._saved_depth != len(self._undo)

    @modified.setter
    def modified(self, value: bool) -> None:
        # Saving marks the image as it is now; anything else just forgets
        # where the saved one was.
        self._saved_depth = None if value else len(self._undo)

    def save_point(self) -> int:
        """How deep the history is now, to mark as saved once a save finishes."""
        return len(self._undo)

    def mark_saved(self, depth: int) -> None:
        """Take the image at that point in the history as the saved one.

        Saving encodes and writes in the background, so the user may have drawn
        on since; the marker belongs to what was written, not to what is on
        screen now.
        """
        self._saved_depth = depth
        self.emit("state-changed")

    # The picture as a whole

    def flattened(
        self, x: int = 0, y: int = 0, width: int | None = None, height: int | None = None
    ) -> cairo.ImageSurface:
        """The picture as it shows, or one rectangle of it: the visible layers, each at
        its opacity, one over another."""
        width = self.width if width is None else width
        height = self.height if height is None else height
        return flatten(self.layers, x, y, width, height)

    def to_pixbuf(self) -> GdkPixbuf.Pixbuf:
        flattened = self.flattened()
        flattened.flush()
        return Gdk.pixbuf_get_from_surface(flattened, 0, 0, self.width, self.height)

    # History

    def _changed(self, damage: Damage, layers: bool = False) -> None:
        """Tell the views the image changed, and where."""
        self.damage = damage
        self.emit("content-changed")
        if layers:
            self.emit("layers-changed")
        self.emit("state-changed")

    def begin_change(self) -> None:
        """Snapshot the current layer so the coming edit to it can be undone."""
        self._before = copy_surface(self.surface)
        self._before_layer = self.layer
        self._before_stack = StackChange.of(self)

    def _record(self, step: Patch | StackChange) -> None:
        self._adjusting = None
        self._undo.append(step)
        if self._redo and self._saved_depth is not None and self._saved_depth >= len(self._undo):
            # The saved image was among the redo steps about to be dropped.
            self._saved_depth = None
        self._redo = []
        self._trim_history()

    def _end_change(self, keep_unchanged: bool) -> None:
        if self._before is None:
            if keep_unchanged:
                self._changed(None)
            return
        before, self._before = self._before, None
        layer, self._before_layer = self._before_layer, None
        stack, self._before_stack = self._before_stack, None
        if stack.differs_from(self):
            # The canvas grew under a paste: every layer has a new surface.
            stack.count_against(self)
            self._record(stack)
            self._changed(None, layers=True)
            return
        patch = patch_between(layer, before, layer.surface)
        if patch is None:
            if not keep_unchanged:
                return
            patch = Patch(layer, 0, 0, None)
        self._record(patch)
        self._changed(patch.damage())

    def commit_change(self) -> None:
        """Keep the change begun earlier as one undo step, even if it altered nothing."""
        self._end_change(keep_unchanged=True)

    def finish_change(self) -> None:
        """Commit the change begun earlier, unless the image came out identical.

        A fill in the colour already there, or a stroke off the canvas, then
        leaves no undo step behind and does not mark the image as modified.
        """
        self._end_change(keep_unchanged=False)

    def _trim_history(self) -> None:
        """Drop the oldest undo steps past MAX_UNDO or UNDO_BUDGET, keeping the newest."""
        kept = len(self._undo)
        total = sum(step.nbytes for step in self._undo)
        excess = 0
        while kept > 1 and (kept > MAX_UNDO or total > UNDO_BUDGET):
            total -= self._undo[excess].nbytes
            excess += 1
            kept -= 1
        if excess == 0:
            return
        del self._undo[:excess]
        if self._saved_depth is not None:
            # Trimmed away along with the oldest steps, it is out of reach.
            depth = self._saved_depth - excess
            self._saved_depth = depth if depth >= 0 else None

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def _step_back(self, source: list, target: list) -> None:
        step = source.pop()
        target.append(step.apply(self))
        if isinstance(step, StackChange):
            self._changed([], layers=True)
        else:
            self._changed(step.damage())

    def undo(self) -> None:
        # Not in the middle of a stroke: the step it would take back is not
        # finished, and taking an older one back would tangle the two.
        if not self._undo or self._before is not None:
            return
        self._step_back(self._undo, self._redo)

    def redo(self) -> None:
        if not self._redo or self._before is not None:
            return
        self._step_back(self._redo, self._undo)
        self._trim_history()

    def _change_stack(self, change, pixels: bool = False) -> None:
        """Make a change to the layers as one step of the history.

        `pixels` says it painted new pixels, as a merge or a rotation does,
        rather than only arranging the layers or changing their settings.
        """
        step = StackChange.of(self)
        change()
        step.count_against(self)
        self._record(step)
        self._changed(None if pixels else [], layers=True)

    # Layers

    def _new_layer_name(self) -> str:
        names = {layer.name for layer in self.layers}
        number = len(self.layers) + 1
        while _("Layer {number}").format(number=number) in names:
            number += 1
        return _("Layer {number}").format(number=number)

    def select_layer(self, index: int) -> None:
        """Make another layer the one the tools paint on. Not a step of the history."""
        if 0 <= index < len(self.layers) and index != self.current:
            self.current = index
            self.emit("layers-changed")

    def add_layer(self) -> bool:
        """A new, empty layer just above the current one, which it becomes."""
        if len(self.layers) >= MAX_LAYERS:
            return False
        layer = Layer(new_surface(self.width, self.height, TRANSPARENT), self._new_layer_name())

        def change():
            self.layers.insert(self.current + 1, layer)
            self.current += 1

        self._change_stack(change)
        return True

    def duplicate_layer(self) -> bool:
        """A copy of the current layer just above it, which becomes the current one."""
        if len(self.layers) >= MAX_LAYERS:
            return False
        original = self.layer
        copy = Layer(
            copy_surface(original.surface),
            _("{name} copy").format(name=original.name),
            original.visible,
            original.opacity,
        )

        def change():
            self.layers.insert(self.current + 1, copy)
            self.current += 1

        self._change_stack(change)
        return True

    def delete_layer(self) -> bool:
        """Remove the current layer; the one beneath takes its place. The last one stays."""
        if len(self.layers) == 1:
            return False

        def change():
            del self.layers[self.current]
            self.current = max(0, self.current - 1)

        self._change_stack(change)
        return True

    def move_layer(self, index: int, to: int) -> bool:
        """Move a layer up or down the stack. The current layer stays current, wherever it goes."""
        count = len(self.layers)
        if not (0 <= index < count and 0 <= to < count) or index == to:
            return False

        def change():
            current = self.layer
            self.layers.insert(to, self.layers.pop(index))
            self.current = self.layers.index(current)

        self._change_stack(change)
        return True

    def merge_down(self) -> bool:
        """Paint the current layer, at its opacity, onto the one beneath, and remove it."""
        if self.current == 0:
            return False
        upper, lower = self.layers[self.current], self.layers[self.current - 1]
        merged = copy_surface(lower.surface)
        cr = cairo.Context(merged)
        cr.set_source_surface(upper.surface, 0, 0)
        cr.paint_with_alpha(upper.opacity)

        def change():
            lower.surface = merged
            del self.layers[self.current]
            self.current -= 1

        self._change_stack(change, pixels=True)
        return True

    def flatten(self) -> bool:
        """Merge the layers that show into one; the hidden ones are dropped."""
        if len(self.layers) == 1:
            return False
        layer = Layer(self.flattened(), self.layers[0].name)

        def change():
            self.layers = [layer]
            self.current = 0

        self._change_stack(change, pixels=True)
        return True

    def _set_layer(self, index: int, attribute: str, value) -> bool:
        if not 0 <= index < len(self.layers) or getattr(self.layers[index], attribute) == value:
            return False
        self._change_stack(lambda: setattr(self.layers[index], attribute, value))
        return True

    def set_layer_visible(self, index: int, visible: bool) -> bool:
        return self._set_layer(index, "visible", visible)

    def rename_layer(self, index: int, name: str) -> bool:
        return self._set_layer(index, "name", name)

    def set_layer_opacity(self, index: int, opacity: float) -> bool:
        """Change how see-through a layer is.

        Dragging a slider asks many times over; while nothing else happens in
        between, the changes add up to one step of the history.
        """
        opacity = max(0.0, min(float(opacity), 1.0))
        if not 0 <= index < len(self.layers) or self.layers[index].opacity == opacity:
            return False
        if (
            self._adjusting is not None
            and self._undo
            and self._undo[-1] is self._adjusting
            and self._adjusting.layers[index].layer is self.layers[index]
            and self._saved_depth != len(self._undo)
        ):
            self.layers[index].opacity = opacity
            self._changed([], layers=True)
            return True
        self._set_layer(index, "opacity", opacity)
        self._adjusting = self._undo[-1]
        return True

    # Edits to the whole image, every layer at once

    def _vacated_fill(self, index: int | None = None) -> tuple[float, float, float, float]:
        """What a layer's emptied pixels become: white at the bottom, where the
        canvas is made of it, and see-through above, so what is beneath shows."""
        index = self.current if index is None else index
        return WHITE if index == 0 else TRANSPARENT

    @staticmethod
    def _resized_surface(
        surface: cairo.ImageSurface, width: int, height: int, fill=WHITE
    ) -> cairo.ImageSurface:
        """A surface on a differently sized canvas, anchored top-left."""
        resized = new_surface(width, height, fill)
        cr = cairo.Context(resized)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_surface(surface, 0, 0)
        cr.rectangle(0, 0, min(width, surface.get_width()), min(height, surface.get_height()))
        cr.fill()
        return resized

    def _transform(self, make) -> None:
        """Give every layer a new surface made from its old one, as one step of the history.

        The old surfaces are left untouched, so the step keeps them without a copy.
        """

        def change():
            for index, layer in enumerate(self.layers):
                layer.surface = make(index, layer.surface)

        self._change_stack(change, pixels=True)

    def resize(self, width: int, height: int, fill=WHITE) -> None:
        """Grow or crop the canvas, keeping the existing pixels anchored top-left.

        The bottom layer grows with `fill`, the ones above it with nothing.
        """
        width = max(1, min(int(width), MAX_SIZE))
        height = max(1, min(int(height), MAX_SIZE))
        if width == self.width and height == self.height:
            return
        self._transform(
            lambda index, surface: self._resized_surface(
                surface, width, height, fill if index == 0 else TRANSPARENT
            )
        )

    @staticmethod
    def _scaled_surface(surface: cairo.ImageSurface, width: int, height: int) -> cairo.ImageSurface:
        """A whole surface resampled to a new size."""
        scaled = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        cr = cairo.Context(scaled)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.scale(width / surface.get_width(), height / surface.get_height())
        cr.set_source_surface(surface, 0, 0)
        # Smooth when shrinking or enlarging a photo; pixel art enlarged whole
        # numbers of times still comes out crisp, since the samples line up.
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        # Without this the sampling reads past the edge, where there is nothing,
        # and leaves the right and bottom edges faded.
        cr.get_source().set_extend(cairo.EXTEND_PAD)
        cr.paint()
        return scaled

    def scale(self, width: int, height: int) -> None:
        """Stretch or shrink the picture itself, rather than the canvas around it."""
        width = max(1, min(int(width), MAX_SIZE))
        height = max(1, min(int(height), MAX_SIZE))
        if (width, height) == (self.width, self.height):
            return
        self._transform(lambda _index, surface: self._scaled_surface(surface, width, height))

    @staticmethod
    def _rotated_surface(surface: cairo.ImageSurface, clockwise: bool) -> cairo.ImageSurface:
        width, height = surface.get_width(), surface.get_height()
        rotated = new_surface(height, width, TRANSPARENT)
        cr = cairo.Context(rotated)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        if clockwise:
            cr.translate(height, 0)
            cr.rotate(math.pi / 2)
        else:
            cr.translate(0, width)
            cr.rotate(-math.pi / 2)
        cr.set_source_surface(surface, 0, 0)
        cr.paint()
        return rotated

    def rotate(self, clockwise: bool) -> None:
        """Turn the whole canvas a quarter turn, swapping its width and height."""
        self._transform(lambda _index, surface: self._rotated_surface(surface, clockwise))

    @staticmethod
    def _flipped_surface(surface: cairo.ImageSurface, horizontal: bool) -> cairo.ImageSurface:
        width, height = surface.get_width(), surface.get_height()
        flipped = new_surface(width, height, TRANSPARENT)
        cr = cairo.Context(flipped)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        if horizontal:
            cr.translate(width, 0)
            cr.scale(-1, 1)
        else:
            cr.translate(0, height)
            cr.scale(1, -1)
        cr.set_source_surface(surface, 0, 0)
        cr.paint()
        return flipped

    def flip(self, horizontal: bool) -> None:
        """Mirror the whole canvas left-right or top-bottom."""
        self._transform(lambda _index, surface: self._flipped_surface(surface, horizontal))

    def crop_to(
        self, x: int, y: int, width: int, height: int, mask: cairo.ImageSurface | None = None
    ) -> None:
        """Shrink the canvas to one rectangle of itself, discarding the rest.

        With a mask the size of the rectangle, what lies outside the mask goes
        transparent, so cropping to a hand-drawn outline keeps only its inside.
        """

        def crop(_index, surface):
            cropped = crop_surface(surface, x, y, width, height)
            if mask is not None:
                keep_inside(cropped, mask)
            return cropped

        self._transform(crop)

    # Edits to the current layer

    def _fill_rect(
        self, rect: tuple[int, int, int, int], fill, mask: cairo.ImageSurface | None = None
    ) -> None:
        cr = cairo.Context(self.surface)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(*fill)
        if mask is None:
            cr.rectangle(*rect)
            cr.fill()
        else:
            # Only through the mask, laid over the rectangle's corner.
            cr.mask_surface(mask, rect[0], rect[1])

    def erase(
        self,
        rect: tuple[int, int, int, int],
        fill=None,
        mask: cairo.ImageSurface | None = None,
    ) -> None:
        """Empty one rectangle of the current layer, or the masked part of it.

        Emptied, the bottom layer is white, and any other see-through; `fill`
        paints a colour of its own instead.
        """
        self.begin_change()
        self._fill_rect(rect, self._vacated_fill() if fill is None else fill, mask)
        self.commit_change()

    def paste(
        self,
        image: cairo.ImageSurface,
        x: int = 0,
        y: int = 0,
        erase: tuple[int, int, int, int] | None = None,
        erase_mask: cairo.ImageSurface | None = None,
    ) -> bool:
        """Stamp an image onto the current layer, growing the canvas if it runs off the edge.

        The growth, the optional erase of where the pixels came from, and the stamp
        share one undo entry, so a single undo takes back a whole move. Returns
        whether part of the image was cut off because the canvas cannot grow past
        MAX_SIZE.
        """
        x, y = max(0, int(x)), max(0, int(y))
        cut_off = x + image.get_width() > MAX_SIZE or y + image.get_height() > MAX_SIZE
        width = min(max(self.width, x + image.get_width()), MAX_SIZE)
        height = min(max(self.height, y + image.get_height()), MAX_SIZE)

        self.begin_change()
        if (width, height) != (self.width, self.height):
            for index, layer in enumerate(self.layers):
                layer.surface = self._resized_surface(
                    layer.surface, width, height, self._vacated_fill(index)
                )
        if erase is not None:
            # Where a moved selection came from, emptied.
            self._fill_rect(erase, self._vacated_fill(), erase_mask)
        cr = cairo.Context(self.surface)
        cr.set_source_surface(image, x, y)
        cr.paint()
        self.commit_change()
        return cut_off
