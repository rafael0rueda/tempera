# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from .airbrush import DEFAULT_DENSITY, DENSITY_RANGE, AirbrushTool
from .base import Tool, ToolContext, draw_marquee
from .brush import BrushTool
from .eraser import EraserTool
from .fill import TOLERANCE as DEFAULT_TOLERANCE, FillTool
from .lasso import LassoTool
from .pencil import PencilTool
from .picker import PickerTool
from .select import SelectTool
from .shapes import DEFAULT_SHAPE, SHAPE_CLASSES, ShapesTool
from .text import TextTool
from .wand import TOLERANCE as DEFAULT_WAND_TOLERANCE, MagicWandTool

TOOL_CLASSES = [
    PencilTool,
    BrushTool,
    AirbrushTool,
    EraserTool,
    ShapesTool,
    TextTool,
    FillTool,
    PickerTool,
    SelectTool,
    LassoTool,
    MagicWandTool,
]

# The sidebar has one button for the two ways of drawing a selection, which
# takes up whichever was used last; the options bar picks between them.
SELECTION_SHAPE_IDS = [SelectTool.id, LassoTool.id]
SIDEBAR_TOOL_CLASSES = [cls for cls in TOOL_CLASSES if cls is not LassoTool]

SHAPES_TOOL_ID = ShapesTool.id
AIRBRUSH_TOOL_ID = AirbrushTool.id
SHAPE_IDS = [cls.id for cls in SHAPE_CLASSES]
ERASER_TOOL_ID = EraserTool.id
FILL_TOOL_ID = FillTool.id
TEXT_TOOL_ID = TextTool.id
SELECT_TOOL_ID = SelectTool.id
WAND_TOOL_ID = MagicWandTool.id
# The tools that pick out part of the image, and can grab it to move it.
SELECTION_TOOL_IDS = {SelectTool.id, LassoTool.id, MagicWandTool.id}


def create_tools() -> dict[str, Tool]:
    return {cls.id: cls() for cls in TOOL_CLASSES}


__all__ = [
    "Tool",
    "ToolContext",
    "draw_marquee",
    "TOOL_CLASSES",
    "SHAPE_CLASSES",
    "SHAPE_IDS",
    "DEFAULT_SHAPE",
    "SHAPES_TOOL_ID",
    "AIRBRUSH_TOOL_ID",
    "DEFAULT_DENSITY",
    "DENSITY_RANGE",
    "ERASER_TOOL_ID",
    "FILL_TOOL_ID",
    "DEFAULT_TOLERANCE",
    "TEXT_TOOL_ID",
    "SELECT_TOOL_ID",
    "SELECTION_TOOL_IDS",
    "SELECTION_SHAPE_IDS",
    "SIDEBAR_TOOL_CLASSES",
    "WAND_TOOL_ID",
    "DEFAULT_WAND_TOLERANCE",
    "create_tools",
]
