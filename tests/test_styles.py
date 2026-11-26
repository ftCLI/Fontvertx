from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QImage, QPalette, QStandardItemModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStyleOptionViewItem,
    QWidget,
)

from fontvertx.gui import styles
from fontvertx.gui import widgets as widgets_module
from fontvertx.gui import window as window_module
from fontvertx.gui.file_list import FontFileList, FontRowDelegate
from fontvertx.gui.instance_tree import InstanceTree
from fontvertx.gui.status_pill import StatusState
from fontvertx.gui.styles import DARK, LIGHT, Palette, build_stylesheet
from fontvertx.gui.widgets import FileTable
from fontvertx.gui.window import ConverterWindow
from fontvertx.inspection import FontInfo, NamedInstanceInfo

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
INDICATOR_MARKS = ("check", "dash", "dot")


@pytest.fixture
def icon_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "icons"
    monkeypatch.setattr(styles, "_icon_directory", lambda: directory)
    return directory


PALETTES = pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])


@PALETTES
def test_palette_values_are_hex_colors(palette: Palette) -> None:
    for name, value in vars(palette).items():
        assert HEX.match(value), f"{name}={value}"


def _contrast(foreground: str, background: str) -> float:
    def luminance(value: str) -> float:
        color = QColor(value)
        components = (color.redF(), color.greenF(), color.blueF())
        linear = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in components)
        return sum(
            weight * component
            for weight, component in zip((0.2126, 0.7152, 0.0722), linear, strict=True)
        )

    values = sorted((luminance(foreground), luminance(background)))
    return (values[1] + 0.05) / (values[0] + 0.05)


def test_hint_text_contrast_on_page_and_cards() -> None:
    for foreground in (LIGHT.text_muted, LIGHT.text_secondary, LIGHT.success, LIGHT.primary):
        for background in (LIGHT.page, LIGHT.surface, LIGHT.disabled_bg):
            assert _contrast(foreground, background) >= 4.5
    for background in (LIGHT.surface, LIGHT.page, LIGHT.accent_tint, LIGHT.field):
        assert _contrast(LIGHT.text_muted, background) >= 4.5


@PALETTES
def test_text_contrast_on_every_background(palette: Palette) -> None:
    for name in (
        "page",
        "surface",
        "field",
        "field_hover",
        "accent_tint",
        "table_header",
        "disabled_bg",
    ):
        ratio = _contrast(palette.text, getattr(palette, name))
        assert ratio >= 4.5, f"text on {name}: {ratio:.2f}"
    for name in ("accent_tint", "surface"):
        ratio = _contrast(palette.accent_text, getattr(palette, name))
        assert ratio >= 4.5, f"accent_text on {name}: {ratio:.2f}"


@PALETTES
def test_white_text_contrast_on_filled_controls_and_chips(palette: Palette) -> None:
    for name in (
        "primary",
        "primary_hover",
        "accent_pressed",
        "chip_running_bg",
        "chip_success_bg",
        "chip_error_bg",
        "chip_neutral_bg",
        "warn_accent",
    ):
        ratio = _contrast(palette.on_primary, getattr(palette, name))
        assert ratio >= 4.5, f"on_primary on {name}: {ratio:.2f}"


@PALETTES
def test_non_text_marks_contrast(palette: Palette) -> None:
    # WCAG 1.4.11: checked fills, focus rings and unchecked borders need 3:1.
    for name in ("accent", "control_border_off"):
        ratio = _contrast(getattr(palette, name), palette.surface)
        assert ratio >= 3, f"{name} on surface: {ratio:.2f}"


def test_dark_errors_warnings_and_pause_share_one_amber() -> None:
    assert DARK.danger == DARK.warn_fg
    assert DARK.chip_error_bg == DARK.warn_accent
    assert DARK.danger_bg == DARK.warn_bg
    assert DARK.danger_border == DARK.warn_border
    # The paused bar's border shows on its fill at least as much as in the light theme.
    assert _contrast(DARK.warn_border, DARK.warn_fill) >= 2.0
    assert _contrast(LIGHT.warn_border, LIGHT.warn_fill) >= 2.0
    # The checked Overwrite box and the UPM mark: amber on the card.
    assert _contrast(DARK.warn_accent, DARK.surface) >= 3


def test_dark_keeps_disabled_convert_deliberately_dim() -> None:
    ratio = _contrast(DARK.convert_disabled_text, DARK.footer_disabled_bg)
    assert 2.5 <= ratio <= 3


def test_light_chip_fills_match_their_former_tokens() -> None:
    assert LIGHT.chip_running_bg == LIGHT.accent
    assert LIGHT.chip_success_bg == LIGHT.success_icon
    assert LIGHT.chip_error_bg == LIGHT.danger
    assert LIGHT.chip_neutral_bg == LIGHT.slate


def test_accent_contrast() -> None:
    assert _contrast(LIGHT.on_primary, LIGHT.accent) >= 4.5
    assert _contrast(LIGHT.on_primary, LIGHT.accent_hover) >= 4.5
    assert _contrast(LIGHT.on_primary, LIGHT.accent_pressed) >= 4.5
    assert _contrast(LIGHT.accent, LIGHT.accent_tint) >= 4.5
    assert _contrast(LIGHT.text_muted, LIGHT.page) >= 4.5
    assert _contrast(LIGHT.text_muted, LIGHT.accent_tint) >= 4.5
    # Disabled Convert keeps its old, deliberately low contrast (about 2.7:1).
    assert 2.5 <= _contrast(LIGHT.convert_disabled_text, LIGHT.footer_disabled_bg) <= 3
    # One accent family: primary, accent and accent text are the same blue.
    assert LIGHT.primary == LIGHT.accent == LIGHT.accent_text == "#2f5da8"


def test_control_borders_and_badge_check_contrast() -> None:
    # Unchecked checkbox / radio borders are non-text UI: WCAG 1.4.11 asks for 3:1.
    assert LIGHT.control_border_off == "#8a8fa6"
    assert _contrast(LIGHT.control_border_off, LIGHT.surface) >= 3
    assert _contrast(LIGHT.control_border_hover, LIGHT.surface) >= 3
    # Disabled stays visibly lighter than the idle border.
    assert _contrast(LIGHT.checkbox_disabled_border, LIGHT.surface) < _contrast(
        LIGHT.control_border_off, LIGHT.surface
    )
    # Completed-step badge check on its circle.
    assert _contrast(LIGHT.step_check, LIGHT.success_bg) >= 4.5
    # Fields: visible on white cards, placeholder readable on rest and hover fills.
    assert (LIGHT.field, LIGHT.field_hover) == ("#edf1f6", "#e5eaf1")
    assert _contrast(LIGHT.field, LIGHT.surface) > 1.1
    for fill in (LIGHT.field, LIGHT.field_hover, LIGHT.disabled_bg):
        assert _contrast(LIGHT.placeholder, fill) >= 4.5


def test_indicator_border_states_in_stylesheet(icon_dir: Path) -> None:
    sheet = build_stylesheet(LIGHT)
    idle = _selector_block(
        sheet, r"QCheckBox::indicator, QTableView::indicator, QTreeWidget#instanceTree::indicator"
    )
    assert f"solid {LIGHT.control_border_off};" in idle
    hover = _selector_block(sheet, r"QCheckBox::indicator:unchecked:hover,[^{]*")
    assert f"border-color: {LIGHT.control_border_hover};" in hover
    assert "QRadioButton::indicator:unchecked:hover" in sheet
    disabled = _selector_block(sheet, r"QCheckBox::indicator:disabled")
    assert f"border-color: {LIGHT.checkbox_disabled_border};" in disabled
    field_hover = _selector_block(sheet, r"QComboBox:hover:enabled,[^{]*")
    assert f"background: {LIGHT.field_hover};" in field_hover


def test_unchecked_text_contrast() -> None:
    assert LIGHT.text_dim == "#626678"
    assert _contrast(LIGHT.text_dim, LIGHT.surface) >= 4.5


def test_font_views_row_states(qapp: QApplication) -> None:
    container = QWidget()
    container.setStyleSheet(build_stylesheet(LIGHT))
    layout = QHBoxLayout(container)
    table = FileTable()
    files = FontFileList(table, lambda: (None, False))
    for row in range(12):
        path = Path(f"font{row}.ttf")
        files.model.add_font(
            path, path.name, FontInfo(path, "TTF", "TrueType", 1000), True, (None, False)
        )
    tree = InstanceTree()
    path = Path("variable.ttf")
    info = FontInfo(
        path,
        "TTF",
        "TrueType",
        1000,
        variable=True,
        instances=tuple(
            NamedInstanceInfo(f"instance {n:02}", (("wght", float(n)),)) for n in range(25)
        ),
    )
    tree.add_font(path, "Variable", info)
    parent = tree.topLevelItem(0)
    parent.setExpanded(True)
    parent.child(0).setCheckState(0, Qt.CheckState.Unchecked)
    layout.addWidget(table)
    layout.addWidget(tree)
    container.resize(1300, 400)
    container.show()
    container.activateWindow()
    QTest.qWait(50)
    QCursor.setPos(container.mapToGlobal(QPoint(0, 0)))

    def pixel(view: FileTable | InstanceTree, x: int, y: int) -> QColor:
        image = view.viewport().grab().toImage()
        scale = image.devicePixelRatio()
        return image.pixelColor(round(x * scale), round(y * scale))

    assert parent.checkState(0) == Qt.CheckState.PartiallyChecked
    for row in range(12):
        assert pixel(table, 180, row * 30 + 4) == QColor(LIGHT.surface)
    assert pixel(tree, 180, 4) == QColor(LIGHT.list_alt)
    for row in range(1, 10):
        assert pixel(tree, 180, row * 30 + 4) == QColor(LIGHT.surface)

    child_index = tree.indexFromItem(parent.child(0))
    delegate = tree.itemDelegate()
    assert isinstance(delegate, FontRowDelegate)
    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, child_index)
    delegate.prepare_row(option, child_index)
    assert option.palette.color(QPalette.ColorRole.Text) == QColor(LIGHT.text_dim)
    group_index = tree.indexFromItem(parent)
    group_option = QStyleOptionViewItem()
    delegate.initStyleOption(group_option, group_index)
    delegate.prepare_row(group_option, group_index)
    assert group_option.font.weight() == QFont.Weight.DemiBold
    assert group_option.palette.color(QPalette.ColorRole.Text) == QColor(LIGHT.text)

    QCursor.setPos(tree.viewport().mapToGlobal(QPoint(180, 4)))
    QTest.mouseMove(tree.viewport(), QPoint(180, 4))
    QTest.qWait(20)
    assert pixel(tree, 180, 4) == QColor(LIGHT.table_header)

    for view, position in ((table, QPoint(180, 4)), (tree, QPoint(180, 34))):
        QCursor.setPos(view.viewport().mapToGlobal(position))
        QTest.mouseMove(view.viewport(), position)
        QTest.qWait(20)
        assert pixel(view, position.x(), position.y()) == QColor(LIGHT.row_hover)
        QCursor.setPos(container.mapToGlobal(QPoint(0, 0)))
        view.setFocus()
        if view is tree:
            tree.setCurrentIndex(group_index)
            QTest.keyClick(view, Qt.Key.Key_Down)
        else:
            QTest.keyClick(view, Qt.Key.Key_Down)
            QTest.keyClick(view, Qt.Key.Key_Up)
        QTest.qWait(20)
        assert pixel(view, position.x(), position.y()) == QColor(LIGHT.row_selection)

    other = QWidget()
    other.show()
    other.activateWindow()
    QTest.qWait(50)
    assert not container.isActiveWindow()
    assert pixel(table, 180, 4) == QColor(LIGHT.row_selection_inactive)
    assert pixel(tree, 180, 34) == QColor(LIGHT.row_selection_inactive)
    other.close()
    container.close()


def _populated_table(qapp: QApplication, rows: int = 4) -> tuple[QWidget, FileTable]:
    container = QWidget()
    container.setStyleSheet(build_stylesheet(LIGHT))
    layout = QHBoxLayout(container)
    table = FileTable()
    files = FontFileList(table, lambda: (None, False))
    for row in range(rows):
        path = Path(f"font{row}.ttf")
        files.model.add_font(
            path, path.name, FontInfo(path, "TTF", "TrueType", 1000), True, (None, False)
        )
    layout.addWidget(table)
    container.resize(700, 300)
    container.show()
    container.activateWindow()
    QTest.qWait(50)
    QCursor.setPos(container.mapToGlobal(QPoint(0, 0)))
    return container, table


def test_table_rows_draw_separator_and_focus_bar_in_the_delegate(qapp: QApplication) -> None:
    container, table = _populated_table(qapp)

    def pixel(x: int, y: int) -> QColor:
        image = table.viewport().grab().toImage()
        scale = image.devicePixelRatio()
        return image.pixelColor(round(x * scale), round(y * scale))

    for row in range(3):
        for x in (20, 180, table.viewport().width() - 5):
            assert pixel(x, row * 30 + 29) == QColor(LIGHT.row_separator)
    table.setFocus()
    table.setCurrentIndex(table.model().index(1, 0))
    QTest.qWait(30)
    assert pixel(0, 30 + 10) == QColor(LIGHT.accent)
    assert pixel(1, 30 + 10) == QColor(LIGHT.accent)
    assert pixel(3, 30 + 10) != QColor(LIGHT.accent)
    assert pixel(0, 10) != QColor(LIGHT.accent)
    container.close()


def test_drag_over_tints_every_row_of_the_list(qapp: QApplication) -> None:
    from fontvertx.gui.widgets import set_drag_over

    container, table = _populated_table(qapp)

    def pixel(x: int, y: int) -> QColor:
        image = table.viewport().grab().toImage()
        scale = image.devicePixelRatio()
        return image.pixelColor(round(x * scale), round(y * scale))

    def frame_pixel(y: int) -> QColor:
        image = table.grab().toImage()
        return image.pixelColor(image.width() // 2, y if y >= 0 else image.height() + y)

    # Offscreen the table is the only focusable widget: drop focus to see the rest hairline.
    QTest.qWaitForWindowActive(container)
    table.clearFocus()
    QTest.qWait(30)
    assert pixel(180, 4) == QColor(LIGHT.surface)
    assert frame_pixel(0) == QColor(LIGHT.border)
    set_drag_over(table, True)
    QTest.qWait(30)
    assert pixel(180, 4) == QColor(LIGHT.row_selected_a)
    assert pixel(180, 34) == QColor(LIGHT.row_selected_a)
    assert frame_pixel(0) == QColor(LIGHT.accent)
    assert frame_pixel(-1) == QColor(LIGHT.accent)
    set_drag_over(table, False)
    QTest.qWait(30)
    assert pixel(180, 4) == QColor(LIGHT.surface)
    assert frame_pixel(0) == QColor(LIGHT.border)
    container.close()


def test_font_views_elide_long_names_instead_of_wrapping(qapp: QApplication) -> None:
    table = FileTable()
    tree = InstanceTree()
    for view in (table, tree):
        assert not view.wordWrap()
        assert view.textElideMode() == Qt.TextElideMode.ElideMiddle


def test_state_and_badge_text_meets_contrast_requirement() -> None:
    pairs = (
        (LIGHT.success_fg, LIGHT.success_bg),
        (LIGHT.success_icon, LIGHT.success_bg),
        (LIGHT.warn_fg, LIGHT.warn_bg),
        (LIGHT.danger, LIGHT.danger_bg),
        (LIGHT.primary_tint_fg, LIGHT.primary_tint_bg),
        (LIGHT.text_muted, LIGHT.badge_muted),
        (LIGHT.accent, LIGHT.accent_tint),
        (LIGHT.on_primary, LIGHT.primary),
        (LIGHT.on_primary, LIGHT.warn_accent),
    )
    for foreground, background in pairs:
        assert _contrast(foreground, background) >= 4.5


def test_dark_stylesheet_has_no_unresolved_tokens(icon_dir: Path) -> None:
    sheet = build_stylesheet(DARK)
    assert not re.search(r"\$[a-z_]+", sheet)
    assert DARK.page in sheet
    assert f"expand_more_{DARK.text_muted[1:]}.svg" in sheet


def test_stylesheet_has_no_unresolved_tokens(icon_dir: Path) -> None:
    sheet = build_stylesheet(LIGHT)
    assert not re.search(r"\$[a-z_]+", sheet)
    assert LIGHT.page in sheet
    # The two existing ones, plus the column menu button's (hidden) menu indicator.
    assert re.findall(r"image: (\S+);", sheet).count("none") == 3
    assert "QComboBox::down-arrow" in sheet
    for name in ("arrow_downward", "arrow_upward", "expand_more", "expand_less"):
        assert f"{name}_{LIGHT.text_muted[1:]}.svg" in sheet
    assert ".png" not in sheet  # every stylesheet image is vector
    assert "QComboBox QAbstractItemView::item:disabled" in sheet
    assert "QScrollBar::handle:vertical:hover" in sheet
    assert LIGHT.text_disabled in sheet


def test_scrollbar_has_transparent_track_and_handle(qapp: QApplication) -> None:
    area = QScrollArea()
    area.setStyleSheet(build_stylesheet(LIGHT))
    area.resize(180, 120)
    content = QWidget()
    content.setMinimumHeight(500)
    area.setWidget(content)
    area.show()
    qapp.processEvents()
    scrollbar = area.verticalScrollBar()
    assert scrollbar.maximum() > 0
    image = scrollbar.grab().toImage()
    assert image.pixelColor(1, image.height() // 2).alpha() == 0
    assert image.pixelColor(6, 10) == QColor(LIGHT.scroll_handle)
    area.close()


def test_table_header_aligns_when_scrollbar_appears(qapp: QApplication) -> None:
    table = FileTable()
    table.setStyleSheet(build_stylesheet(LIGHT))
    model = QStandardItemModel(0, 6, table)
    table.setModel(model)
    table.configure_columns()
    table.resize(650, 200)
    table.show()
    qapp.processEvents()
    bar = table.verticalScrollBar()
    assert bar.maximum() == 0 and not bar.isVisible()
    width_before = table.columnWidth(0)
    model.setRowCount(100)
    QTest.qWait(30)
    header = table.horizontalHeader()
    assert bar.maximum() > 0 and bar.isVisible()
    # The columns end at the fixed-width header corner, which covers the band above the
    # scrollbar: they keep their width when the bar appears.
    assert table.columnWidth(0) == width_before
    for column in range(4):
        assert header.sectionViewportPosition(column) == table.columnViewportPosition(column)
    assert bar.mapTo(table, QPoint(0, 0)).y() >= header.geometry().bottom()
    table.close()


@pytest.mark.parametrize("fill_header", [False, True])
def test_table_scrollbar_header_filler_tracks_visibility(
    qapp: QApplication, fill_header: bool, qtbot_wait: Callable[..., None]
) -> None:
    table = FileTable()
    table.setStyleSheet(build_stylesheet(LIGHT))
    model = QStandardItemModel(0, 6, table)
    table.setModel(model)
    table.configure_columns()
    header = table.horizontalHeader()
    if not fill_header:
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        for column in range(4):
            table.setColumnWidth(column, 60)
    table.resize(650, 200)
    table.show()
    QTest.qWait(30)
    bar = table.verticalScrollBar()
    cap = table._scrollbar_header_cap

    corner = table.column_button
    for rows, width in ((100, 650), (100, 700), (0, 700), (100, 700), (0, 650)):
        table.resize(width, 200)
        model.setRowCount(rows)
        # The scrollbar shows or hides on a later event-loop pass: wait for it (a fixed
        # short wait is not enough on slow CI runners).
        expected = rows > 0
        qtbot_wait(lambda e=expected: cap.isVisible() == bar.isVisible() == e, 2.0)
        # The button (the header corner) is there either way, 32px wide, over the cap.
        assert corner.isVisible() and corner.width() == widgets_module.HEADER_CORNER_WIDTH
        assert corner.geometry().right() == table.contentsRect().right()
        assert corner.geometry().top() == header.geometry().top()
        assert corner.height() == header.height()
        if not rows:
            continue
        assert corner.geometry().contains(QRect(cap.mapTo(table, QPoint(0, 0)), cap.size()))
        cap_pos = cap.mapTo(table, QPoint(0, 0))
        bar_pos = bar.mapTo(table, QPoint(0, 0))
        assert cap_pos.x() == bar_pos.x()
        assert cap.width() == bar.width()
        assert cap.height() == header.height()
        assert cap_pos.y() == header.geometry().top()
        assert cap_pos.y() + cap.height() == bar_pos.y()

        image = table.grab().toImage()
        scale = image.width() / table.width()
        for offset in (-3, -2, -1, 0, 1, 2, 3):
            pixel = image.pixelColor(round((cap_pos.x() + offset) * scale), round(3 * scale))
            expected = QColor(LIGHT.table_header)
            assert abs(pixel.red() - expected.red()) <= 12
            assert abs(pixel.green() - expected.green()) <= 12
            assert abs(pixel.blue() - expected.blue()) <= 12
        for column in range(4):
            assert header.sectionViewportPosition(column) == table.columnViewportPosition(column)
    table.close()


@pytest.mark.parametrize("rows", [0, 100])
@pytest.mark.parametrize("fill_header", [False, True])
def test_table_frame_is_edge_to_edge_hairlines(
    qapp: QApplication, rows: int, fill_header: bool
) -> None:
    """The list has no frame of its own: two hairlines, a full-width header, no clipped corners."""
    table = FileTable()
    table.setStyleSheet(build_stylesheet(LIGHT))
    model = QStandardItemModel(rows, 6, table)
    table.setModel(model)
    table.configure_columns()
    if not fill_header:
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        for column in range(4):
            table.setColumnWidth(column, 60)
    table.resize(650, 200)
    table.show()
    # The table is the only focusable widget offscreen: check the rest hairline first.
    # Wait for activation, which would otherwise hand the focus back afterwards.
    QTest.qWaitForWindowActive(table)
    table.clearFocus()
    QTest.qWait(30)

    assert (table.verticalScrollBar().maximum() > 0) == (rows > 0)
    assert table.viewport().mask().isEmpty()
    image = table.grab().toImage()
    scale = image.width() / table.width()
    hairline = QColor(LIGHT.border)
    header_color = QColor(LIGHT.table_header)
    last = image.width() - 1
    for x in (0, image.width() // 2, last):
        assert image.pixelColor(x, 0) == hairline
        assert image.pixelColor(x, image.height() - 1) == hairline
    header_y = round(3 * scale)
    for x in (0, last):
        pixel = image.pixelColor(x, header_y)
        assert abs(pixel.red() - header_color.red()) <= 12
        assert abs(pixel.green() - header_color.green()) <= 12
        assert abs(pixel.blue() - header_color.blue()) <= 12
    middle = image.height() // 2
    assert image.pixelColor(0, middle) != hairline
    assert image.pixelColor(last, middle) != hairline
    table.setFocus()
    QTest.qWait(30)
    focused = table.grab().toImage()
    focus_hairline = QColor(LIGHT.border_hover)
    assert focused.pixelColor(focused.width() // 2, 0) == focus_hairline
    assert focused.pixelColor(focused.width() // 2, focused.height() - 1) == focus_hairline
    table.close()


def _selector_block(sheet: str, selector_pattern: str) -> str:
    match = re.search(rf"{selector_pattern}\s*\{{([^}}]+)\}}", sheet, re.DOTALL)
    assert match is not None
    return match.group(1)


def test_header_sections_have_right_separator_except_last(icon_dir: Path) -> None:
    sheet = build_stylesheet(LIGHT)
    section = _selector_block(
        sheet,
        r"QTableView#fontFileTable QHeaderView::section,\s*"
        r"QTreeWidget#instanceTree QHeaderView::section",
    )
    assert f"border-right: 1px solid {LIGHT.border_strong};" in section
    # The border replaces 1px of the 3px padding: label positions do not move.
    assert "padding-right: 2px;" in section
    last = _selector_block(
        sheet,
        r"QTableView#fontFileTable QHeaderView::section:last,\s*"
        r"QTableView#fontFileTable QHeaderView::section:only-one,\s*"
        r"QTreeWidget#instanceTree QHeaderView::section:last,\s*"
        r"QTreeWidget#instanceTree QHeaderView::section:only-one",
    )
    assert "border-right: none;" in last
    assert "padding-right: 3px;" in last
    # Separators belong to the header only: rows and the scrollbar filler get none.
    assert "border-right" not in _selector_block(sheet, r"QWidget#tableScrollbarHeader")
    assert "border-right" not in _selector_block(
        sheet, r"QHeaderView::section, QTableCornerButton::section"
    )


def test_header_separators_render_between_sections_only(qapp: QApplication) -> None:
    table = FileTable()
    table.setStyleSheet(build_stylesheet(LIGHT))
    model = QStandardItemModel(100, 6, table)
    table.setModel(model)
    table.configure_columns()
    table.resize(650, 200)
    table.show()
    QTest.qWait(30)
    header = table.horizontalHeader()
    visible = [c for c in range(model.columnCount()) if not header.isSectionHidden(c)]
    assert len(visible) > 1
    image = header.grab().toImage()
    scale = image.width() / header.width()
    y = round(header.height() / 2 * scale)

    def right_edge(column: int) -> QColor:
        x = header.sectionViewportPosition(column) + header.sectionSize(column) - 1
        return image.pixelColor(round(x * scale), y)

    for column in visible[:-1]:
        assert right_edge(column) == QColor(LIGHT.border_strong)
    assert right_edge(visible[-1]) == QColor(LIGHT.table_header)
    table.close()


def test_checkbox_and_row_selection_tokens_are_applied(icon_dir: Path) -> None:
    sheet = build_stylesheet(LIGHT)
    checked = _selector_block(
        sheet,
        r"QCheckBox::indicator:checked,\s*QTableView::indicator:checked,\s*"
        r"QTreeWidget#instanceTree::indicator:checked",
    )
    assert f"background: {LIGHT.accent};" in checked
    assert f"border-color: {LIGHT.accent};" in checked
    assert "indicators/check.svg" in checked
    overwrite_checked = _selector_block(sheet, "QCheckBox#warnCheckbox::indicator:checked")
    assert f"background: {LIGHT.warn_accent};" in overwrite_checked
    assert f"border-color: {LIGHT.warn_accent};" in overwrite_checked
    assert "indicators/check.svg" in overwrite_checked
    # Selected rows use row_selection (inactive: row_selection_inactive); the drag-over
    # target is tinted with row_selected_a.
    for state, token in (
        (":active", LIGHT.row_selection),
        (":!active", LIGHT.row_selection_inactive),
    ):
        selected = _selector_block(sheet, rf"QTableView::item:selected{state},[^{{]*")
        assert f"background: {token};" in selected
    drag_over = _selector_block(sheet, r'QTableView\[dragOver="true"\],[^{]*')
    assert f"background: {LIGHT.row_selected_a};" in drag_over
    assert LIGHT.row_separator == "#e1e6ee"
    assert LIGHT.success_border == "#bfe3ce"
    assert f"border: 1px solid {LIGHT.success_btn_border};" in sheet
    assert "QPushButton#addInstanceButton" not in sheet
    assert "QPushButton#quietIconButton:focus" in sheet
    assert LIGHT.accent_border_soft == "#b9c8e2"


def test_indicator_marks_are_white_svgs(icon_dir: Path) -> None:
    sheet = build_stylesheet(LIGHT)
    for name in INDICATOR_MARKS:
        svg = styles._INDICATOR_DIR / f"{name}.svg"
        assert svg.is_file()
        assert "#ffffff" in svg.read_text(encoding="utf-8")
        assert f"indicators/{name}.svg" in sheet
        assert not QImage(str(svg)).isNull()


def test_indicator_mark_falls_back_to_none_when_missing(
    icon_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(styles, "_INDICATOR_DIR", icon_dir / "missing")
    assert styles._indicator_svg("check") == "none"


def test_stylesheet_is_cached(qapp: QApplication) -> None:
    assert styles.stylesheet() is styles.stylesheet()


def test_stylesheet_is_built_from_the_active_palette(qapp: QApplication) -> None:
    assert styles.colors() is LIGHT
    assert styles.stylesheet() == build_stylesheet(LIGHT)


def test_set_palette_reports_a_change_and_switches_the_stylesheet(qapp: QApplication) -> None:
    other = dataclasses.replace(LIGHT, page="#123456")
    try:
        assert styles.set_palette(LIGHT) is False
        assert styles.set_palette(other) is True
        assert styles.colors() is other
        assert "#123456" in styles.stylesheet()
    finally:
        styles.set_palette(LIGHT)
    assert styles.stylesheet() == build_stylesheet(LIGHT)


def test_mono_family_change_rebuilds_the_stylesheet(qapp: QApplication) -> None:
    original = styles.mono_family()
    try:
        styles.set_mono_family("Fontvertx Test Mono")
        assert "Fontvertx Test Mono" in styles.stylesheet()
    finally:
        styles.set_mono_family(original)
    assert "Fontvertx Test Mono" not in styles.stylesheet()


def test_palette_is_read_through_colors_outside_styles() -> None:
    """Code outside styles.py reads the current palette, so a theme switch reaches it."""
    source = Path(styles.__file__).parent.parent
    offenders = [
        f"{path.relative_to(source)}:{number}"
        for path in sorted(source.rglob("*.py"))
        if path.name != "styles.py"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\bLIGHT\b", line)
    ]
    assert offenders == []


@pytest.mark.parametrize("field_type", [QLineEdit, QSpinBox, QDoubleSpinBox])
def test_text_selection_colors_apply_in_active_and_inactive_palettes(
    qapp: QApplication, field_type: type[QLineEdit]
) -> None:
    field = field_type()
    field.setStyleSheet(styles.stylesheet())
    field.ensurePolished()

    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        assert field.palette().color(group, QPalette.ColorRole.Highlight) == QColor(
            LIGHT.text_selection_bg
        )
        assert field.palette().color(group, QPalette.ColorRole.HighlightedText) == QColor(
            LIGHT.text
        )


@pytest.mark.parametrize(
    ("name", "footer"),
    [
        ("", False),
        ("importButton", False),
        ("primaryButton", False),
        ("primaryButton", True),
        ("organizationIconButton", False),
        ("stepperButton", False),
    ],
)
def test_buttons_use_medium_weight(qapp: QApplication, name: str, footer: bool) -> None:
    button = QPushButton("Test")
    button.setObjectName(name)
    if footer:
        button.setProperty("footerPrimary", True)
    button.setStyleSheet(styles.stylesheet())
    button.ensurePolished()
    # Every button is Medium except Convert (SemiBold).
    expected_weight = QFont.Weight.DemiBold if footer else QFont.Weight.Medium
    assert button.font().weight() == expected_weight


def test_tinted_svgs_are_vector_copies_written_once(qapp: QApplication, icon_dir: Path) -> None:
    for name in ("expand_more", "expand_less", "arrow_upward", "arrow_downward"):
        url = styles._tinted_svg(name, "#123456")
        path = icon_dir / f"{name}_123456.svg"
        assert url == f"url({path.as_posix()})"
        text = path.read_text(encoding="utf-8")
        assert text.startswith('<svg fill="#123456" ')
        assert text.replace('fill="#123456" ', "") == (
            styles._MATERIAL_DIR / f"{name}.svg"
        ).read_text(encoding="utf-8")
        # Rendered from the vector at a 2x size: no upscaled raster.
        assert QImage(str(path)).isNull() is False
    # Existing files are reused, not rewritten.
    stamp = (icon_dir / "expand_more_123456.svg").stat().st_mtime_ns
    styles._tinted_svg("expand_more", "#123456")
    assert (icon_dir / "expand_more_123456.svg").stat().st_mtime_ns == stamp


def test_tinted_svg_falls_back_to_none_on_write_error(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "not_a_directory"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr(styles, "_icon_directory", lambda: blocker)
    assert styles._tinted_svg("expand_more", "#abcdef") == "none"


@pytest.fixture
def styled_window(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> ConverterWindow:
    from PySide6.QtCore import QSettings

    ini = tmp_path / "s.ini"
    monkeypatch.setattr(
        window_module, "QSettings", lambda: QSettings(str(ini), QSettings.Format.IniFormat)
    )
    # Closed and deleted by the autouse cleanup in conftest.py.
    return ConverterWindow()


def test_tab_focus_is_visible_without_layout_shift(styled_window: ConverterWindow) -> None:
    from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit

    window = styled_window
    window.show()
    QApplication.processEvents()
    controls = [
        w
        for w in window.findChildren(QAbstractButton)
        + window.findChildren(QAbstractSpinBox)
        + window.findChildren(QComboBox)
        + window.findChildren(QLineEdit)
        if w.isVisible() and w.isEnabled() and w.focusPolicy() & Qt.FocusPolicy.TabFocus
    ]
    assert controls
    checked = 0
    for control in controls:
        before = control.size()
        control.setFocus(Qt.FocusReason.TabFocusReason)
        QApplication.processEvents()
        if not control.hasFocus():
            continue
        assert control.size() == before, control.objectName() or type(control).__name__
        checked += 1
        if isinstance(control, (QCheckBox, QRadioButton)):
            image = control.grab().toImage()
            assert image.pixelColor(0, control.height() // 2).name() == LIGHT.accent
    assert checked >= len(controls) // 2


def test_selected_row_color_is_distinct_from_hover() -> None:
    assert LIGHT.row_selection == "#e6ecf5"
    assert LIGHT.row_selection != LIGHT.row_hover


def test_window_renders(styled_window: ConverterWindow) -> None:
    styled_window.show()
    QApplication.processEvents()
    image = styled_window.grab().toImage()
    assert not image.isNull()
    assert image.width() == styled_window.width()
    assert image.pixelColor(5, 5).name() == LIGHT.page


def test_inactive_options_card_keeps_normal_appearance(
    styled_window: ConverterWindow,
) -> None:
    styled_window.show()
    QApplication.processEvents()
    card = styled_window.profile_options
    assert not card.isHidden()
    assert not card.isEnabled()
    assert card.grab().toImage().pixelColor(5, 5).name() == LIGHT.surface
    labels = [
        card.findChild(QLabel, "cardNumber"),
        card.findChild(QLabel, "cardHeading"),
        card.no_profile_options.body,
    ]
    colors = (LIGHT.text_muted, LIGHT.text_dim, LIGHT.text_muted)
    for label, color in zip(labels, colors, strict=True):
        assert label is not None
        assert label.palette().color(QPalette.ColorRole.WindowText).name() == color
    styled_window.conversion.setCurrentIndex(styled_window.conversion.findData("ttf2otf"))
    QApplication.processEvents()
    assert card.isEnabled()
    assert card.grab().toImage().pixelColor(5, 5).name() == LIGHT.surface
    # With a conversion chosen the card looks normal even without compatible fonts:
    # its options are settings that do not depend on the loaded fonts.
    assert card.property("optionsState") == ""
    for label, color in zip(labels[:2], (LIGHT.accent, LIGHT.text), strict=True):
        assert label is not None
        assert label.palette().color(QPalette.ColorRole.WindowText).name() == color


def test_step_badges_and_modified_chip_follow_state(styled_window: ConverterWindow) -> None:
    window = styled_window
    window._update_buttons()
    assert [badge.text() for badge in window._step_badges] == ["1", "2", "3", "4"]
    assert [badge.property("state") for badge in window._step_badges[:2]] == [
        "muted",
        "muted",
    ]
    assert all(badge.property("state") != "valid" for badge in window._step_badges[2:])
    assert not window.profile_options.reset_button.isEnabled()
    options_chip = window.profile_options.findChild(QLabel, "modifiedChip")
    assert options_chip is not None and options_chip.isHidden()
    assert window.destination_group.findChild(QLabel, "modifiedChip") is None

    window.conversion.setCurrentIndex(window.conversion.findData("ttf2otf"))
    incompatible = FontInfo(Path("incompatible.otf"), "OTF", "PostScript", 1000)
    window.file_list.add_font(
        incompatible.path,
        incompatible.path.name,
        incompatible,
        True,
    )
    window._apply_compatibility()
    window._update_buttons()
    assert window._step_badges[0].text() == "1"
    assert window._step_badges[0].property("state") == "invalid"
    # A completed step shows the vector check instead of a text glyph.
    assert window._step_badges[1].is_done()
    assert window._step_badges[1].text() == ""
    assert window._step_badges[1].accessibleName() == "Step 2 complete"
    assert window._step_badges[1].property("state") == "valid"
    assert not window._step_badges[0].is_done()
    assert window.profile_options.property("optionsState") == ""
    assert not window.convert_button.isEnabled()
    assert window.summary.text() == "No compatible fonts for this conversion"

    window.profile_options.subroutinize.setChecked(False)
    assert not options_chip.isHidden()
    assert not window.profile_options.reset_button.isHidden()
    assert window.profile_options.reset_button.isEnabled()
    window.profile_options.reset_button.click()
    assert options_chip.isHidden()
    assert not window.profile_options.reset_button.isEnabled()

    window.overwrite.setChecked(True)
    assert window._step_badges[3].text() == "4"
    assert window._step_badges[3].property("state") == ""


@pytest.mark.parametrize("ratio", [1.0, 1.25, 1.5, 1.75, 2.0])
def test_step_badge_check_lands_on_whole_pixels(ratio: float) -> None:
    from fontvertx.gui.widgets import STEP_ICON_SIZE, centered_icon_pixels

    icon_px, offset_px = centered_icon_pixels(24, STEP_ICON_SIZE, ratio)
    box_px = round(24 * ratio)
    assert offset_px * 2 + icon_px == box_px  # same margin on both sides
    assert abs(icon_px - STEP_ICON_SIZE * ratio) <= 1


def test_completed_step_badge_paints_a_centered_vector_check(
    styled_window: ConverterWindow,
) -> None:
    window = styled_window
    window.show()
    window._on_font_found(Path("a.ttf"), FontInfo(Path("a.ttf"), "TTF", "TrueType", 1000))
    window.conversion.setCurrentIndex(window.conversion.findData("ttf2otf"))
    QApplication.processEvents()
    badge = window._step_badges[0]
    assert badge.is_done() and badge.text() == ""
    image = badge.grab().toImage()
    background = QColor(LIGHT.success_bg)
    ink = [
        (x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).lightness() < background.lightness() - 60
    ]
    assert ink, "the check mark is painted"
    xs = [x for x, _ in ink]
    ys = [y for _, y in ink]
    assert min(xs) == image.width() - 1 - max(xs)
    assert min(ys) == image.height() - 1 - max(ys)
    badge.set_done(False)
    assert badge.text() == "1" and not badge.is_done()


def _near(color: QColor, expected: str, tolerance: int = 16) -> bool:
    """Same color up to the antialiasing of a 1px rounded border."""
    target = QColor(expected)
    return all(
        abs(a - b) <= tolerance
        for a, b in zip(color.getRgb()[:3], target.getRgb()[:3], strict=True)
    )


@pytest.mark.parametrize(
    ("state", "tone", "chip"),
    [
        (StatusState.DONE, "success", "Done"),
        (StatusState.WARNING, "warning", "0 skipped"),
        (StatusState.FAILED, "error", "0 failed"),
        (StatusState.CANCELLED, "neutral", "Cancelled"),
        (StatusState.FATAL, "error", "Error"),
    ],
)
def test_footer_result_shows_chip_and_counts(
    styled_window: ConverterWindow, state: StatusState, tone: str, chip: str
) -> None:
    pill = styled_window.status_pill
    styled_window._set_run_status(state)
    assert pill.chip.text() == chip
    assert pill.chip.property("tone") == tone
    assert pill.chip.icon.pixmap() is not None
    assert "converted" in pill.counts.text()
    assert not pill.chip.isHidden() and not pill.counts.isHidden()
    assert pill.label.isHidden() and pill.run_view.isHidden()
    assert pill.property("state") == tone


def test_result_actions_share_compact_state_panel(
    app_font: None, styled_window: ConverterWindow
) -> None:
    window = styled_window
    window.resize(1200, 600)
    window.show()
    window._set_run_status(StatusState.DONE)
    window.view_log_button.setEnabled(True)
    window.open_output_button.setEnabled(True)
    QApplication.processEvents()

    pill = window.status_pill
    assert pill.height() == styles.FOOTER_HEIGHT
    assert pill.pill_layout.indexOf(pill.chip) >= 0
    assert pill.pill_layout.indexOf(pill.result_buttons) >= 0
    assert pill.chip.text() == "Done"
    assert pill.property("state") == "success"
    assert pill.result_buttons_layout.direction().name == "LeftToRight"
    # No dismiss button on a result: Convert is ready for another run.
    assert pill.close_button.isHidden()
    # The footer card carries the tone; the status content paints nothing itself.
    assert window.footer_card.property("tone") == "success"
    card_image = window.footer_card.grab().toImage()
    assert card_image.pixelColor(10, card_image.height() // 2).name() == LIGHT.success_bg
    assert card_image.pixelColor(card_image.width() // 2, 0).name() == LIGHT.success_border
    button_image = window.view_log_button.grab().toImage()
    assert _near(
        button_image.pixelColor(0, window.view_log_button.height() // 2), LIGHT.success_btn_border
    )
    assert not pill.compact
    assert window.view_log_button.height() == 32
    assert window.view_log_button.text() == "View log"
    assert not window.view_log_button.icon().isNull()
    assert not window.open_output_button.icon().isNull()
    # Green chip, white text.
    chip = pill.chip.grab().toImage()
    assert chip.pixelColor(chip.width() // 2, 2).name() == LIGHT.success_icon
    assert (
        pill.chip.label.palette().color(pill.chip.label.foregroundRole()).name() == LIGHT.on_primary
    )


def test_notice_keeps_glyph_and_dismiss(styled_window: ConverterWindow) -> None:
    window = styled_window
    window.show()
    window._set_status("Could not open the output folder.", "error")
    QApplication.processEvents()
    pill = window.status_pill
    assert pill.close_button.size() == QSize(28, 28)
    assert not pill.close_button.isHidden()
    assert pill.label.property("state") == "error"
    assert pill.label.property("footerStatus") is True
    # Error glyph: on a 22px white circle.
    assert pill.icon.size() == QSize(22, 22)
    icon_image = pill.icon.grab().toImage()
    assert icon_image.pixelColor(2, 11).name() == LIGHT.surface
    assert pill.chip.isHidden() and pill.result_buttons.isHidden()


@pytest.mark.parametrize(
    ("state", "background", "border", "track", "fill", "title"),
    [
        (
            StatusState.RUNNING,
            LIGHT.accent_tint,
            LIGHT.running_track,
            LIGHT.running_track,
            LIGHT.accent,
            "Converting…",
        ),
        (
            StatusState.PAUSED,
            LIGHT.warn_bg,
            LIGHT.warn_border,
            LIGHT.warn_fill,
            LIGHT.warn_border,
            "Paused",
        ),
    ],
)
def test_footer_card_tone_and_progress_bar(
    styled_window: ConverterWindow,
    state: StatusState,
    background: str,
    border: str,
    track: str,
    fill: str,
    title: str,
) -> None:
    window = styled_window
    window.resize(1200, 600)
    window.show()
    window.converter.outcome.total = 4
    window.converter.progress_done = 1
    window.progress.setRange(0, 4)
    window.progress.setValue(1)
    window._set_run_status(state)
    QApplication.processEvents()
    pill = window.status_pill
    card = window.footer_card.grab().toImage()
    assert card.pixelColor(10, card.height() // 2).name() == background
    assert card.pixelColor(card.width() // 2, 0).name() == border
    assert pill.run_title.text() == title
    assert pill.run_counter.text() == "1 / 4"
    # Thin 6px bar under the text line, spanning the status area, 25% filled.
    bar = pill.progress
    assert bar.isVisible() and bar.height() == 6
    assert bar.width() > pill.run_title.width()
    assert bar.accessibleName() == "Conversion progress"
    assert bar.value() == 1 and bar.maximum() == 4
    image = bar.grab().toImage()
    assert image.pixelColor(bar.width() // 8, 3).name() == fill
    assert image.pixelColor(bar.width() * 3 // 4, 3).name() == track


def test_paused_run_stays_amber(styled_window: ConverterWindow) -> None:
    """Paused uses the amber warning family throughout; grey is only for CANCELLED."""
    window = styled_window
    window.resize(1200, 600)
    window.show()
    window.converter.outcome.total = 4
    window.converter.progress_done = 2
    window.progress.setRange(0, 4)
    window.progress.setValue(2)
    window._set_run_status(StatusState.PAUSED)
    QApplication.processEvents()
    pill = window.status_pill
    bar = pill.progress
    image = bar.grab().toImage()
    fill = image.pixelColor(bar.width() // 8, 3).name()
    track = image.pixelColor(bar.width() * 7 // 8, 3).name()
    assert (fill, track) == (LIGHT.warn_border, LIGHT.warn_fill)
    grey = {LIGHT.border_strong, LIGHT.control_border_strong, LIGHT.slate}
    assert not {fill, track} & grey
    # The run's action icons (View log) are amber too, like the other warning states.
    for button, name in pill._icon_names.items():
        expected = pill._action_icon(name, LIGHT.warn_fg)
        assert button.icon().cacheKey() == expected.cacheKey()
    # Resumed: back to the running colors.
    window._set_run_status(StatusState.RUNNING)
    QApplication.processEvents()
    image = bar.grab().toImage()
    assert image.pixelColor(bar.width() // 8, 3).name() == LIGHT.accent


def test_warning_palette_is_one_amber_family() -> None:
    """warn_accent is amber like the other warn_* tokens; ``warning`` merged into warn_fg."""
    assert not hasattr(LIGHT, "warning")
    for name in ("warn_accent", "warn_fg", "warn_border", "warn_fill"):
        hue = QColor(getattr(LIGHT, name)).hslHue()
        assert 34 <= hue <= 42, f"{name} hue {hue}"
    # Chip and checked Overwrite: white on warn_accent; the "Non-standard UPM" mark:
    # warn_accent on the card.
    assert _contrast(LIGHT.on_primary, LIGHT.warn_accent) >= 4.5
    assert _contrast(LIGHT.warn_accent, LIGHT.surface) >= 4.5


def test_run_title_tones_and_paused_hint(styled_window: ConverterWindow) -> None:
    window = styled_window
    window.show()
    pill = window.status_pill
    window.converter.current_input = Path("fonts") / "a.ttf"
    window._set_run_status(StatusState.RUNNING)
    assert pill.run_file.text() == str(Path("fonts") / "a.ttf")
    assert pill.run_file.elide_mode is Qt.TextElideMode.ElideMiddle
    assert pill.run_title.property("state") == "running"
    window._set_run_status(StatusState.PAUSED)
    assert pill.run_file.text() == "The next font starts when you resume."
    assert pill.run_title.property("state") == "warning"
    assert pill.run_title.palette().color(pill.run_title.foregroundRole()).name() == LIGHT.warn_fg
    assert pill.accessibleDescription().startswith("Paused")


@pytest.mark.parametrize(
    ("state", "log_border", "log_text", "output_border", "output_text"),
    [
        (
            StatusState.DONE,
            LIGHT.success_btn_border,
            LIGHT.success_icon,
            LIGHT.success_btn_border,
            LIGHT.success_icon,
        ),
        (
            StatusState.CANCELLED,
            LIGHT.control_border_strong,
            LIGHT.slate,
            LIGHT.control_border_strong,
            LIGHT.slate,
        ),
        (StatusState.WARNING, LIGHT.warn_border, LIGHT.warn_fg, LIGHT.warn_border, LIGHT.warn_fg),
        # With errors View log stands out in red; Open output folder stays neutral.
        (
            StatusState.ERRORS,
            LIGHT.danger,
            LIGHT.danger,
            LIGHT.control_border_strong,
            LIGHT.slate,
        ),
        (
            StatusState.FAILED,
            LIGHT.danger,
            LIGHT.danger,
            LIGHT.control_border_strong,
            LIGHT.slate,
        ),
        (StatusState.FATAL, LIGHT.danger, LIGHT.danger, LIGHT.control_border_strong, LIGHT.slate),
    ],
)
def test_result_buttons_follow_pill_tone(
    app_font: None,
    styled_window: ConverterWindow,
    state: StatusState,
    log_border: str,
    log_text: str,
    output_border: str,
    output_text: str,
) -> None:
    window = styled_window
    window.resize(1200, 600)
    window.show()
    window._set_run_status(state)
    window.view_log_button.setEnabled(True)
    window.open_output_button.setEnabled(True)
    QApplication.processEvents()
    assert not window.status_pill.compact  # labelled buttons at this width
    for button, border, text in (
        (window.view_log_button, log_border, log_text),
        (window.open_output_button, output_border, output_text),
    ):
        image = button.grab().toImage()
        assert _near(image.pixelColor(0, button.height() // 2), border)
        assert button.palette().color(button.foregroundRole()).name() == text


def test_pause_cancel_and_resume_styles(styled_window: ConverterWindow) -> None:
    window = styled_window
    window.show()
    window.worker = object()  # type: ignore[assignment]
    window._run_state = window_module.RunState.RUNNING
    window._set_run_status(StatusState.RUNNING)
    window._update_buttons()
    QApplication.processEvents()
    pause, cancel = window.pause_button, window.cancel_button
    assert pause.text() == "Pause" and cancel.text() == "Cancel"
    assert not pause.icon().isNull() and not cancel.icon().isNull()
    assert pause.height() == cancel.height() == 38
    assert pause.palette().color(pause.backgroundRole()).name() == LIGHT.surface
    window._run_state = window_module.RunState.PAUSED
    window._set_run_status(StatusState.PAUSED)
    window._update_buttons()
    QApplication.processEvents()
    assert pause.text() == "Resume"
    assert pause.property("runPrimary") is True
    image = pause.grab().toImage()
    assert image.pixelColor(pause.width() // 2, 4).name() == LIGHT.primary
    assert pause.palette().color(pause.foregroundRole()).name() == LIGHT.on_primary
    assert cancel.property("runPrimary") is False
    window.worker = None


def test_footer_convert_disabled_palette_and_size(
    app_font: None, styled_window: ConverterWindow
) -> None:
    window = styled_window
    window.resize(1200, 880)
    window.show()
    for _ in range(3):
        QApplication.processEvents()
    assert not window.convert_button.isEnabled()
    assert window.convert_button.minimumWidth() == window.convert_button.maximumWidth()
    assert window.convert_button.height() == styles.FOOTER_HEIGHT
    assert LIGHT.footer_disabled_bg == "#e2e8f3"
    assert LIGHT.convert_disabled_text == "#6d8ec2"
    image = window.convert_button.grab().toImage()
    assert image.pixelColor(30, 22).name() == LIGHT.footer_disabled_bg
    assert (
        window.convert_button.palette().color(window.convert_button.foregroundRole()).name()
        == LIGHT.convert_disabled_text
    )
    assert not window.history_button.icon().isNull()


def test_radius_scale_replaces_single_radius() -> None:
    import inspect

    from fontvertx.gui import styles

    assert not hasattr(styles, "RADIUS")
    source = (
        inspect.getsource(styles._QSS_TEMPLATE)
        if hasattr(styles, "_QSS_TEMPLATE")
        else inspect.getsource(styles)
    )
    assert not re.search(r"border-radius: \d+px", source)


def test_footer_status_is_medium_and_convert_semibold(
    qapp: QApplication, styled_window: ConverterWindow
) -> None:
    styled_window.setStyleSheet(styles.stylesheet())
    styled_window.show()
    qapp.processEvents()
    assert styled_window.summary.text() == "Add fonts to start converting"
    for label in (styled_window.summary, styled_window.status_pill.label):
        label.ensurePolished()
        assert label.font().weight() == QFont.Weight.Medium
        assert label.font().pointSizeF() == 10.125  # 13.5px
    styled_window.convert_button.ensurePolished()
    assert styled_window.convert_button.font().weight() == QFont.Weight.DemiBold
    assert styled_window.convert_button.font().pixelSize() == 16
    # Independent settings: changing one never changes the other.
    assert styles.CONVERT_WEIGHT == 600 and styles.FOOTER_STATUS_WEIGHT == 500
