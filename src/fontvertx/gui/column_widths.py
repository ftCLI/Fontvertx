"""Widths of the fixed columns (Format, Outlines, UPM) of the font list and instance tree.

Widths come from font metrics, never from fixed pixel counts: desktop font scaling (common
on Linux) or a larger system font would otherwise elide the widest values. Each column is
as wide as its widest possible content or its header label with the sort indicator,
whichever is wider. Both views recompute them on font and screen-scale changes.
"""

from PySide6.QtCore import QEvent
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QHeaderView, QWidget

from fontvertx.constants import MAX_UPM
from fontvertx.gui.styles import ITEM_PADDING_LEFT, ITEM_TEXT_MARGIN, chip_font, tabular_font

# Every badge the Format and Outlines columns can show. Collections show their font count,
# "TTC (12)": two digits cover real collections (the chip font is monospaced).
FORMAT_BADGES = ("TTF", "OTF", "WOFF", "WOFF2", "TTC", "OTC", "TTC (00)")
OUTLINE_BADGES = ("TrueType", "PostScript", "Mixed")
# The widest UPM: as many digits as the largest allowed value (tabular figures: all equal).
UPM_SAMPLE = "0" * len(str(MAX_UPM))

# Cell padding from the stylesheet (``::item { padding: 0 12px 0 16px }``) plus the text
# margin Qt adds on both sides of the cell text.
CELL_PADDING_H = ITEM_PADDING_LEFT + 12 + 2 * ITEM_TEXT_MARGIN
# FontBadgeDelegate: the chip text gets 20px less than the cell, the chip 12px more than its
# text. Badges are centered and ignore the cell padding: a small margin keeps them apart.
BADGE_CELL_INSET = 20
BADGE_MARGIN = 8
# Events after which the widths must be measured again (StyleChange: a new stylesheet
# changes paddings and the header font weight).
METRIC_EVENTS = (
    QEvent.Type.FontChange,
    QEvent.Type.DevicePixelRatioChange,
    QEvent.Type.StyleChange,
)


def badge_width(texts: tuple[str, ...]) -> int:
    """Cell width that shows the widest of ``texts`` as a chip without eliding it."""
    metrics = QFontMetrics(chip_font())
    widest = max(metrics.horizontalAdvance(text) for text in texts)
    return widest + BADGE_CELL_INSET + BADGE_MARGIN


def upm_width(view_font: QFont) -> int:
    """Cell width that shows the largest UPM unelided, in the view font or the app font."""
    widest = max(
        QFontMetrics(tabular_font(base)).horizontalAdvance(UPM_SAMPLE) for base in (None, view_font)
    )
    return widest + CELL_PADDING_H


def fixed_column_widths(view: QWidget, header: QHeaderView, columns: dict[str, int]) -> None:
    """Size the ``format``, ``outlines`` and ``upm`` columns (logical indexes) of a view.

    The header part comes from the style itself (``sectionSizeFromContents``): label in
    the header font, stylesheet padding and the sort indicator, reserved even while the
    column is not sorted.
    """
    contents = {
        "format": badge_width(FORMAT_BADGES),
        "outlines": badge_width(OUTLINE_BADGES),
        "upm": upm_width(view.font()),
    }
    for key, column in columns.items():
        if column >= header.count():
            continue
        width = max(contents[key], header.sectionSizeFromContents(column).width())
        header.resizeSection(column, width)
