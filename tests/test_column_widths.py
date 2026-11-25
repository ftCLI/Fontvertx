"""Format, Outlines and UPM columns fit their widest content at any font size."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QModelIndex
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QStyle,
    QStyleOptionViewItem,
)

from fontvertx.gui import column_widths
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
        assert header.sectionResizeMode(column) == QHeaderView.ResizeMode.Interactive


def test_file_table_columns_fit_their_content(table: QAbstractItemView) -> None:
    _assert_fits(table)


def test_instance_tree_columns_fit_their_content(tree: InstanceTree) -> None:
    _assert_fits(tree)


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
