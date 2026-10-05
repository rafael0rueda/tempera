# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Work off the UI thread always reports back, however it ends."""


from gi.repository import Gio, GLib

from tempera.background import run_in_background

from driving import wait_until


def result_of(work):
    results = []
    run_in_background(work, results.append)
    assert wait_until(lambda: results), "the work never reported back"
    return results[0]


def test_what_the_work_returns_is_handed_back():
    assert result_of(lambda: 42) == 42


def test_a_glib_error_is_handed_back():
    def work():
        raise GLib.Error.new_literal(Gio.io_error_quark(), "no such file", Gio.IOErrorEnum.NOT_FOUND)

    result = result_of(work)
    assert isinstance(result, GLib.Error) and result.message == "no such file"


def test_any_other_error_is_handed_back_too(capsys):
    def work():
        raise ValueError("damaged")

    result = result_of(work)
    assert isinstance(result, GLib.Error) and result.message == "damaged"
    assert "ValueError" in capsys.readouterr().err


def test_an_error_with_nothing_to_say_is_named(capsys):
    def work():
        raise MemoryError

    assert result_of(work).message == "MemoryError"
