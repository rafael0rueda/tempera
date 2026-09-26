# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

"""The canvas: shows the document and routes pointer and key input to the tools."""

from .floating import CUT_OFF_MESSAGE, FloatingPaste
from .frame import CanvasFrame
from .view import PIXEL_GRID_ZOOM, ZOOM_MAX, ZOOM_MIN, ZOOM_PRESETS, fit_zoom
from .widget import Canvas

__all__ = [
    "CUT_OFF_MESSAGE",
    "Canvas",
    "CanvasFrame",
    "FloatingPaste",
    "PIXEL_GRID_ZOOM",
    "ZOOM_MAX",
    "ZOOM_MIN",
    "ZOOM_PRESETS",
    "fit_zoom",
]
