# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

import cairo

from ..i18n import _
from .base import FreehandTool


class PencilTool(FreehandTool):
    id = "pencil"
    label = _("Pencil")
    icon_name = "tempera-pencil-symbolic"
    tip_icon_name = "tempera-pencil-tip-symbolic"
    antialias = False
    line_cap = cairo.LINE_CAP_SQUARE
