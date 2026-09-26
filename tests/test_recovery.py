# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import stat
import time

import pytest
from gi.repository import Adw, Gio, GLib

from tempera import recent_files, recovery, settings
from tempera.document import Document, new_surface
from tempera.main import TemperaApplication
from tempera.window import TemperaWindow

from pixels import paint_pixel, pixel_at

RED = (1.0, 0.0, 0.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)


def wait_for(condition, seconds: float = 5.0) -> bool:
    context = GLib.MainContext.default()
    deadline = time.monotonic() + seconds
    tick = GLib.timeout_add(10, lambda: GLib.SOURCE_CONTINUE)
    try:
        while not condition():
            if time.monotonic() > deadline:
                return False
            context.iteration(True)
        return True
    finally:
        GLib.source_remove(tick)


def save_and_wait(slot, image, info=None):
    """Keep a copy of a document, or of a picture as a document of one layer."""
    document = image if isinstance(image, Document) else Document(image)
    written = []
    slot.save(document, info or {"title": "Test.png", "file": None}, lambda: written.append(True))
    assert wait_for(lambda: written)


def crash(slot):
    """What a crash leaves: the files, with nobody holding the lock any more."""
    slot._lock.close()
    slot._lock = None


def files(directory):
    return sorted(path.name for path in directory.iterdir()) if directory.exists() else []


# A window's slot


def test_a_copy_is_kept_privately(private_recovery_dir):
    slot = recovery.RecoverySlot()
    surface = new_surface(3, 3, RED)
    save_and_wait(slot, surface)

    assert slot.image_path.is_file() and slot.json_path.is_file()
    assert stat.S_IMODE(private_recovery_dir.stat().st_mode) == 0o700
    for path in (slot.image_path, slot.json_path, private_recovery_dir / (slot.id + ".lock")):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    info = json.loads(slot.json_path.read_text())
    assert info["title"] == "Test.png" and info["version"] == recovery.FORMAT_VERSION
    slot.close()


def test_nothing_is_written_until_there_is_something_to_keep(private_recovery_dir):
    slot = recovery.RecoverySlot()
    slot.clear()
    slot.close()
    assert files(private_recovery_dir) == []


def test_an_open_window_s_copy_is_not_offered(private_recovery_dir):
    slot = recovery.RecoverySlot()
    save_and_wait(slot, new_surface(2, 2, RED))
    assert recovery.find_leftovers() == []
    slot.close()


def test_clearing_and_closing_leave_nothing_behind(private_recovery_dir):
    slot = recovery.RecoverySlot()
    save_and_wait(slot, new_surface(2, 2, RED))
    slot.clear()
    assert files(private_recovery_dir) == [slot.id + ".lock"]
    slot.close()
    assert files(private_recovery_dir) == []


def test_a_copy_cleared_while_being_written_is_removed_when_the_write_ends(private_recovery_dir):
    slot = recovery.RecoverySlot()
    written = []
    slot.save(Document(new_surface(200, 200, RED)), {"title": "T"}, lambda: written.append(True))
    slot.clear()
    assert wait_for(lambda: written)
    assert not slot.image_path.exists() and not slot.json_path.exists()
    slot.close()


def test_a_window_closed_while_writing_leaves_nothing(private_recovery_dir):
    slot = recovery.RecoverySlot()
    slot.save(Document(new_surface(200, 200, RED)), {"title": "T"})
    slot.close()
    assert wait_for(lambda: files(private_recovery_dir) == [])


# After a crash


def test_a_crashed_window_s_copy_comes_back(private_recovery_dir):
    slot = recovery.RecoverySlot()
    surface = new_surface(4, 4, WHITE)
    paint_pixel(surface, 1, 2, RED)
    save_and_wait(slot, surface, {"title": "cat.png", "file": "file:///tmp/cat.png"})
    crash(slot)

    [leftover] = recovery.find_leftovers()
    assert leftover.title == "cat.png"
    assert leftover.uri == "file:///tmp/cat.png"
    assert leftover.saved_at > 0
    loaded = leftover.load()
    assert pixel_at(loaded.surface, 1, 2) == (255, 0, 0, 255)

    # Held while it is being offered, so another Tempera does not offer it too.
    assert recovery.find_leftovers() == []
    leftover.discard()
    assert files(private_recovery_dir) == []


def test_the_layers_come_back_as_they_were(private_recovery_dir):
    document = Document(new_surface(4, 4, WHITE))
    document.add_layer()
    paint_pixel(document.surface, 1, 1, RED)
    document.rename_layer(1, "Ink")
    document.set_layer_opacity(1, 0.5)
    document.add_layer()
    document.set_layer_visible(2, False)
    document.select_layer(1)
    slot = recovery.RecoverySlot()
    save_and_wait(slot, document)
    crash(slot)

    [leftover] = recovery.find_leftovers()
    loaded = leftover.load()
    assert [layer.name for layer in loaded.layers] == ["Background", "Ink", "Layer 3"]
    assert [layer.visible for layer in loaded.layers] == [True, True, False]
    assert loaded.layers[1].opacity == 0.5
    assert loaded.current == 1
    assert pixel_at(loaded.layers[1].surface, 1, 1) == (255, 0, 0, 255)
    assert pixel_at(loaded.layers[1].surface, 2, 2)[3] == 0
    leftover.discard()


def test_a_copy_tempera_1_left_comes_back_too(private_recovery_dir):
    # A picture as a PNG, before there were layers.
    private_recovery_dir.mkdir(parents=True)
    surface = new_surface(3, 3, WHITE)
    paint_pixel(surface, 1, 1, RED)
    surface.write_to_png(str(private_recovery_dir / "old.png"))
    (private_recovery_dir / "old.json").write_text(
        json.dumps({"title": "old.png", "file": None, "version": 1, "time": 1.0})
    )

    [leftover] = recovery.find_leftovers()
    loaded = leftover.load()
    assert len(loaded.layers) == 1
    assert pixel_at(loaded.surface, 1, 1) == (255, 0, 0, 255)
    leftover.discard()
    assert files(private_recovery_dir) == []


def test_deciding_later_offers_it_again_next_time(private_recovery_dir):
    slot = recovery.RecoverySlot()
    save_and_wait(slot, new_surface(2, 2, RED))
    crash(slot)
    [leftover] = recovery.find_leftovers()
    leftover.release()
    assert len(recovery.find_leftovers()) == 1


def test_the_newest_copy_is_offered_first(private_recovery_dir):
    older, newer = recovery.RecoverySlot(), recovery.RecoverySlot()
    save_and_wait(older, new_surface(2, 2, RED), {"title": "older"})
    save_and_wait(newer, new_surface(2, 2, RED), {"title": "newer"})
    info = json.loads(older.json_path.read_text())
    info["time"] -= 100
    older.json_path.write_text(json.dumps(info))
    crash(older)
    crash(newer)
    assert [leftover.title for leftover in recovery.find_leftovers()] == ["newer", "older"]


def test_broken_or_half_written_leftovers_are_cleaned_up(private_recovery_dir):
    private_recovery_dir.mkdir()
    (private_recovery_dir / "broken.json").write_text("not json")
    (private_recovery_dir / "broken.png").write_bytes(b"")
    (private_recovery_dir / "noimage.json").write_text("{}")
    (private_recovery_dir / "nodescription.png").write_bytes(b"")
    (private_recovery_dir / "nodescription2.ora").write_bytes(b"")
    (private_recovery_dir / "onlylock.lock").write_bytes(b"")
    assert recovery.find_leftovers() == []
    assert files(private_recovery_dir) == []


def test_no_folder_means_nothing_to_offer():
    assert recovery.find_leftovers() == []


# The window keeping its copy


@pytest.fixture(scope="module")
def application():
    app = TemperaApplication()
    app.set_application_id("io.github.rafael0rueda.Tempera.RecoveryTests")
    app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    app.register(None)
    return app


@pytest.fixture
def window(application, monkeypatch, tmp_path):
    monkeypatch.setattr(recent_files, "_recent_file_path", lambda: tmp_path / "recent-files.txt")
    monkeypatch.setattr(settings, "_settings_path", lambda: tmp_path / "settings.ini")
    window = TemperaWindow(application)
    yield window
    window.destroy()


def draw(window):
    document = window.canvas.document
    document.begin_change()
    paint_pixel(document.surface, 0, 0, RED)
    document.commit_change()


def kept(window) -> bool:
    return window._recovery.json_path.exists()


def test_an_untouched_image_keeps_no_copy(window, private_recovery_dir):
    window._keep_recovery_copy()
    assert files(private_recovery_dir) == []


def test_unsaved_changes_are_kept_and_only_again_after_more_changes(window, monkeypatch):
    draw(window)
    window._keep_recovery_copy()
    assert wait_for(lambda: kept(window))

    saves = []
    monkeypatch.setattr(window._recovery, "save", lambda *args: saves.append(args))
    window._keep_recovery_copy()
    assert saves == []
    draw(window)
    window._keep_recovery_copy()
    assert len(saves) == 1


def test_saving_or_undoing_back_forgets_the_copy(window):
    draw(window)
    window._keep_recovery_copy()
    assert wait_for(lambda: kept(window))
    window.canvas.document.undo()
    assert not kept(window)


def test_closing_the_window_leaves_nothing(window, private_recovery_dir):
    window.present()
    draw(window)
    window._keep_recovery_copy()
    assert wait_for(lambda: kept(window))
    # What choosing Discard does.
    window._closing = True
    window.close()
    assert wait_for(lambda: files(private_recovery_dir) == [])
    assert window._recovery_timer == 0


def test_closing_an_unchanged_window_ends_its_timer(window):
    window.present()
    window.close()
    assert window._recovery_timer == 0


# Bringing it back


def leftover_of(surface, info):
    slot = recovery.RecoverySlot()
    save_and_wait(slot, surface, info)
    crash(slot)
    leftovers = recovery.find_leftovers()
    [leftover] = [each for each in leftovers if each.id == slot.id]
    for other in leftovers:
        if other is not leftover:
            other.release()
    return leftover


def test_recovering_into_a_blank_window_reopens_the_file_as_unsaved(application, window):
    surface = new_surface(5, 5, WHITE)
    paint_pixel(surface, 2, 2, RED)
    leftover = leftover_of(surface, {"title": "cat.png", "file": "file:///tmp/cat.png"})

    target = application._recover(window, leftover)

    assert target is window
    document = window.canvas.document
    assert document.modified
    assert document.file.get_uri() == "file:///tmp/cat.png"
    assert pixel_at(document.surface, 2, 2) == (255, 0, 0, 255)
    # The old copy is gone, and the window keeps one of its own at once.
    assert not leftover.image_path.exists()
    assert wait_for(lambda: kept(window))


def test_a_window_already_in_use_is_left_alone(application, window):
    draw(window)
    leftover = leftover_of(new_surface(5, 5, RED), {"title": "Untitled", "file": None})
    target = application._recover(window, leftover)
    try:
        assert target is not window
        assert target.canvas.document.file is None
        assert target.canvas.document.modified
    finally:
        target.destroy()


def test_a_copy_that_cannot_be_read_is_kept_for_later(application, window):
    leftover = leftover_of(new_surface(2, 2, RED), {"title": "x"})
    leftover.image_path.write_bytes(b"not a png")
    toasts = []
    window.show_toast = toasts.append

    assert application._recover(window, leftover) is window
    assert toasts and "x" in toasts[0]
    assert leftover.image_path.exists()
    assert len(recovery.find_leftovers()) == 1


def test_each_leftover_is_asked_about_in_turn(application, window):
    first = leftover_of(new_surface(2, 2, RED), {"title": "first"})
    first.release()
    second = leftover_of(new_surface(2, 2, RED), {"title": "second"})
    second.release()
    window.present()

    application._offer_next(window, recovery.find_leftovers())
    dialog = window.get_visible_dialog()
    assert isinstance(dialog, Adw.AlertDialog)
    dialog.emit("response", "discard")
    dialog = window.get_visible_dialog()
    assert isinstance(dialog, Adw.AlertDialog)
    dialog.emit("response", "later")
    # One thrown away, one kept for next time.
    assert len(recovery.find_leftovers()) == 1
