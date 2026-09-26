# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from dataclasses import dataclass

import cairo
from gi.repository import Gdk, Pango, PangoCairo

DEFAULT_FONT = "Sans 24"
# What the size slider offers for text: small enough for a caption, large enough
# for a title across the canvas.
FONT_SIZE_RANGE = (6, 200)

# The pixels that end up in the image must not depend on the desktop's text
# scaling, so every layout Tempera lays out comes from a font map pinned at the
# usual 96 dpi rather than from the screen's.
_FONT_MAP = PangoCairo.FontMap.new()
_FONT_MAP.set_resolution(96)


def font_size(font: str) -> int:
    """The point size of a font description, as the size slider counts it."""
    return max(1, round(Pango.FontDescription(font).get_size() / Pango.SCALE))


def with_font_size(font: str, size: int) -> str:
    description = Pango.FontDescription(font)
    description.set_size(size * Pango.SCALE)
    return description.to_string()


def font_without_size(font: str) -> str:
    """Just the typeface, since the size is shown on the slider instead."""
    description = Pango.FontDescription(font)
    description.unset_fields(Pango.FontMask.SIZE)
    return description.to_string()


ALIGNMENTS = {
    "left": Pango.Alignment.LEFT,
    "center": Pango.Alignment.CENTER,
    "right": Pango.Alignment.RIGHT,
}


@dataclass(frozen=True)
class TextStyle:
    """How the text of a box looks, all of it alike, as in Paint."""

    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikethrough: bool = False
    # How the lines of several sit against one another: "left", "center" or "right".
    align: str = "left"
    # A box behind the text, filled in the colour opposite the text's.
    background: bool = False


PLAIN = TextStyle()
# The parts of a style that are on or off.
TEXT_SWITCHES = ("bold", "italic", "underline", "strikethrough", "background")


def create_layout(
    text: str, font: str, style: TextStyle = PLAIN, preedit: tuple[int, int] | None = None
) -> Pango.Layout:
    """A layout of the text in a style; `preedit` is a (start, end) byte range an input
    method is still composing, shown underlined."""
    layout = Pango.Layout.new(_FONT_MAP.create_context())
    description = Pango.FontDescription(font)
    if style.bold:
        description.set_weight(Pango.Weight.BOLD)
    if style.italic:
        description.set_style(Pango.Style.ITALIC)
    layout.set_font_description(description)
    layout.set_alignment(ALIGNMENTS.get(style.align, Pango.Alignment.LEFT))
    layout.set_text(text, -1)
    attributes = Pango.AttrList()
    # Without a range, an attribute covers all of the text.
    if style.underline:
        attributes.insert(Pango.attr_underline_new(Pango.Underline.SINGLE))
    if style.strikethrough:
        attributes.insert(Pango.attr_strikethrough_new(True))
    if preedit is not None:
        # Doubled when the text is underlined anyway, so it still stands out.
        attribute = Pango.attr_underline_new(
            Pango.Underline.DOUBLE if style.underline else Pango.Underline.SINGLE
        )
        attribute.start_index, attribute.end_index = preedit
        attributes.insert(attribute)
    layout.set_attributes(attributes)
    return layout


class TextBox:
    """Text being typed over the canvas, before it is rasterised into the image.

    Pango indexes text in UTF-8 bytes while the caret here counts characters, so
    the two are converted at the boundary rather than mixed up in the editing.

    The preedit is what an input method is still composing. It shows, underlined,
    at the caret, but is not part of the text until the input method commits it.
    The input method holds on to the keys while it composes, so the editing and
    caret methods below only ever run with no preedit showing.
    """

    def __init__(
        self,
        x: float,
        y: float,
        color: Gdk.RGBA,
        font: str = DEFAULT_FONT,
        style: TextStyle = PLAIN,
        background: Gdk.RGBA | None = None,
    ):
        self._text = ""
        self._preedit = ""
        self._preedit_cursor = 0
        self._font = font
        self._style = style
        self._layout: Pango.Layout | None = None
        self.color = color
        # What the box behind the text is filled with, when the style asks for one.
        self.background = background
        self._caret = 0
        self.x = 0.0
        self.y = 0.0
        self.move_to(x, y)

    @property
    def text(self) -> str:
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        self._text = value
        self._layout = None

    @property
    def font(self) -> str:
        return self._font

    @font.setter
    def font(self, value: str) -> None:
        self._font = value
        self._layout = None

    @property
    def style(self) -> TextStyle:
        return self._style

    @style.setter
    def style(self, value: TextStyle) -> None:
        self._style = value
        self._layout = None

    @property
    def caret(self) -> int:
        return self._caret

    @caret.setter
    def caret(self, value: int) -> None:
        self._caret = value
        if self._preedit:
            # The preedit sits at the caret, so the layout moves with it.
            self._layout = None

    @property
    def preedit(self) -> str:
        return self._preedit

    def set_preedit(self, preedit: str, cursor: int) -> None:
        """Show an input method's unfinished text, with its own cursor counted in characters."""
        self._preedit = preedit
        self._preedit_cursor = max(0, min(cursor, len(preedit)))
        self._layout = None

    @property
    def layout(self) -> Pango.Layout:
        """The text as shown, with any preedit in place at the caret."""
        if self._layout is None:
            before, after = self._text[: self.caret], self._text[self.caret:]
            start = len(before.encode())
            preedit = (start, start + len(self._preedit.encode())) if self._preedit else None
            self._layout = create_layout(before + self._preedit + after, self._font, self._style, preedit)
        return self._layout

    @property
    def size(self) -> tuple[int, int]:
        width, height = self.layout.get_pixel_size()
        return width, height

    def move_to(self, x: float, y: float) -> None:
        # Never past the top-left, for the same reason a paste cannot go there:
        # the canvas only ever grows right and down.
        self.x = max(0.0, x)
        self.y = max(0.0, y)

    def contains(self, x: float, y: float, padding: float = 0.0) -> bool:
        width, height = self.size
        return (
            self.x - padding <= x <= self.x + width + padding
            and self.y - padding <= y <= self.y + height + padding
        )

    # Editing

    def insert(self, text: str) -> None:
        self.text = self._text[: self.caret] + text + self._text[self.caret:]
        self.caret += len(text)

    def backspace(self) -> None:
        if self.caret == 0:
            return
        self.text = self._text[: self.caret - 1] + self._text[self.caret:]
        self.caret -= 1

    def delete(self) -> None:
        if self.caret >= len(self._text):
            return
        self.text = self._text[: self.caret] + self._text[self.caret + 1:]

    def move_caret(self, delta: int) -> None:
        self.caret = max(0, min(self.caret + delta, len(self._text)))

    def move_caret_line(self, delta: int) -> None:
        """Up or down a line, keeping roughly the same horizontal position."""
        layout = self.layout
        line_number, x_pos = layout.index_to_line_x(self._byte_index(), False)
        target = line_number + delta
        if not 0 <= target < layout.get_line_count():
            # Off the top or bottom: go where a text box usually goes.
            self.caret = 0 if delta < 0 else len(self._text)
            return
        _inside, index, trailing = layout.get_line_readonly(target).x_to_index(x_pos)
        self.caret = self._char_index(index, trailing)

    def move_caret_to_edge(self, end: bool) -> None:
        line = self._line()
        self.caret = self._char_index(line.start_index + (line.length if end else 0))

    def caret_at(self, x: float, y: float) -> None:
        """Put the caret nearest to a point in canvas coordinates."""
        _inside, index, trailing = self.layout.xy_to_index(
            round((x - self.x) * Pango.SCALE), round((y - self.y) * Pango.SCALE)
        )
        self.caret = self._char_index(index, trailing)

    def caret_rect(self) -> tuple[float, float, float]:
        """Where to draw the caret, in canvas coordinates: inside the preedit while there is one."""
        index = len((self._text[: self.caret] + self._preedit[: self._preedit_cursor]).encode())
        strong, _weak = self.layout.get_cursor_pos(index)
        return (
            self.x + strong.x / Pango.SCALE,
            self.y + strong.y / Pango.SCALE,
            strong.height / Pango.SCALE,
        )

    def _line(self) -> Pango.LayoutLine:
        line_number, _x = self.layout.index_to_line_x(self._byte_index(), False)
        return self.layout.get_line_readonly(line_number)

    def _byte_index(self) -> int:
        return len(self._text[: self.caret].encode())

    def _char_index(self, byte_index: int, trailing: int = 0) -> int:
        prefix = self._text.encode()[:byte_index].decode("utf-8", "ignore")
        return max(0, min(len(prefix) + trailing, len(self._text)))

    # Drawing

    def _paint(self, cr: cairo.Context, layout: Pango.Layout, x: float, y: float) -> None:
        """The box behind, if there is one, then the text, with its top-left at (x, y)."""
        cr.save()
        if self._style.background and self.background is not None:
            width, height = layout.get_pixel_size()
            color = self.background
            cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
            cr.rectangle(x, y, width, height)
            cr.fill()
        cr.move_to(x, y)
        cr.set_source_rgba(self.color.red, self.color.green, self.color.blue, self.color.alpha)
        PangoCairo.show_layout(cr, layout)
        cr.restore()

    def render(self, cr: cairo.Context) -> None:
        self._paint(cr, self.layout, self.x, self.y)

    def landing(self) -> tuple[cairo.ImageSurface, int, int] | None:
        """The typed text on its own surface, ready to be stamped down, and where its
        top-left corner goes; None when nothing has been typed.

        It takes in everything the glyphs cover, which a slanted one can reach
        past the box laid out for it. Any preedit is left out: it has not been
        typed yet.
        """
        if not self._text:
            return None
        layout = create_layout(self._text, self._font, self._style)
        ink, logical = layout.get_pixel_extents()
        left, top = min(ink.x, logical.x), min(ink.y, logical.y)
        right = max(ink.x + ink.width, logical.x + logical.width)
        bottom = max(ink.y + ink.height, logical.y + logical.height)
        x, y = round(self.x), round(self.y)
        # Whatever would fall above or left of the canvas is lost: it only
        # grows right and down.
        left, top = max(left, -x), max(top, -y)
        if right <= left or bottom <= top:
            return None
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, right - left, bottom - top)
        self._paint(cairo.Context(surface), layout, -left, -top)
        return surface, x + left, y + top

    def render_surface(self) -> cairo.ImageSurface | None:
        """The typed text on its own surface, as landing() lays it out."""
        landing = self.landing()
        return None if landing is None else landing[0]
