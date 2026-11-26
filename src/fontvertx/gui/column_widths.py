"""Widths of the fixed columns (Format, Outlines, UPM) of the font list and instance tree.

Widths come from font metrics, never from fixed pixel counts: desktop font scaling (common
on Linux) or a larger system font would otherwise elide the widest values. Each column is
as wide as its widest possible content or its header label with the sort indicator,
whichever is wider. Both views recompute them on font and screen-scale changes.
"""

from collections.abc import Iterable

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QWidget

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
# Resizable columns: the first one (Name / Font / instance), which fills the view, and
# the optional Family and Style of the font list, sized from their content up to a cap.
FIRST_COLUMN_MIN_WIDTH = 120
OPTIONAL_COLUMN_MAX_WIDTH = 200
OPTIONAL_COLUMN_MIN_WIDTH = 60
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


class FillColumnLayout(QObject):
    """Column resizing as in a file manager: the dragged border follows the mouse.

    The *fill* column (the first one: Name, Font / instance) always takes the space left
    in the viewport, down to its minimum. Fixed columns (sized from their content) are
    never resizable by the user. Dragging the border of a resizable column changes it,
    and the first resizable column to its right compensates by the same amount, so the
    header keeps the viewport width: a drag never makes the horizontal scrollbar appear.
    A border with no resizable column to its right is not draggable (``Fixed``).

    ``auto_fit`` columns (column -> maximum width) are sized from their header label and
    longest value when shown and when the model changes, until the user drags them.
    Call :meth:`column_shown` after showing a column and :meth:`relayout` after hiding one.
    """

    def __init__(
        self,
        view: QAbstractItemView,
        header: QHeaderView,
        *,
        fill: int,
        fixed: Iterable[int],
        minimums: dict[int, int],
        default_minimum: int,
        auto_fit: dict[int, int] | None = None,
    ) -> None:
        super().__init__(view)
        self._view = view
        self._header = header
        self._fill = fill
        self._fixed = frozenset(fixed)
        self._minimums = dict(minimums)
        self._default_minimum = default_minimum
        self._auto_fit = dict(auto_fit or {})
        self._user_sized: set[int] = set()
        # True between a mouse press (or double click) on the header and its release:
        # only then is a section resize the user's, and compensated.
        self._pointer = False
        self._busy = False
        self._refit_timer = QTimer(self)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.timeout.connect(self.refit)
        header.setStretchLastSection(False)
        header.sectionResized.connect(self._on_section_resized)
        # Kept, not looked up per event: during teardown the header may already be gone.
        self._header_viewport = header.viewport()
        self._view_viewport = view.viewport()
        self._header_viewport.installEventFilter(self)
        self._view_viewport.installEventFilter(self)
        model = view.model()
        if model is not None and self._auto_fit:
            for signal in (
                model.rowsInserted,
                model.rowsRemoved,
                model.modelReset,
                model.dataChanged,
                model.layoutChanged,
            ):
                signal.connect(self._schedule_refit)
        self.relayout()

    @property
    def fill_column(self) -> int:
        return self._fill

    def minimum(self, column: int) -> int:
        return self._minimums.get(column, self._default_minimum)

    def _visible(self) -> list[int]:
        header = self._header
        return [c for c in range(header.count()) if not header.isSectionHidden(c)]

    def partner(self, column: int) -> int:
        """First visible resizable column right of ``column`` (visual order), or -1."""
        header = self._header
        position = header.visualIndex(column)
        right = [
            c
            for c in self._visible()
            if c not in self._fixed and c != self._fill and header.visualIndex(c) > position
        ]
        return min(right, key=header.visualIndex, default=-1)

    def content_width(self, column: int) -> int:
        """Header label (with sort indicator) or longest value, capped by ``auto_fit``."""
        width = max(self._view.sizeHintForColumn(column), self._header.sectionSizeHint(column))
        width = min(width, self._auto_fit.get(column, width))
        return max(width, self.minimum(column))

    def column_shown(self, column: int) -> None:
        self._user_sized.discard(column)
        if column in self._auto_fit:
            self._resize(column, self.content_width(column))
        self.relayout()

    def refit(self) -> None:
        for column in self._auto_fit:
            if column in self._user_sized or self._header.isSectionHidden(column):
                continue
            self._resize(column, self.content_width(column))
        self.relayout()

    def _schedule_refit(self, *_args: object) -> None:
        self._refit_timer.start(0)

    def _resize(self, column: int, width: int) -> None:
        self._busy = True
        try:
            self._header.resizeSection(column, width)
        finally:
            self._busy = False

    def relayout(self) -> None:
        if self._busy:
            return
        header = self._header
        self._busy = True
        try:
            for column in range(header.count()):
                draggable = column not in self._fixed and self.partner(column) >= 0
                mode = (
                    QHeaderView.ResizeMode.Interactive
                    if draggable
                    else QHeaderView.ResizeMode.Fixed
                )
                if header.sectionResizeMode(column) != mode:
                    header.setSectionResizeMode(column, mode)
            if self._fill >= header.count() or header.isSectionHidden(self._fill):
                return
            others = sum(header.sectionSize(c) for c in self._visible() if c != self._fill)
            available = self._view_viewport.width() - others
            header.resizeSection(self._fill, max(self.minimum(self._fill), available))
        finally:
            self._busy = False

    def _on_section_resized(self, column: int, old: int, new: int) -> None:
        if self._busy or new == 0:
            return
        if self._pointer and column not in self._fixed:
            self._compensate(column, old, new)
        elif column == self._fill:
            return
        self.relayout()

    def _compensate(self, column: int, old: int, new: int) -> None:
        """Keep the total width: the first resizable column to the right absorbs the drag."""
        header = self._header
        target = max(new, self.minimum(column))
        partner = self.partner(column)
        self._busy = True
        try:
            if partner >= 0:
                room = header.sectionSize(partner) - self.minimum(partner)
                target = min(target, old + room)
                header.resizeSection(partner, header.sectionSize(partner) - (target - old))
                self._user_sized.add(partner)
            else:
                target = old
            if target != new:
                header.resizeSection(column, target)
            self._user_sized.add(column)
        finally:
            self._busy = False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if watched is self._header_viewport:
            if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
                self._pointer = True
            elif kind == QEvent.Type.MouseButtonRelease:
                self._pointer = False
        elif kind == QEvent.Type.Resize and watched is self._view_viewport:
            self.relayout()
        return super().eventFilter(watched, event)
