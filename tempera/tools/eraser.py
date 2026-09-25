# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import cairo
from gi.repository import Gdk

from ..i18n import _
from .base import FreehandTool, ToolContext


TRANSPARENT = Gdk.RGBA()
TRANSPARENT.parse("rgba(0,0,0,0)")


class EraserTool(FreehandTool):
    id = "eraser"
    label = _("Eraser")
    icon_name = "tempera-eraser-symbolic"
    antialias = False
    line_cap = cairo.LINE_CAP_SQUARE

    def colors_used(self, ctx: ToolContext):
        # Rubbing out is not painting with the background colour.
        return ()

    def stroke_color(self, ctx: ToolContext):
        # Like Paint, the eraser lays down the background (secondary) color,
        # unless it has been asked to rub back to nothing at all.
        return TRANSPARENT if ctx.erase_to_transparency else ctx.secondary
