# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from ..i18n import _
from .arrow import ArrowTool
from .base import Tool
from .curve import CurveTool
from .ellipse import EllipseTool
from .line import LineTool
from .polygon import PolygonTool
from .rectangle import RectangleTool
from .rounded_rectangle import RoundedRectangleTool
from .star import StarTool
from .triangle import TriangleTool

# In the order the shape grid shows them, three to a row: lines, then boxes,
# then pointed shapes.
SHAPE_CLASSES = [
    LineTool,
    CurveTool,
    ArrowTool,
    RectangleTool,
    RoundedRectangleTool,
    EllipseTool,
    TriangleTool,
    StarTool,
    PolygonTool,
]
DEFAULT_SHAPE = RectangleTool.id


class ShapesTool(Tool):
    """One tool for every shape; the shape in hand does the drawing."""

    id = "shapes"
    label = _("Shapes")
    icon_name = "tempera-shapes-symbolic"

    def __init__(self):
        self.shapes: dict[str, Tool] = {cls.id: cls() for cls in SHAPE_CLASSES}
        self.shape: Tool = self.shapes[DEFAULT_SHAPE]

    def select(self, shape_id: str) -> None:
        self.shape = self.shapes[shape_id]

    @property
    def fillable(self) -> bool:
        return self.shape.fillable

    def press(self, ctx, x, y):
        self.shape.press(ctx, x, y)

    def motion(self, ctx, x, y):
        self.shape.motion(ctx, x, y)

    def release(self, ctx, x, y):
        self.shape.release(ctx, x, y)

    def draw_preview(self, cr, ctx):
        self.shape.draw_preview(cr, ctx)

    @property
    def in_progress(self) -> bool:
        return self.shape.in_progress

    def hover(self, x, y):
        self.shape.hover(x, y)

    def finish(self, ctx):
        self.shape.finish(ctx)

    def cancel(self):
        self.shape.cancel()

    @property
    def adjustable(self) -> bool:
        return self.shape.adjustable

    def handles(self):
        return self.shape.handles()

    def frame(self):
        return self.shape.frame()

    def bounds(self):
        return self.shape.bounds()

    def contains(self, x, y, reach):
        return self.shape.contains(x, y, reach)

    def grab(self, handle, x, y):
        self.shape.grab(handle, x, y)

    def drag_to(self, x, y, constrain=False):
        self.shape.drag_to(x, y, constrain)

    def move_by(self, dx, dy):
        self.shape.move_by(dx, dy)
