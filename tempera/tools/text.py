# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from ..i18n import _
from .base import Tool, ToolContext


class TextTool(Tool):
    id = "text"
    sized = True
    label = _("Text")
    icon_name = "tempera-text-symbolic"
    # Typing is what changes the image, and that happens long after the click,
    # so the canvas takes it from here and commits the text itself.
    mutates = False

    def press(self, ctx: ToolContext, x, y):
        ctx.begin_text(x, y, ctx.color)
