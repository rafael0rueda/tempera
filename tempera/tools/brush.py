# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from ..i18n import _
from .base import FreehandTool


class BrushTool(FreehandTool):
    id = "brush"
    label = _("Brush")
    icon_name = "tempera-brush-symbolic"
    tip_icon_name = "tempera-brush-tip-symbolic"
