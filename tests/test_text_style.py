# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""How text looks: bold, italic, underlined, struck through, aligned, and on a box."""

import pytest
from gi.repository import Adw, Gio, GLib, Pango

from tempera import recent_files, settings, shortcuts
from tempera.canvas import Canvas
from tempera.color import ColorState, rgba
from tempera.document import Document, new_surface
from tempera.text import TextBox, TextStyle, create_layout
from tempera.window import TemperaWindow

from pixels import pixel_at

BLACK = rgba("#000000")
BLUE = rgba("#0000ff")


def ink(surface):
    """How many pixels have anything on them."""
    surface.flush()
    return sum(1 for alpha in surface.get_data()[3::4] if alpha)


def landed(text, style, background=None, font="Sans 20"):
    box = TextBox(10, 10, BLACK, font, style, background)
    box.insert(text)
    return box.landing()


def test_bold_and_italic_change_the_font():
    layout = create_layout("Hi", "Sans 20", TextStyle(bold=True, italic=True))
    description = layout.get_font_description()
    assert description.get_weight() == Pango.Weight.BOLD
    assert description.get_style() == Pango.Style.ITALIC


def test_bold_is_heavier_than_plain():
    plain, _x, _y = landed("Heavy", TextStyle())
    bold, _x, _y = landed("Heavy", TextStyle(bold=True))
    assert ink(bold) > ink(plain)


@pytest.mark.parametrize("style", [TextStyle(underline=True), TextStyle(strikethrough=True)])
def test_a_line_under_or_through_adds_to_the_text(style):
    plain, _x, _y = landed("text", TextStyle())
    lined, _x, _y = landed("text", style)
    assert ink(lined) > ink(plain)


def test_lines_align_against_each_other():
    def first_line_x(align):
        layout = create_layout("a\nmuch longer line", "Sans 20", TextStyle(align=align))
        return layout.index_to_pos(0).x

    assert first_line_x("left") == 0
    assert 0 < first_line_x("center") < first_line_x("right")


def test_a_background_box_fills_behind_the_text():
    surface, _x, _y = landed("Hi", TextStyle(background=True), BLUE)
    # The corner, clear of the glyphs, is the box's colour.
    assert pixel_at(surface, 0, 0) == (0, 0, 255, 255)
    without, _x, _y = landed("Hi", TextStyle(), BLUE)
    assert pixel_at(without, 0, 0)[3] == 0


def test_the_text_lands_whole_even_where_a_slanted_glyph_reaches_past_its_box():
    box = TextBox(10, 10, BLACK, "Serif 40", TextStyle(italic=True))
    box.insert("ff")
    surface, x, y = box.landing()
    width, height = box.size
    # The surface starts at or before the box, and reaches at least as far.
    assert x <= 10 and y <= 10
    assert x + surface.get_width() >= 10 + width
    assert y + surface.get_height() >= 10 + height


def test_nothing_lands_above_or_left_of_the_canvas():
    box = TextBox(0, 0, BLACK, "Serif 40", TextStyle(italic=True))
    box.insert("jf")
    _surface, x, y = box.landing()
    assert x >= 0 and y >= 0


# On the canvas


@pytest.fixture
def canvas():
    colors = ColorState()
    colors.primary = BLACK
    colors.secondary = BLUE
    canvas = Canvas(Document(new_surface(200, 100, (1.0, 1.0, 1.0, 1.0))), colors)
    canvas.select_tool("text")
    return canvas


def test_a_style_chosen_while_typing_shows_on_the_text_at_once(canvas):
    canvas.begin_text(20, 20, BLACK, BLUE)
    canvas._text.insert("Hello")
    plain_width = canvas._text.size[0]
    canvas.text_style = TextStyle(bold=True)
    assert canvas._text.style.bold
    assert canvas._text.size[0] > plain_width


def test_the_text_tool_gives_the_box_the_other_colour(canvas):
    gesture_start = canvas._make_context(1)
    canvas.active_tool.press(gesture_start, 20, 20)
    assert canvas._text.background.equal(BLUE)


def test_a_box_behind_text_lands_with_it(canvas):
    canvas.text_style = TextStyle(background=True)
    canvas.begin_text(20, 20, BLACK, BLUE)
    canvas._text.insert("Hi")
    canvas.commit_text()
    assert pixel_at(canvas.document.surface, 20, 20) == (0, 0, 255, 255)
    assert pixel_at(canvas.document.surface, 10, 10) == (255, 255, 255, 255)


# In the window


@pytest.fixture(scope="module")
def application():
    app = Adw.Application(
        application_id="io.github.rafael0rueda.Tempera.TextStyleTests",
        flags=Gio.ApplicationFlags.NON_UNIQUE,
    )
    app.register(None)
    return app


@pytest.fixture
def window(application, monkeypatch, tmp_path):
    monkeypatch.setattr(recent_files, "_recent_file_path", lambda: tmp_path / "recent-files.txt")
    monkeypatch.setattr(settings, "_settings_path", lambda: tmp_path / "settings.ini")
    window = TemperaWindow(application)
    yield window
    window.destroy()


def test_the_switches_set_the_style(window):
    window.activate_action("win.text-bold", None)
    window.activate_action("win.text-underline", None)
    window.lookup_action("text-align").change_state(GLib.Variant.new_string("center"))
    style = window.canvas.text_style
    assert style.bold and style.underline and not style.italic
    assert style.align == "center"
    window.activate_action("win.text-bold", None)
    assert not window.canvas.text_style.bold


def test_an_unknown_alignment_is_ignored(window):
    window.lookup_action("text-align").change_state(GLib.Variant.new_string("justify"))
    assert window.canvas.text_style.align == "left"


def test_the_style_is_remembered(window, application):
    window.activate_action("win.text-italic", None)
    window.activate_action("win.text-background", None)
    window.lookup_action("text-align").change_state(GLib.Variant.new_string("right"))
    window._save_preferences()
    other = TemperaWindow(application)
    try:
        assert other.canvas.text_style == TextStyle(italic=True, background=True, align="right")
    finally:
        other.destroy()


def test_the_usual_keys_make_text_bold_italic_or_underlined():
    assert shortcuts.keys_for("win.text-bold") == ["<Control>b"]
    assert shortcuts.keys_for("win.text-italic") == ["<Control>i"]
    assert shortcuts.keys_for("win.text-underline") == ["<Control>u"]


def test_the_background_toggle_wears_the_secondary_colour(window):
    window.colors.secondary = rgba("#26a269")
    assert window._background_chip.color.equal(rgba("#26a269"))
