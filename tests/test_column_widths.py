"""Format, Outlines and UPM columns fit their widest content at any font size."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QModelIndex, QPointF, Qt
from PySide6.QtGui import QFont, QFontMetrics, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QStyle,
    QStyleOptionViewItem,
)

from fontvertx.gui import column_widths
from fontvertx.gui import instance_tree as tree_module
from fontvertx.gui.column_widths import (
    BADGE_CELL_INSET,
    CELL_PADDING_H,
    FORMAT_BADGES,
    OUTLINE_BADGES,
)
from fontvertx.gui.file_list import FontFileList
from fontvertx.gui.instance_tree import InstanceTree
from fontvertx.gui.styles import LIGHT, build_stylesheet, chip_font, tabular_font
from fontvertx.gui.widgets import FileTable
from fontvertx.inspection import AxisInfo, FontInfo, NamedInstanceInfo

FORMAT, OUTLINES, UPM = 1, 2, 3
BIG_UPM = 16384


def _info(path: str, upm: int, *, variable: bool = False) -> FontInfo:
    return FontInfo(
        Path(path),
        "WOFF2",
        "PostScript",
        upm,
        variable=variable,
        axes=(AxisInfo("wght", 100, 400, 900),) if variable else (),
        instances=(NamedInstanceInfo("Regular", (("wght", 400),)),) if variable else (),
    )


@pytest.fixture(params=[1.0, 1.5], ids=["default-font", "larger-font"])
def font_scale(qapp: QApplication, request: pytest.FixtureRequest) -> Iterator[float]:
    original = qapp.font()
    font = QFont(original)
    font.setPointSizeF(original.pointSizeF() * request.param)
    qapp.setFont(font)
    yield request.param
    qapp.setFont(original)


def _show(view: QAbstractItemView) -> QHeaderView:
    view.setStyleSheet(build_stylesheet(LIGHT))
    view.resize(900, 300)
    view.show()
    for _ in range(3):
        QApplication.processEvents()
    return view.header() if isinstance(view, InstanceTree) else view.horizontalHeader()


@pytest.fixture
def table(font_scale: float) -> Iterator[QAbstractItemView]:
    files = FontFileList(FileTable(), lambda: (None, False))
    files.add_font(Path("a.woff2"), "a.woff2", _info("a.woff2", BIG_UPM), True)
    yield files.view
    files.shutdown()


@pytest.fixture
def tree(font_scale: float) -> InstanceTree:
    widget = InstanceTree()
    widget.add_font(Path("Var.woff2"), "Var", _info("Var.woff2", BIG_UPM, variable=True))
    return widget


def _upm_index(view: QAbstractItemView) -> QModelIndex:
    model = view.model()
    index = model.index(0, UPM)
    assert index.data() == str(BIG_UPM)
    return index


def _assert_fits(view: QAbstractItemView) -> None:
    header = _show(view)
    # UPM: the cell text rect of the real stylesheet holds 5 digits, so 16384 is not elided.
    index = _upm_index(view)
    option = QStyleOptionViewItem()
    view.itemDelegateForIndex(index).initStyleOption(option, index)
    option.rect = view.visualRect(index)
    option.widget = view
    text_rect = view.style().subElementRect(QStyle.SubElement.SE_ItemViewItemText, option, view)
    digits = QFontMetrics(option.font).horizontalAdvance(str(BIG_UPM))
    assert text_rect.width() >= digits
    sample = QFontMetrics(tabular_font()).horizontalAdvance("00000")
    assert header.sectionSize(UPM) >= sample + CELL_PADDING_H
    # Badges: the delegate elides the chip text to the cell width minus its inset.
    chips = QFontMetrics(chip_font())
    for column, texts in ((FORMAT, FORMAT_BADGES), (OUTLINES, OUTLINE_BADGES)):
        widest = max(chips.horizontalAdvance(text) for text in texts)
        assert header.sectionSize(column) - BADGE_CELL_INSET >= widest
    # Header labels and the sort indicator are never elided.
    for column in (FORMAT, OUTLINES, UPM):
        assert header.sectionSize(column) >= header.sectionSizeFromContents(column).width()
        assert header.sectionResizeMode(column) == QHeaderView.ResizeMode.Fixed


def test_file_table_columns_fit_their_content(table: QAbstractItemView) -> None:
    _assert_fits(table)


def test_instance_tree_columns_fit_their_content(tree: InstanceTree) -> None:
    _assert_fits(tree)


FIXED = QHeaderView.ResizeMode.Fixed
INTERACTIVE = QHeaderView.ResizeMode.Interactive
LONG_NAME = "A-really-long-font-file-name-that-needs-room-Bold-Italic.woff2"


def _modes(header: QHeaderView) -> list[QHeaderView.ResizeMode]:
    return [header.sectionResizeMode(column) for column in range(header.count())]


def _visible_length(header: QHeaderView) -> int:
    return sum(
        header.sectionSize(c) for c in range(header.count()) if not header.isSectionHidden(c)
    )


def _mouse(header: QHeaderView, kind: QEvent.Type, x: int, buttons: bool = True) -> None:
    pos = QPointF(x, header.height() / 2)
    button = Qt.MouseButton.LeftButton
    if kind == QEvent.Type.MouseMove:
        button = Qt.MouseButton.NoButton
    held = Qt.MouseButton.LeftButton if buttons else Qt.MouseButton.NoButton
    if kind == QEvent.Type.MouseButtonRelease:
        held = Qt.MouseButton.NoButton
    event = QMouseEvent(
        kind, pos, header.viewport().mapToGlobal(pos), button, held, Qt.KeyboardModifier.NoModifier
    )
    QApplication.sendEvent(header.viewport(), event)


def _handle(header: QHeaderView, column: int) -> int:
    """Viewport x of the border to the right of ``column``."""
    return header.sectionViewportPosition(column) + header.sectionSize(column) - 1


LONG_FAMILY = "Extraordinarily Condensed Display Family With A Very Long Name"


def _font_row(name: str, *, family: str = "", style: str = "") -> FontInfo:
    info = _info(name, 1000)
    return FontInfo(info.path, info.format, info.outlines, info.upm, family=family, style=style)


@pytest.fixture
def plain_table(qapp: QApplication) -> Iterator[FileTable]:
    files = FontFileList(FileTable(), lambda: (None, False))
    files.add_font(Path(LONG_NAME), LONG_NAME, _font_row(LONG_NAME, style="Bold"), True)
    yield files.view
    files.view.close()
    files.shutdown()


@pytest.fixture
def plain_tree(qapp: QApplication) -> Iterator[InstanceTree]:
    widget = InstanceTree()
    widget.add_font(Path("Var.woff2"), "Var", _info("Var.woff2", 1000, variable=True))
    yield widget
    widget.close()


def _drag(header: QHeaderView, column: int, delta: int) -> None:
    start = _handle(header, column)
    _mouse(header, QEvent.Type.MouseButtonPress, start)
    _mouse(header, QEvent.Type.MouseMove, start + delta)
    _mouse(header, QEvent.Type.MouseButtonRelease, start + delta)


def _fixed_widths(header: QHeaderView) -> list[int]:
    return [header.sectionSize(c) for c in (FORMAT, OUTLINES, UPM)]


def test_name_fills_with_and_without_family_and_style(plain_table: FileTable) -> None:
    header = _show(plain_table)
    layout = plain_table._column_layout
    available = plain_table.header_width()  # the header up to the corner
    fixed = sum(_fixed_widths(header))
    # Only Name and the fixed columns: Name fills, and no border is draggable.
    assert _modes(header)[:4] == [FIXED, FIXED, FIXED, FIXED]
    assert header.sectionSize(0) == available - fixed
    # Family shown: it takes its content width from Name; Name can now be dragged.
    plain_table.setColumnHidden(4, False)
    family = header.sectionSize(4)
    assert family == layout.content_width(4) <= column_widths.OPTIONAL_COLUMN_MAX_WIDTH
    assert header.sectionSize(0) == available - fixed - family
    assert _modes(header)[:5] == [INTERACTIVE, FIXED, FIXED, FIXED, FIXED]
    # Style shown: same, Family becomes draggable (Style compensates), Style does not.
    plain_table.setColumnHidden(5, False)
    style = header.sectionSize(5)
    assert style == layout.content_width(5)
    assert header.sectionSize(4) == family
    assert header.sectionSize(0) == available - fixed - family - style
    assert _modes(header) == [INTERACTIVE, FIXED, FIXED, FIXED, INTERACTIVE, FIXED]
    # Hidden again: the space goes back to Name; UPM is never stretched.
    plain_table.setColumnHidden(4, True)
    assert header.sectionSize(0) == available - fixed - style
    plain_table.setColumnHidden(5, True)
    assert header.sectionSize(0) == available - fixed
    assert header.sectionSize(UPM) == max(
        column_widths.upm_width(plain_table.font()), header.sectionSizeFromContents(UPM).width()
    )


def test_optional_columns_fit_content_up_to_a_maximum(qapp: QApplication) -> None:
    files = FontFileList(FileTable(), lambda: (None, False))
    table = files.view
    try:
        header = _show(table)
        table.setColumnHidden(4, False)
        table.setColumnHidden(5, False)
        # No values: the header label (with the sort indicator) sets the width.
        assert header.sectionSize(4) == max(
            header.sectionSizeHint(4), column_widths.OPTIONAL_COLUMN_MIN_WIDTH
        )
        files.add_font(Path("a.otf"), "a.otf", _font_row("a.otf", family=LONG_FAMILY), True)
        QApplication.processEvents()
        assert header.sectionSize(4) == column_widths.OPTIONAL_COLUMN_MAX_WIDTH
        assert _visible_length(header) == table.header_width()
    finally:
        table.close()
        files.shutdown()


def test_instance_tree_first_column_fills(plain_tree: InstanceTree) -> None:
    header = _show(plain_tree)
    assert _modes(header) == [INTERACTIVE, FIXED, FIXED, FIXED, FIXED]
    location = header.sectionSize(4)
    assert tree_module.LOCATION_MIN_WIDTH <= location <= tree_module.LOCATION_MAX_WIDTH
    assert (
        header.sectionSize(0)
        == plain_tree.viewport().width() - sum(_fixed_widths(header)) - location
    )
    plain_tree.resize(1300, 300)
    QApplication.processEvents()
    assert header.sectionSize(4) == location  # Location keeps its width, Font fills
    assert _visible_length(header) == plain_tree.viewport().width()


def test_borders_without_a_resizable_column_on_the_right_are_not_handles(
    plain_table: FileTable,
) -> None:
    header = _show(plain_table)
    header.viewport().unsetCursor()
    # Only fixed columns right of Name: no border shows the resize cursor.
    for column in (0, FORMAT, OUTLINES, UPM):
        _mouse(header, QEvent.Type.MouseMove, _handle(header, column), buttons=False)
        assert header.viewport().cursor().shape() != Qt.CursorShape.SplitHCursor
    plain_table.setColumnHidden(4, False)
    _mouse(header, QEvent.Type.MouseMove, _handle(header, 0), buttons=False)
    assert header.viewport().cursor().shape() == Qt.CursorShape.SplitHCursor
    header.viewport().unsetCursor()
    _mouse(header, QEvent.Type.MouseMove, _handle(header, 4), buttons=False)  # last: Family
    assert header.viewport().cursor().shape() != Qt.CursorShape.SplitHCursor


def test_dragging_name_border_is_compensated_by_location(plain_tree: InstanceTree) -> None:
    header = _show(plain_tree)
    fixed = _fixed_widths(header)
    name, location = header.sectionSize(0), header.sectionSize(4)
    start = _handle(header, 0)
    _drag(header, 0, -40)
    # The border follows the mouse; Location grows by the same amount, fixed ones shift.
    assert _handle(header, 0) == start - 40
    assert header.sectionSize(0) == name - 40
    assert header.sectionSize(4) == location + 40
    assert _fixed_widths(header) == fixed
    assert _visible_length(header) == plain_tree.viewport().width()
    assert plain_tree.horizontalScrollBar().maximum() == 0


def test_drag_stops_at_the_compensating_column_minimum(plain_tree: InstanceTree) -> None:
    header = _show(plain_tree)
    header.resizeSection(4, tree_module.LOCATION_MIN_WIDTH + 10)
    name = header.sectionSize(0)
    _drag(header, 0, 100)
    assert header.sectionSize(4) == tree_module.LOCATION_MIN_WIDTH
    assert header.sectionSize(0) == name + 10
    assert _visible_length(header) == plain_tree.viewport().width()
    assert plain_tree.horizontalScrollBar().maximum() == 0


def test_drag_stops_at_the_dragged_column_minimum(plain_tree: InstanceTree) -> None:
    header = _show(plain_tree)
    _drag(header, 0, 5 - _handle(header, 0))  # to x=5: Qt ignores moves at negative x
    assert header.sectionSize(0) == column_widths.FIRST_COLUMN_MIN_WIDTH
    assert _visible_length(header) == plain_tree.viewport().width()


def test_dragging_family_border_is_compensated_by_style(plain_table: FileTable) -> None:
    header = _show(plain_table)
    plain_table.setColumnHidden(4, False)
    plain_table.setColumnHidden(5, False)
    name, family, style = (header.sectionSize(c) for c in (0, 4, 5))
    _drag(header, 4, -20)
    assert (header.sectionSize(0), header.sectionSize(4), header.sectionSize(5)) == (
        name,
        family - 20,
        style + 20,
    )
    assert _visible_length(header) == plain_table.header_width()


def test_narrow_window_shrinks_name_to_its_minimum_then_scrolls(
    plain_tree: InstanceTree,
) -> None:
    header = _show(plain_tree)
    plain_tree.resize(400, 300)
    QApplication.processEvents()
    assert header.sectionSize(0) == column_widths.FIRST_COLUMN_MIN_WIDTH
    assert header.sectionSize(4) >= tree_module.LOCATION_MIN_WIDTH
    assert plain_tree.horizontalScrollBar().maximum() > 0


def test_window_resize_changes_only_name(plain_table: FileTable) -> None:
    header = _show(plain_table)
    plain_table.setColumnHidden(4, False)
    before = [header.sectionSize(c) for c in (1, 2, 3, 4)]
    plain_table.resize(1200, 300)
    QApplication.processEvents()
    assert [header.sectionSize(c) for c in (1, 2, 3, 4)] == before
    assert _visible_length(header) == plain_table.header_width()


def test_double_click_on_border_fits_the_column(plain_table: FileTable) -> None:
    header = _show(plain_table)
    plain_table.setColumnHidden(4, False)
    plain_table.setColumnHidden(5, False)
    content = plain_table._column_layout.content_width(4)
    _drag(header, 4, -15)  # narrower: Style (near its minimum) has room to grow
    assert header.sectionSize(4) == content - 15
    fitted: list[int] = []
    header.sectionHandleDoubleClicked.connect(fitted.append)
    x = _handle(header, 4)
    _mouse(header, QEvent.Type.MouseButtonPress, x)
    _mouse(header, QEvent.Type.MouseButtonRelease, x)
    _mouse(header, QEvent.Type.MouseButtonDblClick, x)
    _mouse(header, QEvent.Type.MouseButtonRelease, x)
    assert fitted == [4]
    assert header.sectionSize(4) == content
    assert _visible_length(header) == plain_table.header_width()
    # The last border (Style) is not a handle: double-clicking it does nothing.
    _mouse(header, QEvent.Type.MouseButtonDblClick, _handle(header, 5))
    assert fitted == [4]


def test_columns_grow_when_the_view_font_grows(qapp: QApplication) -> None:
    tree = InstanceTree()
    header = _show(tree)
    before = header.sectionSize(UPM)
    font = QFont(tree.font())
    font.setPointSizeF(font.pointSizeF() * 2)
    tree.setFont(font)
    for _ in range(3):
        QApplication.processEvents()
    assert header.sectionSize(UPM) > before
    assert header.sectionSize(UPM) == max(
        column_widths.upm_width(tree.font()),
        header.sectionSizeFromContents(UPM).width(),
    )
