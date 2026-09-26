# SPDX-FileCopyrightText: 2026 Rafael Rueda
# SPDX-License-Identifier: GPL-3.0-or-later

from tempera.canvas import Canvas
from tempera.selection import Selection
from tempera.color import ColorState
from tempera.document import Document, new_surface

from pixels import paint_pixel, pixel_at

RED = (1.0, 0.0, 0.0, 1.0)
WHITE = (1.0, 1.0, 1.0, 1.0)


def make_canvas(document: Document) -> Canvas:
    return Canvas(document, ColorState())


def test_crop_to_selection_with_nothing_selected_is_a_no_op():
    canvas = make_canvas(Document(new_surface(4, 4, WHITE)))
    assert canvas.crop_to_selection() is False


def test_crop_to_selection_shrinks_the_document_and_clears_the_selection():
    document = Document(new_surface(4, 4, WHITE))
    paint_pixel(document.surface, 2, 1, RED)
    canvas = make_canvas(document)
    canvas.set_selection(Selection(1, 1, 2, 2))

    assert canvas.crop_to_selection() is True
    assert (document.width, document.height) == (2, 2)
    assert pixel_at(document.surface, 1, 0) == (255, 0, 0, 255)
    assert not canvas.has_selection
