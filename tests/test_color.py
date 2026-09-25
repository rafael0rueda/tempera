# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from gi.repository import Gdk

from tempera.color import MAX_RECENT_COLORS, ColorState, rgba


def test_defaults_are_black_on_white():
    colors = ColorState()
    assert (colors.primary.red, colors.primary.green, colors.primary.blue) == (0, 0, 0)
    assert (colors.secondary.red, colors.secondary.green, colors.secondary.blue) == (1, 1, 1)


def test_setting_primary_emits_changed():
    colors = ColorState()
    seen = []
    colors.connect("changed", lambda *_args: seen.append(True))
    colors.primary = rgba("#ff0000")
    assert seen == [True]
    assert colors.primary.red == 1


def test_swap_exchanges_primary_and_secondary():
    colors = ColorState()
    primary, secondary = colors.primary, colors.secondary
    colors.swap()
    assert colors.primary == secondary
    assert colors.secondary == primary


def test_for_button_picks_secondary_only_for_the_secondary_button():
    colors = ColorState()
    assert colors.for_button(Gdk.BUTTON_PRIMARY) == colors.primary
    assert colors.for_button(Gdk.BUTTON_SECONDARY) == colors.secondary


# recently used colors


def test_picking_a_color_does_not_make_it_recent():
    """Only painting with it does; otherwise the palette's own colours crowd in."""
    colors = ColorState()
    colors.primary = rgba("#ff0000")
    colors.secondary = rgba("#00ff00")
    assert colors.recent == []


def test_colours_used_together_go_to_the_front_in_order():
    colors = ColorState()
    colors.remember(rgba("#0000ff"))
    colors.remember(rgba("#ff0000"), rgba("#00ff00"))
    assert [color.to_string() for color in colors.recent] == [
        rgba("#ff0000").to_string(),
        rgba("#00ff00").to_string(),
        rgba("#0000ff").to_string(),
    ]


def test_using_the_same_color_again_moves_it_to_the_front():
    colors = ColorState()
    colors.remember(rgba("#ff0000"))
    colors.remember(rgba("#0000ff"))
    colors.remember(rgba("#ff0000"))
    assert len(colors.recent) == 2
    assert colors.recent[0].to_string() == rgba("#ff0000").to_string()


def test_only_six_colors_are_kept():
    colors = ColorState()
    for step in range(MAX_RECENT_COLORS + 5):
        colors.remember(rgba("#%02x0000" % step))
    assert len(colors.recent) == MAX_RECENT_COLORS == 6


def test_the_palette_has_twenty_different_colours():
    from tempera.color import PALETTE

    specs = [spec for _name, spec in PALETTE]
    assert len(specs) == len(set(specs)) == 20


def test_swapping_does_not_add_to_the_recent_colors():
    colors = ColorState()
    colors.swap()
    assert colors.recent == []
