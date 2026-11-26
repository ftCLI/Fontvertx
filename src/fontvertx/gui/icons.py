"""Bundled Material Symbols SVG icons, tinted to the palette and sharp at any scale.

Icons are rendered on demand by a QIconEngine at the size *and* device pixel ratio
Qt asks for, so they stay crisp at 100 / 150 / 200% and re-render by themselves
when a window moves to a screen with a different scale.
"""

import logging
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QIconEngine, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from fontvertx.gui.styles import ColorToken, resolve_color

logger = logging.getLogger(__name__)

_ICON_DIR = Path(__file__).parent.parent / "assets" / "icons"
ICON_SIZE = 18

_renderers: dict[Path, QSvgRenderer] = {}
_cache: dict[tuple[str, str, int, int, float], QPixmap] = {}


def clear_cache() -> None:
    """Drop the rendered pixmaps (after a theme switch the old colors are not needed)."""
    _cache.clear()


def _renderer(svg: Path) -> QSvgRenderer:
    renderer = _renderers.get(svg)
    if renderer is None:
        renderer = _renderers[svg] = QSvgRenderer(str(svg))
    return renderer


def render_icon(name: str, color: str, size: QSize, device_pixel_ratio: float) -> QPixmap:
    """Pixmap of icon ``name`` in ``color``: ``size`` logical pixels at the given ratio.

    Cached by (name, color, size, ratio); the pixmap carries the ratio.
    """
    ratio = max(1.0, round(device_pixel_ratio, 2))
    key = (name, color, size.width(), size.height(), ratio)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    pixels = QSize(max(1, round(size.width() * ratio)), max(1, round(size.height() * ratio)))
    image = QImage(pixels, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Square glyph, centered in the requested box.
    side = min(pixels.width(), pixels.height())
    target = QRectF((pixels.width() - side) / 2, (pixels.height() - side) / 2, side, side)
    _renderer(_ICON_DIR / f"{name}.svg").render(painter, target)
    # Tint: keep the alpha channel, replace the fill with the target color.
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(image.rect(), QColor(color))
    painter.end()
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    _cache[key] = pixmap
    return pixmap


class SvgIconEngine(QIconEngine):
    """Renders a tinted SVG for each requested size, mode and device pixel ratio."""

    def __init__(
        self, name: str, color: ColorToken | str, disabled_color: ColorToken | str | None
    ) -> None:
        super().__init__()
        self._name = name
        self._color = color
        self._disabled_color = disabled_color

    def _color_for(self, mode: QIcon.Mode) -> str:
        """Hex color for ``mode``; tokens are resolved now, so a theme switch recolors."""
        if mode is QIcon.Mode.Disabled and self._disabled_color is not None:
            return resolve_color(self._disabled_color)
        return resolve_color(self._color)

    def scaledPixmap(  # noqa: N802 - Qt override
        self, size: QSize, mode: QIcon.Mode, state: QIcon.State, scale: float
    ) -> QPixmap:
        pixmap = render_icon(self._name, self._color_for(mode), size, scale)
        if mode is QIcon.Mode.Disabled and self._disabled_color is None:
            return _greyed(pixmap)
        return pixmap

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return self.scaledPixmap(size, mode, state, 1.0)

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        ratio = painter.device().devicePixelRatioF() if painter.device() else 1.0
        pixmap = self.scaledPixmap(rect.size(), mode, state, ratio)
        painter.drawPixmap(rect, pixmap)

    def actualSize(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QSize:  # noqa: N802
        return size

    def clone(self) -> QIconEngine:
        return SvgIconEngine(self._name, self._color, self._disabled_color)

    def key(self) -> str:
        return "SvgIconEngine"


def _greyed(pixmap: QPixmap) -> QPixmap:
    image = pixmap.toImage()
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.fillRect(image.rect(), QColor(0, 0, 0, 110))
    painter.end()
    result = QPixmap.fromImage(image)
    result.setDevicePixelRatio(pixmap.devicePixelRatio())
    return result


def material_icon(
    name: str,
    color: ColorToken | str,
    size: int = ICON_SIZE,
    disabled_color: ColorToken | str | None = None,
) -> QIcon:
    """Icon for the bundled SVG ``name`` tinted with ``color``.

    ``color`` is a palette token name (``"text_muted"``), resolved each time the icon is
    drawn so it follows a theme switch, or a fixed hex value.

    ``size`` is the logical size the icon is designed for (callers set the matching
    iconSize); any requested size and device pixel ratio is rendered from the SVG.
    ``disabled_color`` tints the icon in its disabled state (Qt would otherwise grey it).
    """
    for value in (color, disabled_color):
        if value is not None:
            resolve_color(value)  # Fail at creation, not at the first paint.
    svg = _ICON_DIR / f"{name}.svg"
    if not svg.is_file():
        logger.warning("Icon not found: %s", svg)
        return QIcon()
    del size  # Rendering is resolution independent; kept for call-site readability.
    return QIcon(SvgIconEngine(name, color, disabled_color))
