# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from gi.repository import Gdk

from ..i18n import _
from .base import Tool, ToolContext


class PickerTool(Tool):
    id = "picker"
    label = _("Color picker")
    icon_name = "tempera-color-picker-symbolic"
    mutates = False

    def press(self, ctx: ToolContext, x, y):
        surface = ctx.surface
        px, py = int(x), int(y)
        if not (0 <= px < surface.get_width() and 0 <= py < surface.get_height()):
            return

        surface.flush()
        data = surface.get_data()
        offset = py * surface.get_stride() + px * 4
        blue, green, red, alpha = data[offset:offset + 4]

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
