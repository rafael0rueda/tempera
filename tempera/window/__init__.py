# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The main window."""

from .image_dialogs import scaled_side
from .layout import PALETTE_BAR_HEIGHT, SIDEBAR_WIDTH
from .window import TemperaWindow

__all__ = ["PALETTE_BAR_HEIGHT", "SIDEBAR_WIDTH", "TemperaWindow", "scaled_side"]
