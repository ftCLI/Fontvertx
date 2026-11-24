"""Background and dashed rounded border of the empty drop zone.

Both are painted directly by ``DropZone.paintEvent``; the text and the decorative "Aa"
are ordinary labels on top.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from fontvertx.gui.styles import LIGHT

ZONE_RADIUS = 14
BORDER_WIDTH = 1.5
DASH_PATTERN = (4.0, 3.0)  # in pen widths


def zone_colors(dragging: bool) -> dict[str, QColor]:
    """Background and border colors, at rest or while files are dragged over the zone."""
    if dragging:
        names = {"background": LIGHT.dropzone_bg_active, "border": LIGHT.accent}
    else:
        names = {"background": LIGHT.dropzone_bg, "border": LIGHT.border_strong}
    return {key: QColor(value) for key, value in names.items()}


def zone_outline(width: float, height: float, inset: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(
        QRectF(inset, inset, width - 2 * inset, height - 2 * inset),
        ZONE_RADIUS - inset,
        ZONE_RADIUS - inset,
    )
    return path


def paint_zone_frame(painter: QPainter, width: float, height: float, dragging: bool) -> None:
    """Fill the rounded zone and draw its dashed border (centered on the edge, inset by half a pen)."""
    colors = zone_colors(dragging)
    outline = zone_outline(width, height, BORDER_WIDTH / 2)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillPath(outline, colors["background"])
    pen = QPen(colors["border"], BORDER_WIDTH)
    pen.setDashPattern(list(DASH_PATTERN))
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(outline)
