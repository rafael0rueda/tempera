# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from gi.repository import Gdk

from ..i18n import _
from .base import Tool, ToolContext


class PickerTool(Tool):
    id = "picker"
    label = _("Color Picker")
    icon_name = "tempera-color-picker-symbolic"
    tip_icon_name = "tempera-color-picker-tip-symbolic"
    mutates = False

    def press(self, ctx: ToolContext, x, y):
        px, py = int(x), int(y)
        if not (0 <= px < ctx.surface.get_width() and 0 <= py < ctx.surface.get_height()):
            return

        # The colour as it shows, whichever layer it is on.
        if ctx.picture is not None:
            surface, offset = ctx.picture(px, py, 1, 1), 0
        else:
            surface, offset = ctx.surface, py * ctx.surface.get_stride() + px * 4
        surface.flush()
        blue, green, red, alpha = surface.get_data()[offset:offset + 4]

        color = Gdk.RGBA()
        if alpha == 0:
            color.red = color.green = color.blue = 0.0
            color.alpha = 0.0
        else:
            color.red = min(red / alpha, 1.0)
            color.green = min(green / alpha, 1.0)
            color.blue = min(blue / alpha, 1.0)
            color.alpha = alpha / 255
        ctx.pick_color(color, ctx.button)
