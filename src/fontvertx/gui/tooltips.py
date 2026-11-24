"""Themed tooltips: dark square box in the UI font, shown with a calmer timing.

The theme is applied twice: by the application stylesheet (``QToolTip`` rule) and by the
``QToolTip`` palette and font, so tooltips that bypass the stylesheet match too. Corners
stay square on purpose (rounded tooltip windows leave artifacts on Windows).

Tooltips stay plain text, which Qt never wraps: it measures and places them as they are.
Long texts go through ``wrap_tip()``, which breaks them at ``TOOLTIP_WRAP_WIDTH`` pixels
in advance; short texts stay on one line.
"""

import re
from collections.abc import Callable

from PySide6.QtGui import QColor, QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QToolTip

from fontvertx.gui.styles import LIGHT, ui_font

TOOLTIP_FONT_PIXELS = 12
TOOLTIP_WRAP_WIDTH = 400  # pixels of text, padding excluded
# Tooltips wait a while before appearing, and stop chaining soon after one hides.
TOOLTIP_WAKE_UP_MS = 1200
TOOLTIP_FALL_ASLEEP_MS = 300
# A word wider than the limit (typically a path) breaks after one of these, kept at line end.
_PIECE = re.compile(r"[^\\/_-]*[\\/_-]|[^\\/_-]+")
# A line that is a path (D:\..., \\server\..., /..., ~/..., ./...): its folder names may
# contain spaces, so it wraps after separators first, never in the middle of a name.
_PATH_START = re.compile(r"([A-Za-z]:)?[\\/]|~[\\/]|\.{1,2}[\\/]")


class TooltipTimingStyle(QProxyStyle):
    """Wraps the application style to slow tooltips down; everything else is unchanged."""

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return TOOLTIP_WAKE_UP_MS
        if hint == QStyle.StyleHint.SH_ToolTip_FallAsleepDelay:
            return TOOLTIP_FALL_ASLEEP_MS
        return super().styleHint(hint, option, widget, returnData)


def tooltip_font() -> QFont:
    font = ui_font()
    font.setPixelSize(TOOLTIP_FONT_PIXELS)
    font.setWeight(QFont.Weight.Medium)
    return font


def tooltip_palette() -> QPalette:
    palette = QPalette(QToolTip.palette())
    background, text = QColor(LIGHT.tooltip_bg), QColor(LIGHT.tooltip_text)
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        palette.setColor(group, QPalette.ColorRole.ToolTipBase, background)
        palette.setColor(group, QPalette.ColorRole.ToolTipText, text)
        palette.setColor(group, QPalette.ColorRole.Window, background)
        palette.setColor(group, QPalette.ColorRole.WindowText, text)
    return palette


def wrap_tip(text: str) -> str:
    """Plain tooltip text broken into lines of at most ``TOOLTIP_WRAP_WIDTH`` pixels.

    Existing line breaks are kept. Lines wrap at spaces; a word wider than the limit breaks
    after ``\\``, ``/``, ``_`` or ``-``, and only as a last resort between characters. A
    line that is a path breaks after those separators first, then at spaces.
    """
    width = QFontMetrics(tooltip_font()).horizontalAdvance
    return "\n".join("\n".join(_wrap_line(line, width)) for line in text.split("\n"))


def _wrap_line(line: str, width: Callable[[str], int], *, paths: bool = True) -> list[str]:
    if width(line) <= TOOLTIP_WRAP_WIDTH:
        return [line]
    if paths and _PATH_START.match(line):
        # A folder name wider than the limit falls back to spaces, then characters.
        return _break_word(line, width, lambda piece: _wrap_line(piece, width, paths=False))
    lines: list[str] = []
    current = ""
    for word in line.split(" "):
        candidate = f"{current} {word}" if current else word
        if width(candidate) <= TOOLTIP_WRAP_WIDTH:
            current = candidate
            continue
        if current:
            lines.append(current)
        if width(word) <= TOOLTIP_WRAP_WIDTH:
            current = word
            continue
        pieces = _break_word(word, width, lambda piece: _break_chars(piece, width))
        lines.extend(pieces[:-1])
        current = pieces[-1]
    lines.append(current)
    return lines


def _break_word(
    word: str, width: Callable[[str], int], too_wide: Callable[[str], list[str]]
) -> list[str]:
    """Split text wider than the limit after separators; ``too_wide`` splits a lone piece."""
    pieces: list[str] = []
    current = ""
    for piece in _PIECE.findall(word):
        if width(current + piece) <= TOOLTIP_WRAP_WIDTH:
            current += piece
            continue
        if current:
            pieces.append(current)
        current = piece
        if width(piece) > TOOLTIP_WRAP_WIDTH:
            *done, current = too_wide(piece)
            pieces.extend(done)
    pieces.append(current)
    return pieces


def _break_chars(text: str, width: Callable[[str], int]) -> list[str]:
    """Last resort, for text with no separator: break between characters."""
    pieces: list[str] = []
    current = ""
    for char in text:
        if current and width(current + char) > TOOLTIP_WRAP_WIDTH:
            pieces.append(current)
            current = ""
        current += char
    pieces.append(current)
    return pieces


def install_tooltip_theme(app: QApplication) -> None:
    """Apply the tooltip palette and font (idempotent)."""
    QToolTip.setPalette(tooltip_palette())
    QToolTip.setFont(tooltip_font())
