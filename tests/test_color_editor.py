# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The colour editor, and picking a colour from the screen."""

import pytest
from gi.repository import Adw, Gdk, Gio, GLib

from tempera import color_editor, recent_files, settings
from tempera.color import ColorState, rgba
from tempera.color_editor import MAX_CUSTOM_COLORS, ColorEditor, parse_hex, to_hex
from tempera.screen_color import color_from_results, pick_on, request_path
from tempera.window import TemperaWindow
from tempera.window import window as window_module


def channels(color):
    return tuple(round(value * 255) for value in (color.red, color.green, color.blue, color.alpha))


# Hex


@pytest.mark.parametrize(
    "text, expected",
    [
        ("#ff8000", (255, 128, 0, 255)),
        ("ff8000", (255, 128, 0, 255)),
        ("#f80", (255, 136, 0, 255)),
        ("#ff800080", (255, 128, 0, 128)),
        ("  #FF8000 ", (255, 128, 0, 255)),
    ],
)
def test_hex_values_are_read(text, expected):
    assert channels(parse_hex(text)) == expected


@pytest.mark.parametrize("text", ["", "#12", "#12345", "red", "#gggggg", "#1234567"])
def test_what_is_not_hex_is_refused(text):
    assert parse_hex(text) is None


def test_opacity_shows_in_hex_only_when_there_is_some():
    assert to_hex(rgba("#3584e4")) == "#3584e4"
    assert to_hex(rgba("rgba(53,132,228,0.5)")) == "#3584e480"


# The editor


@pytest.fixture
def colors():
    return ColorState()


@pytest.fixture
def editor(colors):
    return ColorEditor("Primary Colour", rgba("#3584e4"), colors)


def test_it_starts_from_the_colour_it_was_given(editor):
    assert editor.hex.get_text() == "#3584e4"
    assert channels(editor.color) == (53, 132, 228, 255)
    assert editor.opacity.get_value() == 100


def test_a_hex_value_typed_in_is_taken(editor):
    editor.hex.set_text("#c01c28")
    editor.hex.emit("activate")
    assert channels(editor.color) == (192, 28, 40, 255)
    assert round(editor.hue.get_value()) == 356


def test_a_hex_value_that_is_not_one_is_marked(editor):
    editor.hex.set_text("#nope")
    editor.hex.emit("activate")
    assert editor.hex.has_css_class("error")
    assert channels(editor.color) == (53, 132, 228, 255)


def test_the_hue_slider_turns_the_colour(editor):
    editor.set_color(rgba("#ff0000"))
    editor.hue.set_value(120)
    assert channels(editor.color) == (0, 255, 0, 255)
    assert editor.hex.get_text() == "#00ff00"


def test_the_square_sets_strength_and_brightness(editor):
    editor.set_color(rgba("#ff0000"))
    area = editor.area
    area._set(0.0, 1.0)
    assert channels(editor.color) == (255, 255, 255, 255)
    area._set(1.0, 0.5)
    assert channels(editor.color)[:3] == (128, 0, 0)


def test_arrow_keys_move_the_knob(editor):
    editor.set_color(rgba("#ff0000"))
    editor.area._on_key_pressed(None, Gdk.KEY_Left, 0, Gdk.ModifierType(0))
    assert editor.area.saturation == pytest.approx(0.99)
    editor.area._on_key_pressed(None, Gdk.KEY_Down, 0, Gdk.ModifierType.SHIFT_MASK)
    assert editor.area.value == pytest.approx(0.9)


def test_a_grey_keeps_the_hue_already_chosen(editor):
    editor.set_color(rgba("#00ff00"))
    editor.set_color(rgba("#808080"))
    assert round(editor.hue.get_value()) == 120
    # So bringing strength back up returns to green, not red.
    editor.area._set(1.0, 1.0)
    assert channels(editor.color)[:3] == (0, 255, 0)


def test_opacity_is_part_of_the_colour(editor):
    editor.opacity.set_value(50)
    assert channels(editor.color)[3] == 128
    assert editor.hex.get_text().endswith("80")
    assert editor.opacity_value.get_label() == "50%"


def test_select_hands_the_colour_over_and_cancel_does_not(colors):
    chosen = []
    editor = ColorEditor("Primary Colour", rgba("#3584e4"), colors)
    editor.connect("chosen", lambda _editor, color: chosen.append(color.copy()))
    editor.hue.set_value(0)
    editor._select()
    assert chosen and to_hex(chosen[0]) == to_hex(editor.color)

    cancelled = []
    other = ColorEditor("Primary Colour", rgba("#3584e4"), colors)
    other.connect("chosen", lambda *_args: cancelled.append(True))
    other.close()
    assert cancelled == []


def test_colours_can_be_kept_and_let_go(editor, colors):
    editor.keep_color()
    editor.set_color(rgba("#c01c28"))
    editor.keep_color()
    assert [to_hex(color) for color in colors.custom] == ["#c01c28", "#3584e4"]
    # Keeping one again moves it to the front rather than repeating it.
    editor.set_color(rgba("#3584e4"))
    editor.keep_color()
    assert [to_hex(color) for color in colors.custom] == ["#3584e4", "#c01c28"]

    swatch = editor.custom.get_child_at_index(1).get_child()
    editor.set_color(rgba("#000000"))
    swatch.emit("picked", Gdk.BUTTON_PRIMARY)
    assert to_hex(editor.color) == "#c01c28"
    swatch.emit("picked", Gdk.BUTTON_SECONDARY)
    assert [to_hex(color) for color in colors.custom] == ["#3584e4"]


def test_only_so_many_colours_are_kept(editor, colors):
    for index in range(MAX_CUSTOM_COLORS + 3):
        editor.set_color(rgba("#%02x0000" % index))
        editor.keep_color()
    assert len(colors.custom) == MAX_CUSTOM_COLORS
    assert to_hex(colors.custom[0]) == "#120000"


def test_a_colour_off_the_screen_keeps_the_opacity(editor, monkeypatch):
    monkeypatch.setattr(
        color_editor, "pick_screen_color", lambda on_color, on_error: on_color(rgba("#26a269"))
    )
    editor.opacity.set_value(40)
    editor._pick_from_screen()
    assert channels(editor.color) == (38, 162, 105, 102)


def test_a_failed_pick_is_said(colors, monkeypatch):
    messages = []
    editor = ColorEditor("Primary Colour", rgba("#3584e4"), colors, messages.append)
    monkeypatch.setattr(
        color_editor, "pick_screen_color", lambda on_color, on_error: on_error("no portal")
    )
    editor._pick_from_screen()
    assert messages == ["no portal"]


# The portal


class FakeBus:
    """Stands in for the session bus, answering PickColor as the portal would."""

    def __init__(self, answer=None, fails=False):
        self.answer = answer
        self.fails = fails
        self.subscriptions = {}
        self.calls = []

    def get_unique_name(self):
        return ":1.42"

    def signal_subscribe(self, sender, interface, member, path, arg0, flags, callback):
        self.subscriptions[len(self.subscriptions) + 1] = (path, callback)
        return len(self.subscriptions)

    def signal_unsubscribe(self, subscription):
        self.subscriptions.pop(subscription)

    def call(self, name, path, interface, method, parameters, reply_type, flags, timeout, cancellable, callback):
        self.calls.append((interface, method, parameters.unpack()))
        callback(self, "result")

    def call_finish(self, result):
        if self.fails:
            raise GLib.Error("The name is not activatable")
        # The portal answers on the path the token says, some time later.
        (subscription, (path, callback)), = self.subscriptions.items()
        if self.answer is not None:
            callback(self, ":1.2", path, "org.freedesktop.portal.Request", "Response", GLib.Variant("(ua{sv})", self.answer))


def test_the_answer_is_listened_for_where_the_portal_will_give_it():
    assert request_path(FakeBus(), "tempera0a") == "/org/freedesktop/portal/desktop/request/1_42/tempera0a"


def test_a_picked_colour_comes_back():
    bus = FakeBus((0, {"color": GLib.Variant("(ddd)", (1.0, 0.5, 0.0))}))
    picked, errors = [], []
    pick_on(bus, picked.append, errors.append)
    assert channels(picked[0]) == (255, 128, 0, 255)
    assert errors == [] and bus.subscriptions == {}
    interface, method, (parent, options) = bus.calls[0]
    assert (interface, method) == ("org.freedesktop.portal.Screenshot", "PickColor")
    assert options["handle_token"].startswith("tempera")


def test_a_pick_called_off_says_nothing():
    bus = FakeBus((1, {}))
    picked, errors = [], []
    pick_on(bus, picked.append, errors.append)
    assert picked == [] and errors == []


def test_a_pick_that_failed_says_so():
    bus = FakeBus((2, {}))
    picked, errors = [], []
    pick_on(bus, picked.append, errors.append)
    assert picked == [] and len(errors) == 1


def test_no_portal_says_so_and_stops_listening():
    bus = FakeBus(fails=True)
    picked, errors = [], []
    pick_on(bus, picked.append, errors.append)
    assert picked == [] and "not available" in errors[0]
    assert bus.subscriptions == {}


def test_an_answer_without_a_colour_is_not_one():
    assert color_from_results({}) is None
    assert color_from_results({"color": (1.0, 2.0)}) is None
    assert channels(color_from_results({"color": (2.0, -1.0, 0.5)})) == (255, 0, 128, 255)


# In the window


@pytest.fixture(scope="module")
def application():
    app = Adw.Application(
        application_id="io.github.rafael0rueda.Tempera.ColorEditorTests",
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


def test_clicking_a_current_colour_opens_the_editor_for_it(window):
    editor = window._color_bar.choose(primary=False)
    assert isinstance(editor, ColorEditor)
    editor.set_color(rgba("#26a269"))
    editor._select()
    assert to_hex(window.colors.secondary) == "#26a269"


def test_kept_colours_are_remembered(window, application):
    window.colors.custom = [rgba("#26a269"), rgba("rgba(1,2,3,0.5)")]
    window._save_preferences()
    other = TemperaWindow(application)
    try:
        assert [to_hex(color) for color in other.colors.custom] == ["#26a269", "#01020380"]
    finally:
        other.destroy()


def test_the_picker_can_take_a_colour_off_the_screen(window, monkeypatch):
    monkeypatch.setattr(
        window_module, "pick_screen_color", lambda on_color, on_error: on_color(rgba("#e66100"))
    )
    window.lookup_action("tool").change_state(GLib.Variant.new_string("picker"))
    assert window._tool_options.get_visible_child_name() == "picker"
    window.activate_action("win.pick-from-screen", None)
    assert to_hex(window.colors.primary) == "#e66100"
