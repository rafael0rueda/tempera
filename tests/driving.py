# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Driving the canvas and the main loop from tests, with no pointer and no screen."""

import time

from gi.repository import Gdk, GLib

NO_KEYS = Gdk.ModifierType(0)


class FakeGesture:
    """What the canvas asks of a drag gesture: the button held, and the keys held with it."""

    def __init__(self, button=Gdk.BUTTON_PRIMARY, state=NO_KEYS):
        self.button = button
        self.state = state

    def get_current_button(self):
        return self.button

    def get_current_event_state(self):
        return self.state


def drag(canvas, start, end, state=NO_KEYS, button=Gdk.BUTTON_PRIMARY) -> None:
    """Press at one point of the canvas, move to another and let go."""
    gesture = FakeGesture(button, state)
    offset = (end[0] - start[0], end[1] - start[1])
    canvas._on_drag_begin(gesture, *start)
    canvas._on_drag_update(gesture, *offset)
    canvas._on_drag_end(gesture, *offset)


def wait_until(condition, seconds: float = 5.0) -> bool:
    """Keep the main loop turning until a condition holds, as for work a thread
    hands back; False if it never does."""
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    # Wakes the loop now and then, so it waits for GTK instead of spinning.
    tick = GLib.timeout_add(10, lambda: GLib.SOURCE_CONTINUE)
    try:
        while not condition():
            if time.monotonic() > deadline:
                return False
            context.iteration(True)
        return True
    finally:
        GLib.source_remove(tick)
