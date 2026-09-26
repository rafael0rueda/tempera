# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Copies of unsaved work, kept so that a crash does not lose it.

Each window with unsaved changes keeps one slot in Tempera's data folder: the
image with its layers as an OpenRaster file, a small JSON file describing it,
and a lock file the window holds for as long as it is open. (Tempera 1 kept a
flattened PNG instead, which is still brought back.) Saving, discarding the changes or closing the
window normally deletes the slot. A slot whose lock nobody holds was left by a
Tempera that stopped without closing, and is offered back the next time.

The files are readable only by their owner, and are never written anywhere
the user did not choose except this folder: the image the user opened is only
ever changed by saving it.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import cairo
from gi.repository import GLib

from .document import Document, Layer, copy_surface
from .openraster import read_openraster, write_openraster

# How often a window with unsaved changes keeps a fresh copy, in seconds.
INTERVAL = 30
FORMAT_VERSION = 2
# What a slot's image can be: layers since Tempera 2, a flat picture before.
IMAGE_SUFFIXES = (".ora", ".png")


def recovery_dir() -> Path:
    return Path(GLib.get_user_data_dir()) / "tempera" / "recovery"


def _make_private_dir(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)


def _write_private(path: Path, write) -> None:
    """Write a file only its owner can read, whole or not at all."""
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        write(stream)
    os.replace(temporary, path)


def _remove(directory: Path, slot_id: str, keep_lock: bool = False) -> None:
    for suffix in (*IMAGE_SUFFIXES, ".json"):
        (directory / (slot_id + suffix)).unlink(missing_ok=True)
        (directory / (slot_id + suffix + ".tmp")).unlink(missing_ok=True)
    if not keep_lock:
        (directory / (slot_id + ".lock")).unlink(missing_ok=True)


def _try_lock(path: Path):
    """An open, exclusively locked file, or None if someone else holds the lock."""
    try:
        stream = os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT, 0o600), "r+b")
    except OSError:
        return None
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        return None
    return stream


class RecoverySlot:
    """The copy one window keeps of its unsaved image."""

    def __init__(self, directory: Path | None = None):
        self.directory = directory or recovery_dir()
        self.id = uuid.uuid4().hex
        self._lock = None
        # Bumped by clear(), so a write that finishes afterwards knows its
        # copy is no longer wanted.
        self._generation = 0
        self._writing = False
        # The newest copy asked for while another was being written.
        self._waiting: tuple[list[Layer], dict] | None = None

    @property
    def image_path(self) -> Path:
        return self.directory / (self.id + ".ora")

    @property
    def json_path(self) -> Path:
        return self.directory / (self.id + ".json")

    def _claim(self) -> bool:
        if self._lock is None:
            try:
                _make_private_dir(self.directory)
            except OSError:
                return False
            self._lock = _try_lock(self.directory / (self.id + ".lock"))
        return self._lock is not None

    def save(self, document: Document, info: dict, done=None) -> None:
        """Keep a copy of the image as it is now; the writing happens in the background."""
        if not self._claim():
            return
        # Copied here, so drawing on can carry on while the copy is written.
        layers = [
            Layer(copy_surface(layer.surface), layer.name, layer.visible, layer.opacity)
            for layer in document.layers
        ]
        info = dict(
            info,
            version=FORMAT_VERSION,
            time=time.time(),
            width=document.width,
            height=document.height,
            current=document.current,
        )
        request = (layers, info)
        if self._writing:
            self._waiting = request
            return
        self._start(request, done)

    def _start(self, request, done) -> None:
        self._writing = True
        generation = self._generation
        layers, info = request

        def write() -> None:
            try:
                # The image first: a description on disk means its image is complete.
                _write_private(
                    self.image_path,
                    lambda stream: write_openraster(
                        stream, layers, info["width"], info["height"], complete=False
                    ),
                )
                _write_private(
                    self.json_path, lambda stream: stream.write(json.dumps(info).encode())
                )
            except OSError:
                pass
            GLib.idle_add(finished)

        def finished() -> bool:
            self._writing = False
            if generation != self._generation:
                # Saved, discarded or closed while this was being written; a
                # closed window has let go of its lock file too.
                _remove(self.directory, self.id, keep_lock=self._lock is not None)
            if self._waiting is not None:
                waiting, self._waiting = self._waiting, None
                self._start(waiting, done)
            elif done is not None:
                done()
            return GLib.SOURCE_REMOVE

        threading.Thread(target=write, daemon=True).start()

    def clear(self) -> None:
        """Forget the copy: the image was saved, or its changes thrown away."""
        self._generation += 1
        self._waiting = None
        if self._lock is not None:
            _remove(self.directory, self.id, keep_lock=True)

    def close(self) -> None:
        """The window is closing normally: nothing is left to recover."""
        self.clear()
        if self._lock is not None:
            if not self._writing:
                _remove(self.directory, self.id)
            self._lock.close()
            self._lock = None


@dataclass
class Leftover:
    """Unsaved work left behind by a Tempera that stopped without closing."""

    id: str
    directory: Path
    info: dict
    lock: object

    @property
    def image_path(self) -> Path:
        """The layers, or the flat picture a Tempera before 2 left."""
        for suffix in IMAGE_SUFFIXES:
            path = self.directory / (self.id + suffix)
            if path.exists():
                return path
        return self.directory / (self.id + IMAGE_SUFFIXES[0])

    @property
    def title(self) -> str:
        return str(self.info.get("title") or "Untitled")

    @property
    def uri(self) -> str | None:
        uri = self.info.get("file")
        return uri if isinstance(uri, str) else None

    @property
    def saved_at(self) -> float:
        value = self.info.get("time")
        return float(value) if isinstance(value, (int, float)) else 0.0

    def load(self) -> Document:
        """The image as it was kept. Raises OpenRasterError, cairo.Error or OSError when it cannot be read."""
        path = self.image_path
        if path.suffix == ".png":
            return Document(cairo.ImageSurface.create_from_png(str(path)))
        with open(path, "rb") as stream:
            _width, _height, layers = read_openraster(stream)
        document = Document(layers=layers)
        current = self.info.get("current")
        if isinstance(current, int) and 0 <= current < len(layers):
            document.current = current
        return document

    def discard(self) -> None:
        _remove(self.directory, self.id)
        self.release()

    def release(self) -> None:
        """Leave it for next time, and let another Tempera offer it."""
        if self.lock is not None:
            self.lock.close()
            self.lock = None


def find_leftovers(directory: Path | None = None) -> list[Leftover]:
    """Copies that no open window holds, newest first.

    Each one comes locked, so no other Tempera offers it at the same time;
    discard() or release() lets go of it.
    """
    directory = directory or recovery_dir()
    if not directory.is_dir():
        return []
    leftovers = []
    for description in directory.glob("*.json"):
        slot_id = description.stem
        lock = _try_lock(directory / (slot_id + ".lock"))
        if lock is None:
            continue  # a window that is still open
        try:
            info = json.loads(description.read_text(encoding="utf-8"))
            if not isinstance(info, dict) or not any(
                (directory / (slot_id + suffix)).is_file() for suffix in IMAGE_SUFFIXES
            ):
                raise ValueError("incomplete")
        except (OSError, ValueError):
            # Nothing that can be brought back.
            lock.close()
            _remove(directory, slot_id)
            continue
        leftovers.append(Leftover(slot_id, directory, info, lock))
    # Stray images a crash left before their description was written.
    for suffix in IMAGE_SUFFIXES:
        for image in directory.glob("*" + suffix):
            if not (directory / (image.stem + ".json")).exists():
                lock = _try_lock(directory / (image.stem + ".lock"))
                if lock is not None:
                    lock.close()
                    _remove(directory, image.stem)
    # Locks of windows that never kept a copy before the crash.
    for lock_path in directory.glob("*.lock"):
        stem = lock_path.stem
        if any((directory / (stem + suffix)).exists() for suffix in (".json", *IMAGE_SUFFIXES)):
            continue
        lock = _try_lock(lock_path)
        if lock is not None:
            lock.close()
            _remove(directory, stem)
    leftovers.sort(key=lambda leftover: leftover.saved_at, reverse=True)
    return leftovers
