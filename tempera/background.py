# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Running slow work off the UI thread."""

from __future__ import annotations

import sys
import threading
import traceback
from typing import Callable

from gi.repository import Gio, GLib


def run_in_background(
    work: Callable[[], object], done: Callable[[object | GLib.Error], None]
) -> None:
    """Run work off the UI thread and hand what it returns, or the GLib.Error it raises, back to it.

    `done` is always called: whoever waits on it has usually marked something
    as busy until then. Anything else the work raises is a bug, or the machine
    running out of memory, and comes back as a GLib.Error too.
    """

    def run():
        try:
            result = work()
        except GLib.Error as error:
            result = error
        except Exception as error:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            result = GLib.Error.new_literal(
                Gio.io_error_quark(), str(error) or type(error).__name__, Gio.IOErrorEnum.FAILED
            )
        GLib.idle_add(lambda: (done(result), False)[1])

    threading.Thread(target=run, daemon=True).start()
