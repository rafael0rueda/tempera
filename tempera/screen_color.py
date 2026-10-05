# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Picking a colour from anywhere on the screen, through the desktop's own picker.

Tempera cannot look at other windows itself, least of all inside Flatpak; the
desktop portal can. Asking it shows a crosshair over the whole screen, and it
answers with the colour clicked, or with nothing if the pick was called off.
"""

from __future__ import annotations

import secrets
from typing import Callable

from gi.repository import Gdk, Gio, GLib

from .i18n import _

PORTAL = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENSHOT = "org.freedesktop.portal.Screenshot"
REQUEST = "org.freedesktop.portal.Request"
# What a portal request can come back with.
SUCCESS, CANCELLED = 0, 1


def color_from_results(results: dict) -> Gdk.RGBA | None:
    """The colour in a PickColor answer, as three channels from 0 to 1."""
    picked = results.get("color")
    if not isinstance(picked, tuple) or len(picked) != 3:
        return None
    color = Gdk.RGBA()
    color.red, color.green, color.blue = (max(0.0, min(float(value), 1.0)) for value in picked)
    color.alpha = 1.0
    return color


def request_path(bus: Gio.DBusConnection, token: str) -> str:
    """Where the portal will answer a request made with this token.

    Known before the request is made, so the answer is listened for first
    and cannot slip past.
    """
    sender = bus.get_unique_name().lstrip(":").replace(".", "_")
    return f"{PORTAL_PATH}/request/{sender}/{token}"


def pick_on(
    bus: Gio.DBusConnection,
    on_color: Callable[[Gdk.RGBA], None],
    on_error: Callable[[str], None],
    parent_window: str = "",
) -> None:
    """Ask the portal on a bus for a colour from the screen."""
    token = "tempera" + secrets.token_hex(8)
    subscription = 0

    def on_response(_bus, _sender, _path, _interface, _signal, parameters) -> None:
        bus.signal_unsubscribe(subscription)
        response, results = parameters.unpack()
        if response == CANCELLED:
            return
        color = color_from_results(results) if response == SUCCESS else None
        if color is None:
            on_error(_("The screen color could not be read"))
        else:
            on_color(color)

    subscription = bus.signal_subscribe(
        PORTAL,
        REQUEST,
        "Response",
        request_path(bus, token),
        None,
        Gio.DBusSignalFlags.NONE,
        on_response,
    )

    def on_called(source, result) -> None:
        try:
            source.call_finish(result)
        except GLib.Error as error:
            # No portal, or one without a colour picker: nothing will answer.
            bus.signal_unsubscribe(subscription)
            on_error(_("Picking a color from the screen is not available: {message}").format(
                message=error.message
            ))

    bus.call(
        PORTAL,
        PORTAL_PATH,
        SCREENSHOT,
        "PickColor",
        GLib.Variant("(sa{sv})", (parent_window, {"handle_token": GLib.Variant("s", token)})),
        GLib.VariantType.new("(o)"),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
        on_called,
    )


def pick_screen_color(
    on_color: Callable[[Gdk.RGBA], None], on_error: Callable[[str], None]
) -> None:
    """Let the user click anywhere on the screen, and hand over the colour there."""

    def on_bus(_source, result) -> None:
        try:
            bus = Gio.bus_get_finish(result)
        except GLib.Error as error:
            on_error(error.message)
            return
        pick_on(bus, on_color, on_error)

    Gio.bus_get(Gio.BusType.SESSION, None, on_bus)
