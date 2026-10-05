# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from gi.repository import Gdk

from tempera.text import TextBox, font_size, font_without_size, with_font_size


COLOR = Gdk.RGBA()
COLOR.parse("#000000")


def test_insert_backspace_delete():
    box = TextBox(0, 0, COLOR)
    box.insert("hello")
    assert box.text == "hello"
    assert box.caret == 5

    box.move_caret(-1)
    box.delete()
    assert box.text == "hell"
    assert box.caret == 4

    box.backspace()
    assert box.text == "hel"
    assert box.caret == 3


def test_backspace_and_delete_at_the_edges_are_no_ops():
    box = TextBox(0, 0, COLOR)
    box.backspace()
    assert box.text == ""

    box.insert("ab")
    box.caret = len(box.text)
    box.delete()
    assert box.text == "ab"


def test_move_caret_clamps_to_the_text_bounds():
    box = TextBox(0, 0, COLOR)
    box.insert("ab")
    box.move_caret(-10)
    assert box.caret == 0
    box.move_caret(10)
    assert box.caret == 2


def test_move_caret_to_edge():
    box = TextBox(0, 0, COLOR)
    box.insert("hello")
    box.caret = 2
    box.move_caret_to_edge(end=False)
    assert box.caret == 0
    box.move_caret_to_edge(end=True)
    assert box.caret == 5


def test_move_caret_line_up_and_down_across_lines():
    box = TextBox(0, 0, COLOR)
    box.insert("ab\ncd")
    box.caret = 1  # "a|b\ncd"

    box.move_caret_line(1)
    assert box.caret >= 3  # moved onto "cd", past the newline at index 2

    box.move_caret_line(-1)
    box.move_caret_line(-1)  # off the top edge
    assert box.caret == 0


def test_move_caret_line_off_the_bottom_edge_goes_to_the_end():
    box = TextBox(0, 0, COLOR)
    box.insert("ab\ncd")
    box.caret = 4
    box.move_caret_line(1)
    assert box.caret == len(box.text)


def test_byte_and_char_index_round_trip_multibyte_text():
    """Pango indexes in UTF-8 bytes; the caret counts characters — this is the
    conversion the class docstring warns has to happen at the boundary."""
    box = TextBox(0, 0, COLOR)
    box.text = "héllo"  # "héllo" — é is 2 bytes in UTF-8
    box.caret = 2  # after "hé"

    assert box._byte_index() == 3
    assert box._char_index(3) == 2
    assert box._char_index(0) == 0
    assert box._char_index(len(box.text.encode())) == len(box.text)


def test_move_to_never_goes_negative():
    box = TextBox(5, 5, COLOR)
    box.move_to(-10, -10)
    assert (box.x, box.y) == (0, 0)


def test_render_surface_is_none_for_empty_text():
    box = TextBox(0, 0, COLOR)
    assert box.render_surface() is None


def test_render_surface_matches_the_layout_size_for_nonempty_text():
    box = TextBox(0, 0, COLOR)
    box.insert("hi")
    surface = box.render_surface()
    width, height = box.size
    assert surface is not None
    assert (surface.get_width(), surface.get_height()) == (width, height)


def test_font_size_round_trips_through_with_font_size():
    resized = with_font_size("Sans 24", 40)
    assert font_size(resized) == 40


def test_font_without_size_drops_the_size():
    assert "24" not in font_without_size("Sans 24")


# preedit


def test_preedit_shows_at_the_caret_without_joining_the_text():
    box = TextBox(0, 0, COLOR)
    box.insert("ab")
    box.caret = 1
    plain_width, _height = box.size

    box.set_preedit("にほ", 1)

    assert box.text == "ab"
    assert box.layout.get_text() == "aにほb"
    assert box.size[0] > plain_width


def test_the_caret_sits_inside_the_preedit():
    box = TextBox(0, 0, COLOR)
    box.insert("ab")
    box.caret = 1
    box.set_preedit("にほ", 0)
    at_start, _y, _height = box.caret_rect()

    box.set_preedit("にほ", 2)
    at_end, _y, _height = box.caret_rect()

    assert at_end > at_start


def test_clearing_the_preedit_restores_the_layout():
    box = TextBox(0, 0, COLOR)
    box.insert("ab")
    box.set_preedit("にほ", 2)
    box.set_preedit("", 0)
    assert box.layout.get_text() == "ab"


def test_the_preedit_is_not_rendered_into_the_image():
    box = TextBox(0, 0, COLOR)
    box.insert("a")
    without = box.render_surface()

    box.set_preedit("にほんご", 4)
    with_preedit = box.render_surface()

    assert with_preedit.get_width() == without.get_width()


def test_only_a_preedit_renders_nothing():
    box = TextBox(0, 0, COLOR)
    box.set_preedit("にほ", 2)
    assert box.render_surface() is None
