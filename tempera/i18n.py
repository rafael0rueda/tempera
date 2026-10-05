# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""Translations.

Tempera ships in English only, but every string a person reads goes through
`_()`, so a translation can be added later without touching the code. The
strings are collected into `po/tempera.pot` by `meson compile tempera-pot`.

Strings with something filled in use `.format()` rather than an f-string, so
that the translator sees a whole sentence with named places in it. A string
with a count in it uses `ngettext()`, and a short one that could be taken two
ways `C_()`.
"""

from __future__ import annotations

import gettext
import os

DOMAIN = "tempera"


def locale_dir() -> str | None:
    """Where the catalogues are: the installed prefix, or the system default."""
    return os.environ.get("TEMPERA_LOCALE_DIR") or None


_translation = gettext.translation(DOMAIN, locale_dir(), fallback=True)
_ = _translation.gettext
# For a count: ngettext("{count} page", "{count} pages", count), since other
# languages have more forms than one and many, or share them out differently.
ngettext = _translation.ngettext


def C_(context: str, text: str) -> str:
    """A short string that means different things in different places, such as
    "Fill" the tool and "Fill" the inside of a shape: the context tells a
    translator which, and lets each be translated its own way."""
    return _translation.pgettext(context, text)


__all__ = ["DOMAIN", "locale_dir", "_", "ngettext", "C_"]
