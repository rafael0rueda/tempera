# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import ctypes
import math

import cairo
from gi.repository import Gdk, GdkPixbuf, GObject

MAX_UNDO = 50
# An undo step keeps only the rectangle the edit changed, but a fill or a
# rotation changes all of it, so the history is also capped by memory: 50 whole
# steps of the largest canvas would take 12.8 GB. The newest step is always
# kept, whatever its size.
UNDO_BUDGET = 1024 * 1024 * 1024
DEFAULT_WIDTH = 800
DEFAULT_HEIGHT = 600
MAX_SIZE = 8192

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


class Patch:
    """One step of the history: the pixels to put back to get the image as it was.

    Usually a rectangle of the same-sized image; for an edit that changed the
    canvas size it is the whole image, which then replaces the surface. An edit
    that changed nothing has no pixels at all.
    """

    __slots__ = ("x", "y", "pixels", "whole")

    def __init__(self, x: int, y: int, pixels: cairo.ImageSurface | None, whole: bool = False):
        self.x, self.y, self.pixels, self.whole = x, y, pixels, whole

    @property
    def nbytes(self) -> int:
        return surface_bytes(self.pixels) if self.pixels is not None else 0

    @property
    def rect(self) -> tuple[int, int, int, int] | None:
        """The part of the image it covers, or None for the whole of it."""
        if self.whole:
            return None
        if self.pixels is None:
            return (self.x, self.y, 0, 0)
        return (self.x, self.y, self.pixels.get_width(), self.pixels.get_height())

    def apply(self, surface: cairo.ImageSurface) -> tuple[cairo.ImageSurface, Patch]:
        """Put the pixels back; returns the resulting surface and the patch that reverses it."""
        if self.whole:
            return self.pixels, Patch(0, 0, surface, whole=True)
        if self.pixels is None:
            return surface, Patch(0, 0, None)
        width, height = self.pixels.get_width(), self.pixels.get_height()
        reverse = Patch(self.x, self.y, crop_surface(surface, self.x, self.y, width, height))
        cr = cairo.Context(surface)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_surface(self.pixels, self.x, self.y)
        cr.rectangle(self.x, self.y, width, height)
        cr.fill()
        return surface, reverse


def patch_between(before: cairo.ImageSurface, after: cairo.ImageSurface) -> Patch | None:
    """What it takes to turn `after` back into `before`, or None if they are the same."""
    if (before.get_width(), before.get_height()) != (after.get_width(), after.get_height()):
        return Patch(0, 0, before, whole=True)
    rect = changed_rect(before, after)
    if rect is None:
        return None
    return Patch(rect[0], rect[1], crop_surface(before, *rect))


class Document(GObject.Object):
    """The painted image plus its undo history."""

    __gsignals__ = {
        "content-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "state-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, surface: cairo.ImageSurface | None = None):
        super().__init__()
        self.surface = surface or new_surface(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        self.file = None
        self._undo: list[Patch] = []
        self._redo: list[Patch] = []
        # How many undo steps deep the saved image sits, so undoing back to it
        # counts as unmodified. None once no undo or redo can reach it again.
        self._saved_depth: int | None = 0
        # The image as it was when begin_change() was called, until the change
        # is committed and only the part it altered is kept.
        self._before: cairo.ImageSurface | None = None
        # The part of the image the last change touched, as (x, y, width,
        # height), or None when it may be anywhere: a view redraws only that.
        self.damage: tuple[int, int, int, int] | None = None

    @property
    def width(self) -> int:
        return self.surface.get_width()

    @property
    def height(self) -> int:
        return self.surface.get_height()

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

    def begin_change(self) -> None:
        """Snapshot the surface so the coming edit can be undone."""
        self._before = copy_surface(self.surface)

    def _record(self, patch: Patch) -> None:
        self._undo.append(patch)
        if self._redo and self._saved_depth is not None and self._saved_depth >= len(self._undo):
            # The saved image was among the redo steps about to be dropped.
            self._saved_depth = None
        self._redo = []
        self._trim_history()

    def _changed(self, damage: tuple[int, int, int, int] | None) -> None:
        """Tell the views the image changed, and where."""
        self.damage = damage
        self.emit("content-changed")
        self.emit("state-changed")

    def commit_change(self) -> None:
        """Keep the change begun earlier as one undo step, even if it altered nothing."""
        if self._before is None:
            self._changed(None)
            return
        before, self._before = self._before, None
        patch = patch_between(before, self.surface) or Patch(0, 0, None)
        self._record(patch)
        self._changed(patch.rect)

    def _trim_history(self) -> None:
        """Drop the oldest undo steps past MAX_UNDO or UNDO_BUDGET, keeping the newest."""
        kept = len(self._undo)
        total = sum(patch.nbytes for patch in self._undo)
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

    def finish_change(self) -> None:
        """Commit the change begun earlier, unless the image came out identical.

        A fill in the colour already there, or a stroke off the canvas, then
        leaves no undo step behind and does not mark the image as modified.
        """
        if self._before is None:
            self.commit_change()
            return
        before, self._before = self._before, None
        patch = patch_between(before, self.surface)
        if patch is None:
            return
        self._record(patch)
        self._changed(patch.rect)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> None:
        # Not in the middle of a stroke: the step it would take back is not
        # finished, and taking an older one back would tangle the two.
        if not self._undo or self._before is not None:
            return
        patch = self._undo.pop()
        self.surface, reverse = patch.apply(self.surface)
        self._redo.append(reverse)
        self._changed(patch.rect)

    def redo(self) -> None:
        if not self._redo or self._before is not None:
            return
        patch = self._redo.pop()
        self.surface, reverse = patch.apply(self.surface)
        self._undo.append(reverse)
        self._trim_history()
        self._changed(patch.rect)

    def _replace_surface(self, surface: cairo.ImageSurface) -> None:
        """Swap in a new image as one undo step, keeping the old one whole.

        For the edits that build a new surface rather than draw on this one:
        the old surface is left untouched, so it needs no copy.
        """
        self._record(Patch(0, 0, self.surface, whole=True))
        self.surface = surface
        self._changed(None)

    def _resized_surface(
        self, width: int, height: int, fill=(1.0, 1.0, 1.0, 1.0)
    ) -> cairo.ImageSurface:
        """The current image on a differently sized canvas, anchored top-left."""
        surface = new_surface(width, height, fill)
        cr = cairo.Context(surface)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_surface(self.surface, 0, 0)
        cr.rectangle(0, 0, min(width, self.width), min(height, self.height))
        cr.fill()
        return surface

    def resize(self, width: int, height: int, fill=(1.0, 1.0, 1.0, 1.0)) -> None:
        """Grow or crop the canvas, keeping the existing pixels anchored top-left."""
        width = max(1, min(int(width), MAX_SIZE))
        height = max(1, min(int(height), MAX_SIZE))
        if width == self.width and height == self.height:
            return

        self._replace_surface(self._resized_surface(width, height, fill))

    def _scaled_surface(self, width: int, height: int) -> cairo.ImageSurface:
        """The whole image resampled to a new size."""
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        cr = cairo.Context(surface)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.scale(width / self.width, height / self.height)
        cr.set_source_surface(self.surface, 0, 0)
        # Smooth when shrinking or enlarging a photo; pixel art enlarged whole
        # numbers of times still comes out crisp, since the samples line up.
        cr.get_source().set_filter(cairo.FILTER_GOOD)
        # Without this the sampling reads past the edge, where there is nothing,
        # and leaves the right and bottom edges faded.
        cr.get_source().set_extend(cairo.EXTEND_PAD)
        cr.paint()
        return surface

    def scale(self, width: int, height: int) -> None:
        """Stretch or shrink the picture itself, rather than the canvas around it."""
        width = max(1, min(int(width), MAX_SIZE))
        height = max(1, min(int(height), MAX_SIZE))
        if (width, height) == (self.width, self.height):
            return

        self._replace_surface(self._scaled_surface(width, height))

    def _rotated_surface(self, clockwise: bool) -> cairo.ImageSurface:
        surface = new_surface(self.height, self.width, (0.0, 0.0, 0.0, 0.0))
        cr = cairo.Context(surface)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        if clockwise:
            cr.translate(self.height, 0)
            cr.rotate(math.pi / 2)
        else:
            cr.translate(0, self.width)
            cr.rotate(-math.pi / 2)
        cr.set_source_surface(self.surface, 0, 0)
        cr.paint()
        return surface

    def rotate(self, clockwise: bool) -> None:
        """Turn the whole canvas a quarter turn, swapping its width and height."""
        self._replace_surface(self._rotated_surface(clockwise))

    def _flipped_surface(self, horizontal: bool) -> cairo.ImageSurface:
        surface = new_surface(self.width, self.height, (0.0, 0.0, 0.0, 0.0))
        cr = cairo.Context(surface)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        if horizontal:
            cr.translate(self.width, 0)
            cr.scale(-1, 1)
        else:
            cr.translate(0, self.height)
            cr.scale(1, -1)
        cr.set_source_surface(self.surface, 0, 0)
        cr.paint()
        return surface

    def flip(self, horizontal: bool) -> None:
        """Mirror the whole canvas left-right or top-bottom."""
        self._replace_surface(self._flipped_surface(horizontal))

    def crop_to(
        self, x: int, y: int, width: int, height: int, mask: cairo.ImageSurface | None = None
    ) -> None:
        """Shrink the canvas to one rectangle of itself, discarding the rest.

        With a mask the size of the rectangle, what lies outside the mask goes
        transparent, so cropping to a hand-drawn outline keeps only its inside.
        """
        surface = crop_surface(self.surface, x, y, width, height)
        if mask is not None:
            keep_inside(surface, mask)
        self._replace_surface(surface)

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
        fill=(1.0, 1.0, 1.0, 1.0),
        mask: cairo.ImageSurface | None = None,
    ) -> None:
        """Paint one rectangle, or the masked part of it, with the colour the canvas is made of."""
        self.begin_change()
        self._fill_rect(rect, fill, mask)
        self.commit_change()

    def paste(
        self,
        image: cairo.ImageSurface,
        x: int = 0,
        y: int = 0,
        erase: tuple[int, int, int, int] | None = None,
        erase_mask: cairo.ImageSurface | None = None,
    ) -> bool:
        """Stamp an image onto the canvas, growing it if the image runs off the edge.

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
            self.surface = self._resized_surface(width, height)
        if erase is not None:
            # Where a moved selection came from, left the same white a bigger
            # canvas is made of.
            self._fill_rect(erase, (1.0, 1.0, 1.0, 1.0), erase_mask)
        cr = cairo.Context(self.surface)
        cr.set_source_surface(image, x, y)
        cr.paint()
        self.commit_change()
        return cut_off

    def to_pixbuf(self) -> GdkPixbuf.Pixbuf:
        self.surface.flush()
        return Gdk.pixbuf_get_from_surface(self.surface, 0, 0, self.width, self.height)
