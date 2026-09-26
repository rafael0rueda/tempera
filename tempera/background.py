# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Running slow work off the UI thread."""

from __future__ import annotations

import threading
from typing import Callable

from gi.repository import GLib


def run_in_background(
    work: Callable[[], object], done: Callable[[object | GLib.Error], None]
) -> None:
    """Run work off the UI thread and hand what it returns, or the GLib.Error it raises, back to it."""

    def run():
        try:
            result = work()
        except GLib.Error as error:
            result = error
        GLib.idle_add(lambda: (done(result), False)[1])

    threading.Thread(target=run, daemon=True).start()
