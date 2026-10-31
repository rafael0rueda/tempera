# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Writing JPEG XL, when native/tempera_jxl.c has been built.

GdkPixbuf reads the format, so opening needs nothing from here, but it cannot
write it. Without this helper, saving as JPEG XL is simply not offered. Built
and installed, the launcher says where it is; `build-aux/build_native.sh` puts
one next to this file for the source tree, if it finds libjxl to build against.

The call lets go of Python's lock while it runs, so the window stays free while
a worker thread encodes.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

from gi.repository import GdkPixbuf

# Named in the environment by the launcher; "off" does without it.
ENVIRONMENT = "TEMPERA_JXL"
LIBRARY_NAME = "tempera_jxl.so"
# What tempera_jxl_version() in the C says of the calls below; one built from
# other source is left alone.
VERSION = 1


def _load() -> ctypes.CDLL | None:
    named = os.environ.get(ENVIRONMENT, "")
    if named == "off":
        return None
    for path in (named, str(Path(__file__).resolve().parent / LIBRARY_NAME)):
        if not path or not os.path.isfile(path):
            continue
        try:
            library = ctypes.CDLL(path)
            library.tempera_jxl_version.restype = ctypes.c_int
            library.tempera_jxl_version.argtypes = ()
            if library.tempera_jxl_version() != VERSION:
                continue
            bytes_out = ctypes.POINTER(ctypes.c_ubyte)
            number = ctypes.c_int
            library.tempera_jxl_encode.restype = number
            library.tempera_jxl_encode.argtypes = (
                ctypes.c_char_p, number, number, number,
                ctypes.POINTER(bytes_out), ctypes.POINTER(ctypes.c_size_t),
            )  # fmt: skip
            library.tempera_jxl_free.restype = None
            library.tempera_jxl_free.argtypes = (bytes_out,)
        except (OSError, AttributeError):
            # Built for another machine, against a libjxl that is not here, or
            # from source too old to say its version.
            continue
        return library
    return None


# The helper, or None when there is none: then JPEG XL is not offered for saving.
library = _load()


def available() -> bool:
    return library is not None


def encode(pixbuf: GdkPixbuf.Pixbuf, quality: int) -> bytes | None:
    """A picture as a JPEG XL file, or None when it could not be encoded.

    The pixbuf has to have an alpha channel, as one made from a surface does:
    its rows are then exactly four bytes a pixel, with nothing between them.
    A `quality` of 100 keeps every pixel exactly.
    """
    encoded = ctypes.POINTER(ctypes.c_ubyte)()
    size = ctypes.c_size_t()
    failed = library.tempera_jxl_encode(
        pixbuf.read_pixel_bytes().get_data(), pixbuf.get_width(), pixbuf.get_height(), quality,
        ctypes.byref(encoded), ctypes.byref(size),
    )  # fmt: skip
    if failed:
        return None
    try:
        return ctypes.string_at(encoded, size.value)
    finally:
        library.tempera_jxl_free(encoded)
