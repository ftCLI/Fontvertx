from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QEvent, QMimeData, QModelIndex, QPoint, QPointF, QRect, Qt, QUrl
from PySide6.QtGui import QColor, QDropEvent, QFont, QFontMetrics, QHelpEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionViewItem,
    QToolTip,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from fontvertx.gui import instance_tree as tree_module
from fontvertx.gui.instance_tree import CustomInstanceDialog, InstanceTree, location_text
from fontvertx.gui.styles import LIGHT, build_stylesheet
from fontvertx.inspection import AxisInfo, FontInfo, NamedInstanceInfo
from fontvertx.models import InstanceSpec

AXES = (AxisInfo("wght", 100, 400, 900), AxisInfo("wdth", 75, 100, 125))
FONT_PATH = Path("Var.ttf")


def variable_info(path: Path = FONT_PATH, outlines: str = "TrueType") -> FontInfo:
    return FontInfo(
        path,
        "SFNT",
        outlines,
        1000,
        variable=True,
        axes=AXES,
        instances=(
            NamedInstanceInfo("Regular", (("wght", 400), ("wdth", 100))),
            NamedInstanceInfo("Bold", (("wght", 700), ("wdth", 100))),
        ),
    )


@pytest.fixture
def tree(qapp: QApplication) -> InstanceTree:
    widget = InstanceTree()
    widget.resize(600, 300)
    widget.setSortingEnabled(False)
    widget.add_font(FONT_PATH, "Var", variable_info())
    # Closed and deleted by the autouse cleanup in conftest.py (shown trees left open
    # would slow down later timing-sensitive tests).
    return widget


def child_names(tree: InstanceTree) -> list[str]:
    font = tree.topLevelItem(0)
    return [font.child(i).text(0) for i in range(font.childCount())]


def stub_dialog(monkeypatch: pytest.MonkeyPatch, accepted: bool) -> list[CustomInstanceDialog]:
    """Replace the modal dialog loop so tests can set the axis values directly."""
    shown: list[CustomInstanceDialog] = []

    def fake_exec(self: CustomInstanceDialog) -> int:
        shown.append(self)
        self._boxes["wght"].setValue(555)
        return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected

    monkeypatch.setattr(CustomInstanceDialog, "exec", fake_exec)
    return shown


def test_location_text_formats_coordinates() -> None:
    assert location_text(()) == "Default"
    assert location_text((("wght", 400.0), ("wdth", 87.5))) == "wght=400, wdth=87.5"


def test_custom_dialog_previews_output_file_name(qapp: QApplication) -> None:
    named = (InstanceSpec((("wght", 700), ("wdth", 100)), "Bold"),)
    dialog = CustomInstanceDialog(AXES, named, "Var", FONT_PATH, None)  # type: ignore[arg-type]

    assert dialog.coordinates() == (("wght", 400.0), ("wdth", 100.0))
    assert dialog.filename_preview.text().startswith("Output file: ")
    assert dialog.filename_preview.text().endswith(".ttf")

    dialog._boxes["wght"].setValue(700)
    assert "Bold" in dialog.filename_preview.text()

    edit = CustomInstanceDialog(
        AXES,
        named,
        "Var",
        FONT_PATH,
        None,
        coordinates=(("wght", 300), ("wdth", 80)),  # type: ignore[arg-type]
    )
    assert edit.windowTitle() == "Edit custom instance"
    assert edit.coordinates() == (("wght", 300.0), ("wdth", 80.0))


def test_add_font_lists_named_instances_and_summary(tree: InstanceTree) -> None:
    font = tree.topLevelItem(0)

    assert child_names(tree) == ["Regular", "Bold"]
    assert font.text(4) == "2 of 2 selected"
    assert font.text(3) == "1000"
    upm_font = font.font(3)
    location_font = font.child(0).font(4)
    assert upm_font.family() == location_font.family() == "Inter"
    assert not upm_font.fixedPitch()
    assert not location_font.fixedPitch()
    assert upm_font.featureValue(QFont.Tag.fromString("tnum")) == 1
    assert location_font.featureValue(QFont.Tag.fromString("tnum")) == 1
    centered = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    assert font.textAlignment(3) == centered
    assert tree.headerItem().textAlignment(3) == centered
    assert tree.font_count() == 1
    assert tree.skipped_count() == 0
    assert tree.instance_count() == 2
    assert tree.selected_paths() == [FONT_PATH]
    assert tree.selected_outlines() == {"TrueType"}
    assert tree.check_state() == Qt.CheckState.Checked


def test_tree_row_geometry_and_scrollbar_header(tree: InstanceTree) -> None:
    tree.setStyleSheet(build_stylesheet(LIGHT))
    tree.resize(650, 90)
    font = tree.topLevelItem(0)
    font.setExpanded(True)
    tree.show()
    QTest.qWait(30)
    assert tree.header().height() == 30
    assert tree.indentation() == 24
    assert all(tree.visualItemRect(item).height() == 30 for item in (font, font.child(0)))
    assert tree.verticalScrollBar().maximum() > 0
    assert tree._scrollbar_header.cap.isVisible()
    cap = tree._scrollbar_header.cap
    cap_pos = cap.mapTo(tree, QPoint())
    bar_pos = tree.verticalScrollBar().mapTo(tree, QPoint())
    assert cap_pos.x() == bar_pos.x()
    assert cap.width() == tree.verticalScrollBar().width()
    assert cap_pos.y() + cap.height() == bar_pos.y()
    header_image = tree.grab().toImage()
    header_scale = header_image.devicePixelRatio()
    for offset in (-3, -2, -1, 0, 1, 2, 3):
        pixel = header_image.pixelColor(
            round((cap_pos.x() + offset) * header_scale), round(3 * header_scale)
        )
        assert abs(pixel.red() - QColor(LIGHT.table_header).red()) <= 12
    image = tree.viewport().grab().toImage()
    scale = image.devicePixelRatio()
    rect = tree.visualItemRect(font)
    assert image.pixelColor(round(190 * scale), round((rect.top() + 4) * scale)) == QColor(
        LIGHT.list_alt
    )
    font.child(0).setCheckState(0, Qt.CheckState.Unchecked)
    assert font.checkState(0) == Qt.CheckState.PartiallyChecked
    QTest.qWait(30)
    image = tree.viewport().grab().toImage()
    assert image.pixelColor(round(190 * scale), round((rect.top() + 4) * scale)) == QColor(
        LIGHT.list_alt
    )
    parent_index = tree.indexFromItem(font)
    tree.collapse(parent_index)
    QTest.qWait(30)
    assert not tree._scrollbar_header.cap.isVisible()
    tree.expand(parent_index)
    QTest.qWait(30)
    assert tree._scrollbar_header.cap.isVisible()
    assert tree.viewport().mask().isEmpty()
    tree.close()


def test_filtered_font_uses_group_background(qapp: QApplication) -> None:
    tree = InstanceTree()
    tree.setStyleSheet(build_stylesheet(LIGHT))
    tree.resize(650, 200)
    for label in ("A", "B", "C"):
        path = Path(f"{label}.ttf")
        tree.add_font(path, label, variable_info(path))
    tree.set_filter("B")
    tree.show()
    QTest.qWait(30)
    image = tree.viewport().grab().toImage()
    scale = image.devicePixelRatio()
    assert image.pixelColor(round(190 * scale), round(4 * scale)) == QColor(LIGHT.list_alt)
    tree.close()


def test_parent_space_toggles_children_and_expansion_preserves_checks(tree: InstanceTree) -> None:
    tree.show()
    parent = tree.topLevelItem(0)
    tree.setCurrentItem(parent)
    tree.setFocus()
    QTest.keyClick(tree, Qt.Key.Key_Space)
    assert parent.checkState(0) == Qt.CheckState.Unchecked
    assert all(parent.child(i).checkState(0) == Qt.CheckState.Unchecked for i in range(2))
    tree.expandAll()
    tree.collapseAll()
    assert all(parent.child(i).checkState(0) == Qt.CheckState.Unchecked for i in range(2))
    tree.close()


def test_checkbox_click_does_not_change_current_item(tree: InstanceTree) -> None:
    tree.setStyleSheet(build_stylesheet(LIGHT))
    parent = tree.topLevelItem(0)
    parent.setExpanded(True)
    child = parent.child(0)
    tree.show()
    tree.setCurrentItem(parent)
    QTest.qWait(30)
    index = tree.indexFromItem(child)
    option = QStyleOptionViewItem()
    option.initFrom(tree)
    option.rect = tree.visualRect(index)
    tree.itemDelegate().initStyleOption(option, index)
    indicator = tree.style().subElementRect(
        QStyle.SubElement.SE_ItemViewItemCheckIndicator, option, tree
    )
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=indicator.center())
    assert child.checkState(0) == Qt.CheckState.Unchecked
    assert tree.currentItem() is parent
    tree.close()


def test_font_without_named_instances_gets_default_instance(qapp: QApplication) -> None:
    widget = InstanceTree()
    info = FontInfo(FONT_PATH, "SFNT", "TrueType", None, variable=True, axes=AXES)
    widget.add_font(FONT_PATH, "Var", info)

    assert child_names(widget) == ["Default instance"]
    assert widget.topLevelItem(0).text(3) == "Mixed"
    assert widget.selection() == ((FONT_PATH, (InstanceSpec(()),)),)


def test_checking_children_updates_summary_selection_and_memory(tree: InstanceTree) -> None:
    changes: list[bool] = []
    tree.checksChanged.connect(lambda: changes.append(True))
    font = tree.topLevelItem(0)

    font.child(1).setCheckState(0, Qt.CheckState.Unchecked)

    assert changes
    assert font.text(4) == "1 of 2 selected"
    assert tree.instance_count() == 1
    assert tree.check_state() == Qt.CheckState.PartiallyChecked

    tree.set_all_checked(False)
    assert tree.selection() == ()
    assert tree.check_state() == Qt.CheckState.Unchecked
    assert tree.selected_outlines() == set()
    tree.set_all_checked(True)
    assert tree.instance_count() == 2


def test_rescan_restores_remembered_choices_until_forgotten(tree: InstanceTree) -> None:
    tree.topLevelItem(0).child(0).setCheckState(0, Qt.CheckState.Unchecked)

    tree.clear_fonts()
    assert tree.font_count() == 0
    assert tree.check_state() is None
    tree.add_font(FONT_PATH, "Var", variable_info())
    assert tree.instance_count() == 1

    tree.clear_fonts()
    tree.forget()
    tree.add_font(FONT_PATH, "Var", variable_info())
    assert tree.instance_count() == 2


def test_skipped_fonts_are_listed_and_hideable(tree: InstanceTree) -> None:
    info = FontInfo(Path("Static.ttf"), "SFNT", "TrueType", 1000)
    tree.add_skipped(Path("Static.ttf"), "Static", "Not a variable font", info)

    skipped = tree.topLevelItem(1)
    assert tree.skipped_count() == 1
    assert skipped.text(4) == "Not a variable font"
    tip = skipped.toolTip(0)
    assert tip.endswith("Not a variable font")
    assert tip.startswith(str(Path("Static.ttf")))
    assert "Static" not in tip.split("\n")
    assert tree.topLevelItem(0).toolTip(0) == str(FONT_PATH)
    assert not skipped.isHidden()

    tree.set_hide_incompatible(True)
    assert skipped.isHidden()
    tree.set_hide_incompatible(False)
    assert not skipped.isHidden()

    tree.set_filter("zzz")
    assert skipped.isHidden()
    assert tree.topLevelItem(0).isHidden()
    tree.set_filter("static")
    assert not skipped.isHidden()


def test_filter_finds_fonts_by_path_and_skipped_rows_by_reason(qapp: QApplication) -> None:
    tree = InstanceTree()
    tree.setSortingEnabled(False)
    path = Path("Library") / "Foundry Archive" / "Var.ttf"
    tree.add_font(path, "Var", variable_info(path))
    info = FontInfo(Path("Plain.ttf"), "SFNT", "TrueType", 1000)
    tree.add_skipped(Path("Elsewhere") / "Plain.ttf", "Plain", "Not a variable font", info)
    font, skipped = tree.topLevelItem(0), tree.topLevelItem(1)
    # Instance rows and the summary carry no tooltips: their cells show everything.
    for child in (font.child(i) for i in range(font.childCount())):
        assert all(child.toolTip(column) == "" for column in range(tree.columnCount()))
    assert font.toolTip(tree_module._LOCATION_COLUMN) == ""
    assert skipped.toolTip(tree_module._LOCATION_COLUMN) == ""
    expected = f"{Path('Elsewhere') / 'Plain.ttf'}\nNot a variable font"
    assert skipped.toolTip(0) == expected
    assert font.toolTip(0) == str(path)

    tree.set_filter("foundry arch")  # part of the path only
    assert not font.isHidden()
    assert skipped.isHidden()
    tree.set_filter("elsewhere")
    assert font.isHidden()
    assert not skipped.isHidden()
    tree.set_filter("variable font")  # the skipped row's reason
    assert font.isHidden()
    assert not skipped.isHidden()
    tree.set_filter("wght=700")  # a location
    assert not font.isHidden()
    assert font.child(0).isHidden()
    assert not font.child(1).isHidden()
    tree.set_filter("regular")  # a name
    assert not font.child(0).isHidden()
    assert font.child(1).isHidden()
    tree.close()
    tree.deleteLater()


def test_location_tooltip_only_when_truncated(tree: InstanceTree) -> None:
    _shown_tree(tree)
    font = tree.topLevelItem(0)
    font.setExpanded(True)
    child = font.child(0)
    tree.resize(1000, 300)
    tree.header().resizeSection(tree_module._LOCATION_COLUMN, 400)
    QApplication.processEvents()
    index = _location(tree, child)
    center = tree.visualRect(index).center()
    assert tree.elided_location_at(center) == ""
    assert tree.elided_location_at(tree.visualRect(_location(tree, font)).center()) == ""
    assert tree.elided_location_at(tree.visualRect(tree.indexFromItem(child, 0)).center()) == ""

    tree.header().resizeSection(tree_module._LOCATION_COLUMN, 40)
    QApplication.processEvents()
    center = tree.visualRect(index).center()
    assert tree.elided_location_at(center) == child.text(tree_module._LOCATION_COLUMN)
    shown: list[str] = []
    original = QToolTip.showText
    try:
        QToolTip.showText = lambda _pos, text, *_args: shown.append(text)  # type: ignore[method-assign]
        event = QHelpEvent(QEvent.Type.ToolTip, center, tree.viewport().mapToGlobal(center))
        assert tree.viewportEvent(event)
    finally:
        QToolTip.showText = original  # type: ignore[method-assign]
    assert shown == [child.text(tree_module._LOCATION_COLUMN)]


def test_filter_keeps_matching_children_visible(tree: InstanceTree) -> None:
    font = tree.topLevelItem(0)

    tree.set_filter("bold")
    assert not font.isHidden()
    assert font.child(0).isHidden()
    assert not font.child(1).isHidden()

    tree.set_filter("var")
    assert not font.child(0).isHidden()

    tree.set_filter("")
    assert not font.child(0).isHidden()


def test_auto_expand_only_for_single_font(tree: InstanceTree) -> None:
    font = tree.topLevelItem(0)
    tree.auto_expand()
    assert font.isExpanded()

    font.setExpanded(False)
    tree.add_font(Path("Other.ttf"), "Other", variable_info(Path("Other.ttf"), "PostScript"))
    tree.auto_expand()
    assert not font.isExpanded()
    assert tree.selected_outlines() == {"TrueType", "PostScript"}


def test_add_custom_instance_selects_and_remembers_it(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = stub_dialog(monkeypatch, accepted=True)
    assert not tree.can_add()
    tree.add_custom()
    assert shown == []

    tree.setCurrentItem(tree.topLevelItem(0))
    assert tree.can_add()
    assert not tree.can_remove()
    tree.add_custom()

    font = tree.topLevelItem(0)
    assert child_names(tree) == ["Regular", "Bold", "Custom instance"]
    assert tree.currentItem() is font.child(2)
    assert tree.can_remove()
    assert font.text(4) == "3 of 3 selected"
    assert len(shown[0]._named_instances) == 2

    tree.clear_fonts()
    tree.add_font(FONT_PATH, "Var", variable_info())
    assert child_names(tree) == ["Regular", "Bold", "Custom instance"]


def test_instance_order_under_a_sorted_tree(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sorting orders the fonts. Under each font the named instances come first, in the
    font's order; custom ones follow, sorted by location when the tree is sorted by
    Location (in its direction), otherwise in the order they were added."""
    sorted_tree = InstanceTree()  # sorting on, as in the window
    assert sorted_tree.isSortingEnabled()
    sorted_tree.add_font(FONT_PATH, "Var", variable_info())
    sorted_tree.add_font(Path("Another.ttf"), "Another", variable_info(Path("Another.ttf")))
    values = iter([555, 150, 800])

    def fake_exec(self: CustomInstanceDialog) -> int:
        self._boxes["wght"].setValue(next(values))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(CustomInstanceDialog, "exec", fake_exec)
    font = next(
        sorted_tree.topLevelItem(i)
        for i in range(sorted_tree.topLevelItemCount())
        if sorted_tree.topLevelItem(i).text(0) == "Var"
    )
    for _ in range(3):
        sorted_tree.setCurrentItem(font)
        sorted_tree.add_custom()

    def rows() -> list[tuple[str, str]]:
        return [(font.child(i).text(0), font.child(i).text(4)) for i in range(font.childCount())]

    def expected(*custom_weights: int) -> list[tuple[str, str]]:
        named = [("Regular", 400), ("Bold", 700)]
        custom = [("Custom instance", weight) for weight in custom_weights]
        return [
            (name, location_text((("wght", weight), ("wdth", 100))))
            for name, weight in named + custom
        ]

    added = expected(555, 150, 800)
    assert rows() == added
    for column, order, result in (
        (0, Qt.SortOrder.DescendingOrder, added),
        (4, Qt.SortOrder.AscendingOrder, expected(150, 555, 800)),
        (4, Qt.SortOrder.DescendingOrder, expected(800, 555, 150)),
        (1, Qt.SortOrder.AscendingOrder, added),
        (0, Qt.SortOrder.AscendingOrder, added),
    ):
        sorted_tree.sortByColumn(column, order)
        assert rows() == result, (column, order)
    # The fonts themselves follow the sort.
    sorted_tree.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    assert [sorted_tree.topLevelItem(i).text(0) for i in range(2)] == ["Var", "Another"]


@pytest.mark.parametrize("accepted", [True, False])
def test_custom_instance_dialog_is_deleted_once_closed(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch, accepted: bool
) -> None:
    window = QWidget()  # the dialog's parent, as the main window in the app
    window.setLayout(QVBoxLayout())
    window.layout().addWidget(tree)
    shown = stub_dialog(monkeypatch, accepted=accepted)
    tree.setCurrentItem(tree.topLevelItem(0))
    tree.add_custom()
    assert shown[0].parent() is window
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(shown[0])
    assert window.findChildren(CustomInstanceDialog) == []
    expected = ["Regular", "Bold", "Custom instance"] if accepted else ["Regular", "Bold"]
    assert child_names(tree) == expected


def test_add_custom_instance_cancelled_or_without_axes(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_dialog(monkeypatch, accepted=False)
    tree.setCurrentItem(tree.topLevelItem(0))
    tree.add_custom()
    assert child_names(tree) == ["Regular", "Bold"]

    stub_dialog(monkeypatch, accepted=True)
    no_axes = InstanceTree()
    no_axes.add_font(FONT_PATH, "Var", FontInfo(FONT_PATH, "SFNT", "TrueType", 1000, variable=True))
    no_axes.setCurrentItem(no_axes.topLevelItem(0))
    no_axes.add_custom()
    assert child_names(no_axes) == ["Default instance"]


def test_custom_instance_matching_existing_selects_it(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[1]))

    def fake_exec(self: CustomInstanceDialog) -> int:
        self._boxes["wght"].setValue(700)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(CustomInstanceDialog, "exec", fake_exec)
    font = tree.topLevelItem(0)
    font.child(1).setCheckState(0, Qt.CheckState.Unchecked)
    tree.setCurrentItem(font)

    tree.add_custom()

    assert child_names(tree) == ["Regular", "Bold"]
    assert font.child(1).checkState(0) == Qt.CheckState.Checked
    assert messages == ["Named instance already exists"]


def test_edit_custom_instance_updates_it_and_rejects_duplicates(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[1]))
    stub_dialog(monkeypatch, accepted=True)
    font = tree.topLevelItem(0)
    tree.setCurrentItem(font)
    tree.add_custom()
    custom = font.child(2)
    custom.setCheckState(0, Qt.CheckState.Unchecked)

    tree.edit_custom()
    assert custom.data(0, tree_module._SPEC_ROLE).coordinates[0] == ("wght", 555.0)
    assert custom.text(1) == ""
    assert custom.text(4).startswith("wght=555")

    def to_bold(self: CustomInstanceDialog) -> int:
        self._boxes["wght"].setValue(700)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(CustomInstanceDialog, "exec", to_bold)
    tree.edit_custom()
    assert messages == ["Instance already exists"]
    assert custom.data(0, tree_module._SPEC_ROLE).coordinates[0] == ("wght", 555.0)

    tree.setCurrentItem(font.child(0))
    tree.edit_custom()
    assert messages == ["Instance already exists"]


def test_double_click_edits_custom_only(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = stub_dialog(monkeypatch, accepted=True)
    font = tree.topLevelItem(0)
    tree.setCurrentItem(font)
    tree.add_custom()
    shown.clear()

    tree._on_item_double_clicked(font.child(0), 0)
    assert shown == []
    tree._on_item_double_clicked(font.child(2), 0)
    assert len(shown) == 1


def test_remove_custom_instance(tree: InstanceTree, monkeypatch: pytest.MonkeyPatch) -> None:
    stub_dialog(monkeypatch, accepted=True)
    font = tree.topLevelItem(0)
    tree.setCurrentItem(font)
    tree.add_custom()
    actions: list[bool] = []
    tree.actionsChanged.connect(lambda: actions.append(True))

    tree.setCurrentItem(font.child(0))
    tree.remove_custom()
    assert child_names(tree) == ["Regular", "Bold", "Custom instance"]

    tree.setCurrentItem(font)
    tree.remove_custom()
    assert child_names(tree) == ["Regular", "Bold", "Custom instance"]

    tree.setCurrentItem(font.child(2))
    tree.remove_custom()
    assert child_names(tree) == ["Regular", "Bold"]
    assert font.text(4) == "2 of 2 selected"
    assert actions


class FakeMenu:
    """Stands in for QMenu: records the labels and returns the ``choice`` action."""

    shown: list[list[str]] = []
    choice: int | None = None

    def __init__(self, parent: Any) -> None:
        self.labels: list[str] = []
        self.actions: list[object] = []

    def addAction(self, text: str) -> Any:
        action = object()
        self.labels.append(text)
        self.actions.append(action)
        return action

    def exec(self, pos: Any) -> Any:
        FakeMenu.shown.append(self.labels)
        return None if FakeMenu.choice is None else self.actions[FakeMenu.choice]


@pytest.fixture
def fake_menu(monkeypatch: pytest.MonkeyPatch) -> type[FakeMenu]:
    FakeMenu.shown = []
    FakeMenu.choice = None
    monkeypatch.setattr(tree_module, "QMenu", FakeMenu)
    return FakeMenu


def _tree_with_custom(tree: InstanceTree, monkeypatch: pytest.MonkeyPatch) -> QTreeWidgetItem:
    """Add one custom instance (font.child(2)) and show the expanded tree."""
    stub_dialog(monkeypatch, accepted=True)
    font = tree.topLevelItem(0)
    tree.setCurrentItem(font)
    tree.add_custom()
    tree.expandAll()
    tree.show()
    QApplication.processEvents()
    return font


def test_context_menu_shows_only_the_row_actions(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch, fake_menu: type[FakeMenu]
) -> None:
    font = _tree_with_custom(tree, monkeypatch)
    named, custom = font.child(0), font.child(2)
    calls: list[str] = []
    monkeypatch.setattr(tree, "add_custom", lambda: calls.append("add"))
    monkeypatch.setattr(tree, "edit_custom", lambda: calls.append("edit"))
    monkeypatch.setattr(tree, "remove_custom", lambda: calls.append("remove"))

    def point(item: QTreeWidgetItem) -> QPoint:
        return tree.visualItemRect(item).center()

    tree._show_menu(point(font))
    tree._show_menu(point(custom))
    tree._show_menu(point(named))
    assert fake_menu.shown == [
        ["Add custom instance…"],
        ["Edit custom instance…", "Remove instance"],
    ]
    assert calls == []

    for item, choice, expected in (
        (font, 0, "add"),
        (custom, 0, "edit"),
        (custom, 1, "remove"),
    ):
        fake_menu.choice = choice
        tree._show_menu(point(item))
        assert calls[-1] == expected
    assert len(calls) == 3

    tree._show_menu(tree.viewport().rect().bottomRight())
    assert len(calls) == 3


def test_keyboard_context_menu_matches_the_row(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch, fake_menu: type[FakeMenu]
) -> None:
    font = _tree_with_custom(tree, monkeypatch)
    tree.setFocus()
    for item in (font, font.child(2), font.child(0)):
        tree.setCurrentItem(item)
        QTest.keyClick(tree, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
    assert fake_menu.shown == [
        ["Add custom instance…"],
        ["Edit custom instance…", "Remove instance"],
    ]


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_enter_acts_on_each_row_type(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch, key: Qt.Key
) -> None:
    font = _tree_with_custom(tree, monkeypatch)
    edits: list[QTreeWidgetItem | None] = []
    monkeypatch.setattr(tree, "edit_custom", lambda: edits.append(tree.currentItem()))
    tree.setFocus()

    tree.setCurrentItem(font)
    QTest.keyClick(tree, key)
    assert not font.isExpanded()
    QTest.keyClick(tree, key)
    assert font.isExpanded()
    assert edits == []

    named = font.child(0)
    tree.setCurrentItem(named)
    QTest.keyClick(tree, key)
    assert edits == []
    assert font.isExpanded()
    assert tree.currentItem() is named

    custom = font.child(2)
    tree.setCurrentItem(custom)
    QTest.keyClick(tree, key)
    assert edits == [custom]


def test_double_click_acts_on_each_row_type(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    font = _tree_with_custom(tree, monkeypatch)
    edits: list[QTreeWidgetItem | None] = []
    monkeypatch.setattr(tree, "edit_custom", lambda: edits.append(tree.currentItem()))

    tree.itemDoubleClicked.emit(font.child(0), 0)
    assert edits == []
    tree.itemDoubleClicked.emit(font.child(2), 0)
    assert edits == [font.child(2)]
    tree.itemDoubleClicked.emit(font, 0)
    assert edits == [font.child(2)]
    assert tree.expandsOnDoubleClick()


def test_custom_chip_on_custom_instances_only(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    font = _tree_with_custom(tree, monkeypatch)
    column = tree_module._FORMAT_COLUMN
    delegate = tree.itemDelegateForColumn(column)
    assert isinstance(delegate, tree_module.InstanceBadgeDelegate)

    def chip(item: QTreeWidgetItem) -> str:
        option = QStyleOptionViewItem()
        delegate.initStyleOption(option, tree.indexFromItem(item, column))
        return option.text

    assert chip(font) == "SFNT"
    assert chip(font.child(0)) == ""
    assert chip(font.child(1)) == ""
    assert chip(font.child(2)) == tree_module.CUSTOM_CHIP_LABEL
    # Painted only: the cell stays empty, so the filter and sorting ignore it.
    assert font.child(2).text(column) == ""
    tree.set_filter("custom")
    assert not font.child(2).isHidden()
    assert font.child(0).isHidden()
    tree.set_filter("")
    assert tree.grab().toImage().width() > 0


def test_keyboard_context_menu_opens_for_selected_instance(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree.show()
    tree.expandAll()
    child = tree.topLevelItem(0).child(0)
    tree.setCurrentItem(child)
    tree.setFocus()
    QApplication.processEvents()
    positions: list[object] = []
    monkeypatch.setattr(tree, "_show_menu", positions.append)
    QTest.keyClick(tree, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
    assert positions == [tree.visualItemRect(child).center()]


def test_drop_emits_existing_paths_only(tree: InstanceTree, tmp_path: Path) -> None:
    received: list[list[str]] = []
    tree.paths_dropped.connect(received.append)
    font = tmp_path / "font.ttf"
    font.touch()
    mimes: list[QMimeData] = []

    def drop(path: Path) -> QDropEvent:
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        mimes.append(mime)
        return QDropEvent(
            QPointF(1, 1),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    accepted = drop(font)
    tree.dropEvent(accepted)
    ignored = drop(tmp_path / "missing.ttf")
    tree.dropEvent(ignored)

    assert [[Path(p) for p in paths] for paths in received] == [[font]]
    assert accepted.isAccepted()
    assert not ignored.isAccepted()


def test_tree_rendering(qapp: QApplication) -> None:
    widget = InstanceTree()
    widget.resize(600, 300)
    empty = widget.grab().toImage()
    assert empty.width() == 600

    info = FontInfo(Path("Static.ttf"), "SFNT", "TrueType", 1000)
    widget.add_skipped(Path("Static.ttf"), "Static", "Not a variable font", info)
    widget.add_font(FONT_PATH, "Var", variable_info())
    muted = widget.topLevelItem(0).foreground(0).color()
    assert muted.isValid()
    assert widget.grab().toImage().width() == 600


# -- "+ Instance" row action ------------------------------------------------------------


def _location(tree: InstanceTree, item: QTreeWidgetItem) -> QModelIndex:
    return tree.indexFromItem(item, tree_module._LOCATION_COLUMN)


def _shown_tree(tree: InstanceTree) -> InstanceTree:
    tree.setStyleSheet(build_stylesheet(LIGHT))
    tree.resize(700, 300)
    tree.show()
    QTest.qWait(20)
    return tree


def _hover(tree: InstanceTree, position: QPoint) -> None:
    viewport = tree.viewport()
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(position),
        QPointF(viewport.mapToGlobal(position)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(viewport, event)


def _count_adds(tree: InstanceTree, monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    calls: list[bool] = []
    monkeypatch.setattr(tree, "add_custom", lambda: calls.append(True))
    return calls


def test_add_action_is_painted_and_hit_tested_from_one_rect(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    _shown_tree(tree)
    font = tree.topLevelItem(0)
    tree.setCurrentItem(font)
    cell = tree.visualRect(_location(tree, font))
    rect = tree.add_action_rect_for(_location(tree, font))
    assert rect == tree_module.add_action_rect(cell)
    assert tree.add_action_state(_location(tree, font)) == tree_module.ACTION_SOLID
    assert rect.height() == tree_module.ADD_ACTION_HEIGHT
    assert rect.left() == cell.left() + tree_module.ADD_ACTION_INSET
    assert rect.center().y() == pytest.approx(cell.center().y(), abs=1)
    assert cell.contains(rect)
    calls = _count_adds(tree, monkeypatch)

    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert calls == [True]
    for outside in (
        QPoint(rect.right() + 3, rect.center().y()),
        QPoint(cell.right() - 4, cell.center().y()),
        QPoint(rect.center().x(), cell.top() + 1),
    ):
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=outside)
    assert calls == [True]
    assert tree.currentItem() is font


def test_add_action_paints_accent_button_and_pressed_tint(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    _shown_tree(tree)
    font = tree.topLevelItem(0)
    tree.setCurrentItem(font)
    QTest.qWait(20)
    rect = tree.add_action_rect_for(_location(tree, font))
    image = tree.viewport().grab().toImage()
    scale = image.devicePixelRatio()

    def pixel(x: int, y: int) -> QColor:
        return image.pixelColor(round(x * scale), round(y * scale))

    border = pixel(rect.left(), rect.center().y())
    assert abs(border.red() - QColor(LIGHT.accent).red()) <= 10
    assert abs(border.blue() - QColor(LIGHT.accent).blue()) <= 10
    assert pixel(rect.left() + 3, rect.center().y()) == QColor(LIGHT.surface)

    _count_adds(tree, monkeypatch)
    QTest.mousePress(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert tree.is_add_action_pressed(_location(tree, font))
    QTest.qWait(20)
    image = tree.viewport().grab().toImage()
    assert pixel(rect.left() + 3, rect.center().y()) == QColor(LIGHT.row_selection)
    QTest.mouseRelease(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert not tree.is_add_action_pressed(_location(tree, font))


def test_release_outside_the_button_does_not_add(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    _shown_tree(tree)
    font = tree.topLevelItem(0)
    tree.setCurrentItem(font)
    rect = tree.add_action_rect_for(_location(tree, font))
    calls = _count_adds(tree, monkeypatch)
    QTest.mousePress(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    QTest.mouseRelease(
        tree.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(rect.right() + 20, rect.top())
    )
    assert calls == []
    assert not tree.is_add_action_pressed(_location(tree, font))


def test_ghost_action_on_hover_makes_row_current_then_adds(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    other_path = Path("Other.ttf")
    tree.add_font(other_path, "Other", variable_info(other_path))
    _shown_tree(tree)
    first, second = tree.topLevelItem(0), tree.topLevelItem(1)
    tree.setCurrentItem(first)
    rect = tree.add_action_rect_for(_location(tree, second))
    assert tree.add_action_state(_location(tree, second)) is None

    _hover(tree, rect.center())
    assert tree.add_action_state(_location(tree, second)) == tree_module.ACTION_GHOST
    assert tree.add_action_state(_location(tree, first)) == tree_module.ACTION_SOLID
    assert tree.viewport().cursor().shape() == Qt.CursorShape.PointingHandCursor
    _hover(tree, QPoint(rect.right() + 30, rect.center().y()))
    assert tree.viewport().cursor().shape() != Qt.CursorShape.PointingHandCursor
    assert tree.add_action_state(_location(tree, second)) == tree_module.ACTION_GHOST

    _hover(tree, rect.center())
    stub_dialog(monkeypatch, accepted=True)
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert [second.child(i).text(0) for i in range(second.childCount())][-1] == "Custom instance"
    assert first.childCount() == 2
    assert tree.currentItem().parent() is second

    QApplication.sendEvent(tree.viewport(), QEvent(QEvent.Type.Leave))
    assert tree.add_action_state(_location(tree, first)) is None
    assert tree.add_action_state(_location(tree, second)) == tree_module.ACTION_SOLID


def test_hovering_an_instance_row_shows_no_ghost(tree: InstanceTree) -> None:
    _shown_tree(tree)
    tree.setCurrentIndex(QModelIndex())
    font = tree.topLevelItem(0)
    font.setExpanded(True)
    child = font.child(0)
    _hover(tree, tree.visualRect(_location(tree, child)).center())
    assert tree.add_action_state(_location(tree, font)) is None
    assert tree.add_action_state(_location(tree, child)) is None


def test_current_instance_puts_the_action_on_its_font(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    _shown_tree(tree)
    font = tree.topLevelItem(0)
    font.setExpanded(True)
    tree.setCurrentItem(font.child(1))
    assert tree.add_action_state(_location(tree, font)) == tree_module.ACTION_SOLID
    assert tree.add_action_state(_location(tree, font.child(1))) is None
    stub_dialog(monkeypatch, accepted=True)
    rect = tree.add_action_rect_for(_location(tree, font))
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert child_names(tree) == ["Regular", "Bold", "Custom instance"]


def test_no_action_when_nothing_can_be_added(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    info = FontInfo(Path("Static.ttf"), "SFNT", "TrueType", 1000)
    tree.add_skipped(Path("Static.ttf"), "Static", "Not a variable font", info)
    _shown_tree(tree)
    font, skipped = tree.topLevelItem(0), tree.topLevelItem(1)
    calls = _count_adds(tree, monkeypatch)
    QApplication.sendEvent(tree.viewport(), QEvent(QEvent.Type.Leave))

    # Nothing current and nothing hovered: no button on the font row. (A click there
    # would first hover it, which shows the ghost: see the ghost test.)
    tree.setCurrentIndex(QModelIndex())
    assert not tree.can_add()
    assert tree.add_action_state(_location(tree, font)) is None

    tree.setCurrentItem(skipped)
    assert not tree.can_add()
    assert tree.add_action_state(_location(tree, font)) is None
    assert tree.add_action_state(_location(tree, skipped)) is None
    _hover(tree, tree.add_action_rect_for(_location(tree, skipped)).center())
    assert tree.add_action_state(_location(tree, skipped)) is None
    QTest.mouseClick(
        tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=tree.add_action_rect_for(_location(tree, skipped)).center(),
    )
    assert calls == []
    tree.setFocus()
    QTest.keyClick(tree, Qt.Key.Key_Insert)
    assert calls == []


def test_insert_key_adds_custom_instance(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    _shown_tree(tree)
    tree.activateWindow()
    font = tree.topLevelItem(0)
    font.setExpanded(True)
    calls = _count_adds(tree, monkeypatch)
    tree.setFocus()
    for current in (font, font.child(0)):
        tree.setCurrentItem(current)
        QTest.keyClick(tree, Qt.Key.Key_Insert)
    assert calls == [True, True]


def test_add_action_tooltip_names_the_shortcut(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    _shown_tree(tree)
    font = tree.topLevelItem(0)
    tree.setCurrentItem(font)
    rect = tree.add_action_rect_for(_location(tree, font))
    event = QHelpEvent(
        QEvent.Type.ToolTip, rect.center(), tree.viewport().mapToGlobal(rect.center())
    )
    assert tree.viewportEvent(event)
    assert QToolTip.text() == "Add custom instance (Ins)"
    QToolTip.hideText()
    shown: list[str] = []
    monkeypatch.setattr(QToolTip, "showText", lambda _pos, text, *_args: shown.append(text))
    outside = QPoint(rect.right() + 30, rect.center().y())
    event = QHelpEvent(QEvent.Type.ToolTip, outside, tree.viewport().mapToGlobal(outside))
    tree.viewportEvent(event)
    assert "Add custom instance (Ins)" not in shown


def test_double_click_on_action_does_not_toggle_the_row(
    tree: InstanceTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    _shown_tree(tree)
    font = tree.topLevelItem(0)
    tree.setCurrentItem(font)
    calls = _count_adds(tree, monkeypatch)
    rect = tree.add_action_rect_for(_location(tree, font))
    # What the platform sends for a double click: QTest.mouseDClick alone is only the
    # second press.
    QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    QTest.mouseRelease(tree.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert not font.isExpanded()
    assert calls == [True, True]


def test_narrow_location_column_elides_text_not_button(tree: InstanceTree, app_font: None) -> None:
    metrics = QFontMetrics(QApplication.font())
    text = "12 of 12 selected"
    wide = QRect(0, 0, tree_module.LOCATION_MIN_WIDTH, 30)
    narrow = QRect(0, 0, 130, 30)
    tiny = QRect(0, 0, 60, 30)
    button_width = tree_module.add_action_rect(wide).width()
    for cell in (wide, narrow, tiny):
        assert tree_module.add_action_rect(cell).width() == button_width
    rect, visible = tree_module.add_action_text_layout(wide, text, metrics)
    assert visible == text
    assert rect.left() > tree_module.add_action_rect(wide).right()
    rect, visible = tree_module.add_action_text_layout(narrow, text, metrics)
    assert visible != text and visible.endswith("…")
    assert rect.left() > tree_module.add_action_rect(narrow).right()
    assert rect.right() < narrow.right()
    _, visible = tree_module.add_action_text_layout(tiny, text, metrics)
    assert visible == ""

    _shown_tree(tree)
    tree.setCurrentItem(tree.topLevelItem(0))
    tree.header().resizeSection(tree_module._LOCATION_COLUMN, 120)
    QTest.qWait(20)
    assert not tree.viewport().grab().isNull()


def test_location_column_fits_action_and_summary(tree: InstanceTree, app_font: None) -> None:
    assert tree.columnWidth(tree_module._LOCATION_COLUMN) >= tree_module.LOCATION_MIN_WIDTH
    font = tree.topLevelItem(0)
    alignment = Qt.AlignmentFlag(font.textAlignment(tree_module._LOCATION_COLUMN))
    assert alignment & Qt.AlignmentFlag.AlignRight
    cell = QRect(0, 0, tree_module.LOCATION_MIN_WIDTH, 30)
    metrics = QFontMetrics(QApplication.font())
    for text in ("12 of 12 selected", "120 of 120 selected"):
        _, visible = tree_module.add_action_text_layout(cell, text, metrics)
        assert visible == text
    tree.header().resizeSection(tree_module._LOCATION_COLUMN, 300)
    tree.add_font(Path("Second.ttf"), "Second", variable_info(Path("Second.ttf")))
    assert tree.columnWidth(tree_module._LOCATION_COLUMN) >= tree_module.LOCATION_MIN_WIDTH


def test_font_column_fills_and_location_keeps_its_width(tree: InstanceTree) -> None:
    _shown_tree(tree)
    header = tree.header()
    location = tree_module._LOCATION_COLUMN

    def font_fills() -> bool:
        others = sum(header.sectionSize(c) for c in range(1, tree.columnCount()))
        return header.sectionSize(0) == tree.viewport().width() - others

    width = header.sectionSize(location)
    assert tree_module.LOCATION_MIN_WIDTH <= width <= tree_module.LOCATION_MAX_WIDTH
    assert font_fills()
    tree.resize(1000, 300)
    QApplication.processEvents()
    assert header.sectionSize(location) == width and font_fills()
    tree.add_font(Path("Second.ttf"), "Second", variable_info(Path("Second.ttf")))
    assert font_fills()
    # Dragging the Font / instance border: Location compensates, total width unchanged.
    start = header.sectionViewportPosition(0) + header.sectionSize(0) - 1
    before = header.sectionSize(location)
    for kind, x, buttons in (
        (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, start - 50, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, start - 50, Qt.MouseButton.NoButton),
    ):
        pos = QPointF(x, header.height() / 2)
        button = (
            Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        )
        QApplication.sendEvent(
            header.viewport(),
            QMouseEvent(
                kind,
                pos,
                header.viewport().mapToGlobal(pos),
                button,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
    assert header.sectionSize(location) == before + 50
    assert font_fills()
    assert tree.horizontalScrollBar().maximum() == 0
    tree.close()


def test_summary_text_does_not_move_when_the_action_appears(
    tree: InstanceTree, app_font: None
) -> None:
    """The right edge of "N of N selected" is the same with and without the button."""
    other = Path("Other.ttf")
    tree.add_font(other, "Other", variable_info(other))
    _shown_tree(tree)
    first, second = tree.topLevelItem(0), tree.topLevelItem(1)
    tree.setCurrentItem(first)
    QTest.qWait(20)
    image = tree.viewport().grab().toImage()
    scale = image.devicePixelRatio()

    def text_right(item: QTreeWidgetItem) -> int:
        cell = tree.visualRect(_location(tree, item))
        background = image.pixelColor(
            round((cell.right() - 1) * scale), round(cell.top() * scale + 3)
        )
        for x in range(round(cell.right() * scale), round(cell.left() * scale), -1):
            column = (
                image.pixelColor(x, round(cell.center().y() * scale) + dy) for dy in (-3, 0, 3)
            )
            if any(abs(c.red() - background.red()) > 40 for c in column):
                return x
        return -1

    assert tree.add_action_state(_location(tree, first)) == tree_module.ACTION_SOLID
    assert tree.add_action_state(_location(tree, second)) is None
    assert abs(text_right(first) - text_right(second)) <= 1


# -- Custom instance dialog: output file preview -------------------------------------

LONG_PATH = Path(
    "Supercalifragilistic-Expialidocious_Variable-Display-Condensed-Extra-Long-Family-Name"
    "-With-Many-Hyphenated-Parts-For-Wrapping-Tests.ttf"
)


def _shown_dialog(path: Path) -> CustomInstanceDialog:
    dialog = CustomInstanceDialog(AXES, (), "Var", path, None)  # type: ignore[arg-type]
    dialog.setStyleSheet(build_stylesheet(LIGHT))
    dialog.show()
    QTest.qWait(30)
    return dialog


def _axis_row_heights(dialog: CustomInstanceDialog) -> list[int]:
    return [box.parentWidget().height() for box in dialog._boxes.values()]


def _assert_preview_fits(dialog: CustomInstanceDialog) -> None:
    label = dialog.filename_preview
    two_lines = tree_module.PREVIEW_MIN_LINES * label.fontMetrics().lineSpacing()
    assert label.height() >= two_lines
    assert label.height() >= label.heightForWidth(label.width())
    layout = dialog.layout()
    assert layout is not None
    assert dialog.height() >= layout.minimumSize().height()
    for box in dialog._boxes.values():
        field = box.parentWidget()
        assert field.height() >= field.sizeHint().height()
    for button in dialog.findChildren(QPushButton):
        if button.isVisible():
            assert button.height() >= button.minimumSizeHint().height()


def test_long_preview_grows_the_dialog_not_the_axis_rows(
    qapp: QApplication, app_font: None
) -> None:
    short = _shown_dialog(FONT_PATH)
    short_rows = _axis_row_heights(short)
    long = _shown_dialog(LONG_PATH)
    try:
        label = long.filename_preview
        assert label.heightForWidth(label.width()) > 2 * label.fontMetrics().lineSpacing()
        _assert_preview_fits(long)
        assert _axis_row_heights(long) == short_rows
        for value in (555, 123.45, 900):
            long._boxes["wght"].setValue(value)
            QTest.qWait(20)
            _assert_preview_fits(long)
            assert _axis_row_heights(long) == short_rows
        long.resize(long.minimumWidth(), long.height())
        QTest.qWait(20)
        _assert_preview_fits(long)
        assert _axis_row_heights(long) == short_rows
    finally:
        short.close()
        long.close()


def test_short_preview_reserves_two_lines(qapp: QApplication, app_font: None) -> None:
    dialog = _shown_dialog(FONT_PATH)
    try:
        label = dialog.filename_preview
        assert label.heightForWidth(label.width()) <= 2 * label.fontMetrics().lineSpacing()
        assert label.height() == label.minimumHeight()
        _assert_preview_fits(dialog)
        height = dialog.height()
        for value in (555, 700, 100):
            dialog._boxes["wght"].setValue(value)
            QTest.qWait(20)
            assert dialog.height() == height
        alignment = label.alignment()
        assert alignment & Qt.AlignmentFlag.AlignTop
        assert alignment & Qt.AlignmentFlag.AlignLeft
    finally:
        dialog.close()


def test_preview_keeps_the_full_file_name(qapp: QApplication) -> None:
    dialog = CustomInstanceDialog(AXES, (), "Var", LONG_PATH, None)  # type: ignore[arg-type]
    shown = dialog.filename_preview.text().replace("​", "")
    assert shown.startswith("Output file: Supercalifragilistic-Expialidocious_Variable")
    assert shown.endswith("Wrapping-Tests-wght400wdth100.ttf") or shown.endswith(".ttf")
    assert "…" not in shown
    assert tree_module._wrappable("a-b_c.ttf") == "a-​b_​c​.ttf"


def _preview_lines(dialog: CustomInstanceDialog) -> int:
    """Lines the file-name preview needs at its current width (measured, never assumed:
    where the name wraps depends on each system's text metrics)."""
    label = dialog.filename_preview
    return round(label.heightForWidth(label.width()) / label.fontMetrics().lineSpacing())


def _edit_axes_and_measure(path: Path) -> tuple[CustomInstanceDialog, int, int, int, list[int]]:
    """Show the dialog, then edit the axis values (a longer file name).

    Returns the dialog, its height when shown, the preview lines before and after the
    edit, and the axis row heights when shown.
    """
    dialog = _shown_dialog(path)
    rows = _axis_row_heights(dialog)
    height = dialog.height()
    lines_before = _preview_lines(dialog)
    dialog._boxes["wght"].setValue(123.45)
    dialog._boxes["wdth"].setValue(87.25)
    QTest.qWait(30)
    return dialog, height, lines_before, _preview_lines(dialog), rows


@pytest.mark.parametrize(
    "path",
    [Path("FFFFF-Var.ttf"), Path("-".join(["Abcd"] * 9) + ".ttf")],
)
def test_preview_line_change_after_show_grows_the_dialog_only_when_needed(
    qapp: QApplication, app_font: None, path: Path
) -> None:
    dialog, height, lines_before, lines_after, rows = _edit_axes_and_measure(path)
    try:
        # The preview always has room for PREVIEW_MIN_LINES lines: the dialog grows only
        # when the edited name needs more lines than it already had room for.
        room = max(lines_before, tree_module.PREVIEW_MIN_LINES)
        if lines_after > room:
            assert dialog.height() > height
        else:
            assert dialog.height() == height
        _assert_preview_fits(dialog)
        assert _axis_row_heights(dialog) == rows
    finally:
        dialog.close()


def test_preview_gaining_a_line_after_show_grows_the_dialog(
    qapp: QApplication, app_font: None
) -> None:
    # Find, with this system's text metrics, a name whose preview gains a line beyond
    # the reserved room after the edit, so the "grows" case is covered everywhere.
    for segments in range(6, 40):
        path = Path("-".join(["Abcd"] * segments) + ".ttf")
        dialog, height, lines_before, lines_after, rows = _edit_axes_and_measure(path)
        try:
            if lines_after > max(lines_before, tree_module.PREVIEW_MIN_LINES):
                assert dialog.height() > height
                _assert_preview_fits(dialog)
                assert _axis_row_heights(dialog) == rows
                return
        finally:
            dialog.close()
    pytest.fail("No file name gained a preview line after the edit")
