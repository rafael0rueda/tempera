# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from ..i18n import _
from ..selection import Selection
from .base import Tool

TOLERANCE = 32


class MagicWandTool(Tool):
    """Selects the pixels joined to the one clicked through colours near enough its own.

    It looks at the current layer only, the way the fill does.
    """

    id = "wand"
    label = _("Magic Wand")
    icon_name = "tempera-select-wand-symbolic"
    # Picking a region changes nothing in the image; moving or deleting it later does.
    mutates = False
    # A region across a big image takes a moment to find, so the search runs
    # off the UI thread; what it found becomes the selection on release.
    background = True

    def __init__(self):
        self._found: Selection | None = None
        self._searched = False

    def press(self, ctx, x, y):
        self._found = Selection.from_color(ctx.surface, x, y, ctx.tolerance)
        self._searched = True

    def release(self, ctx, x, y):
        if self._searched and ctx.select_pixels is not None:
            ctx.select_pixels(self._found)
        self._found = None
        self._searched = False
