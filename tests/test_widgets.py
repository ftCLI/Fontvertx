from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QEnterEvent,
    QFont,
    QHelpEvent,
    QStandardItemModel,
    QTextDocument,
    QTextFormat,
    QValidator,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QDoubleSpinBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QStyleFactory,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from fontvertx.__main__ import _mono_family
from fontvertx.gui.drop_zone_frame import zone_colors
from fontvertx.gui.icons import material_icon
from fontvertx.gui.instance_tree import InstanceTree
from fontvertx.gui.profiles import CONVERSION_GROUP_HEADINGS, CONVERSIONS
from fontvertx.gui.styles import (
    LIGHT,
    UI_FONT_FAMILY,
    mono_family,
    set_mono_family,
    stylesheet,
)
from fontvertx.gui.widgets import (
    DROP_ZONE_DRAGGING,
    DROP_ZONE_SCANNING,
    DROP_ZONE_TITLE,
    GLYPH_GAP,
    ConversionSelector,
    DecimalSpinBox,
    DropZone,
    ElidedLabel,
    ExamplePathLabel,
    FileTable,
    FolderSplitButton,
    HoverIconButton,
    KeyboardPushButton,
    StepperField,
    UpmSpinBox,
    accept_local_files,
    dropped_paths,
)


def mime_for(*paths: Path) -> QMimeData:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    return mime


_KEEP_ALIVE: list[QMimeData] = []


def test_folder_split_focus_and_menu_share_frame(qapp: QApplication) -> None:
    host = QWidget()
    layout = QVBoxLayout(host)
    other = QPushButton("Other")
    split = FolderSplitButton()
    layout.addWidget(other)
    layout.addWidget(split)
    host.setStyleSheet(stylesheet())
    host.show()
    host.activateWindow()
    other.setFocus()
    QTest.qWait(30)
    original_size = split.size()
    divider_x = split.main_button.geometry().right() + 1

    def check_frame(focused: bool, opened: bool) -> None:
        image = split.grab().toImage()
        scale = image.devicePixelRatio()

        def pixel(x: int, y: int) -> str:
            return image.pixelColor(round(x * scale), round(y * scale)).name()

        assert split.size() == original_size
        assert split.property("focusWithin") == focused
        # Borderless secondary button: the 2px frame only shows the accent on focus.
        assert pixel(split.width() // 2, 0) == (LIGHT.accent if focused else LIGHT.button)
        assert pixel(0, split.height() // 2) == (LIGHT.accent if focused else LIGHT.button)
        assert pixel(split.width() - 1, split.height() // 2) == (
            LIGHT.accent if focused else LIGHT.button
        )
        assert pixel(divider_x, split.height() // 2) == LIGHT.border_strong
        assert pixel(split.arrow_button.x() + 3, 5) == (
            LIGHT.button_pressed if opened else LIGHT.button
        )

    check_frame(False, False)
    for button in (split.main_button, split.arrow_button):
        button.setFocus(Qt.FocusReason.TabFocusReason)
        QTest.qWait(20)
        check_frame(True, False)
    split.menu.popup(split.mapToGlobal(QPoint(0, split.height())))
    QTest.qWait(30)
    other.setFocus()
    QTest.qWait(20)
    check_frame(True, True)
    split.menu.close()
    other.setFocus()
    QTest.qWait(30)
    check_frame(False, False)
    host.close()


@pytest.mark.parametrize("key", [Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_folder_split_arrow_keys_open_menu(qapp: QApplication, key: Qt.Key) -> None:
    split = FolderSplitButton()
    split.setStyleSheet(stylesheet())
    split.show()
    split.activateWindow()
    split.arrow_button.setFocus()
    QTest.qWait(20)
    opened: list[bool] = []

    def on_show() -> None:
        opened.append(bool(split.property("focusWithin")))
        QTimer.singleShot(0, split.menu, split.menu.close)

    split.menu.aboutToShow.connect(on_show)
    QTest.keyClick(split.arrow_button, key)
    QTest.qWait(20)
    assert opened == [True]
    split.close()


@pytest.mark.parametrize("dialog", [False, True])
@pytest.mark.parametrize(
    ("path", "width", "line_count"),
    [
        ("font.otf", 300, 1),
        ("Sample Family/opentype_ps/upm_1000/font.otf", 270, 2),
        ("Sample Family/opentype_tt/upm_1000/font.otf", 190, 3),
        ("samplelongfilename.otf", 190, 1),
    ],
)
def test_example_path_visible_ink_is_centered(
    qapp: QApplication, dialog: bool, path: str, width: int, line_count: int
) -> None:
    original_family = mono_family()
    set_mono_family(_mono_family())
    try:
        label = ExamplePathLabel()
        if dialog:
            label.setProperty("previewContext", "dialog")
        label.setStyleSheet(stylesheet())
        label.resize(width, 100)
        label.set_path(path)
        label.show()
        QTest.qWait(20)
        document = QTextDocument()
        document.setHtml(label.text())
        assert document.blockCount() == line_count
        image = label.grab().toImage()
        inset = round(12 * image.devicePixelRatio())
        ink_rows = [
            y
            for y in range(image.height())
            if any(
                (color := image.pixelColor(x, y)).red() < 100
                and color.green() < 110
                and color.blue() < 135
                for x in range(inset, image.width() - inset)
            )
        ]
        assert ink_rows
        # Centered within 2px: where the glyphs' ink sits in their line box depends on
        # each system's font rasterizer (1px on Windows, 2px on macOS).
        assert abs(ink_rows[0] - (image.height() - 1 - ink_rows[-1])) <= 2
        label.close()
    finally:
        set_mono_family(original_family)


@pytest.mark.parametrize("dialog", [False, True])
def test_example_path_wraps_only_at_slashes_and_copies_cleanly(
    qapp: QApplication, dialog: bool
) -> None:
    label = ExamplePathLabel()
    if dialog:
        label.setProperty("previewContext", "dialog")
    label.setStyleSheet(stylesheet())
    label.resize(220, 100)
    path = "Sample Family/opentype_tt/upm_1000/font.otf"
    label.set_path(path)
    label.show()
    QTest.qWait(20)
    assert label.toolTip() == path
    assert label.plain_path() == path
    document = QTextDocument()
    document.setDefaultFont(label.font())
    document.setDocumentMargin(0)
    document.setHtml(label.text())
    blocks = []
    block = document.begin()
    while block.isValid():
        blocks.append(block)
        block = block.next()
    assert len(blocks) > 1
    assert all(block.text().endswith("/\u200b") for block in blocks[:-1])
    assert all(block.blockFormat().leftMargin() == 0 for block in blocks)
    assert all(block.blockFormat().topMargin() == 0 for block in blocks)
    assert all(block.blockFormat().bottomMargin() == 0 for block in blocks)
    last_block = blocks[-1]
    fragment = last_block.begin().fragment()
    assert fragment.isValid()
    assert not fragment.charFormat().hasProperty(QTextFormat.Property.FontWeight)
    assert f"color:{LIGHT.header_group}" in label.text()
    assert document.toPlainText().replace("\n", "").replace("\u200b", "") == path
    image = label.grab().toImage()
    scale = image.devicePixelRatio()
    line_height = label.fontMetrics().lineSpacing()
    for line in range(len(blocks) - 1):
        y_start = round((9 + line * line_height) * scale)
        y_end = min(image.height(), round((9 + (line + 1) * line_height) * scale))
        assert any(
            (color := image.pixelColor(x, y)).red() < 150
            and color.blue() - color.red() >= 15
            and color.green() > color.red()
            for y in range(y_start, y_end)
            for x in range(image.width())
        )
    assert image.pixelColor(round(5 * scale), round(15 * scale)).name() == (
        LIGHT.field if dialog else LIGHT.primary_tint_bg
    )
    QTest.mousePress(label, Qt.MouseButton.LeftButton, pos=QPoint(2, 10))
    QTest.mouseMove(label, QPoint(label.width() - 3, label.height() - 5), 20)
    QTest.mouseRelease(
        label, Qt.MouseButton.LeftButton, pos=QPoint(label.width() - 3, label.height() - 5)
    )
    image = label.grab().toImage()
    assert any(
        image.pixelColor(x, y).name()
        == (LIGHT.text_selection_bg if dialog else LIGHT.example_selection)
        for y in range(image.height())
        for x in range(image.width())
    )
    QTest.keyClick(label, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert qapp.clipboard().text() == path
    assert label.cursor().shape() == Qt.CursorShape.ArrowCursor
    label.close()


def test_example_path_preserves_spaces_and_html_on_copy(qapp: QApplication) -> None:
    label = ExamplePathLabel()
    label.setStyleSheet(stylesheet())
    label.resize(190, 100)
    path = "a  & <b>/file name.otf"
    label.set_path(path)
    label.show()
    QTest.qWait(20)
    assert "&nbsp;" not in label.text()
    document = QTextDocument()
    document.setHtml(label.text())
    assert document.toPlainText().replace("\n", "").replace("\u200b", "") == path
    QTest.mousePress(label, Qt.MouseButton.LeftButton, pos=QPoint(2, 4))
    QTest.mouseMove(label, QPoint(label.width() - 3, label.height() - 3), 20)
    QTest.mouseRelease(
        label, Qt.MouseButton.LeftButton, pos=QPoint(label.width() - 3, label.height() - 3)
    )
    QTest.keyClick(label, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert qapp.clipboard().text() == path
    label.close()


def drop_event(mime: QMimeData) -> QDropEvent:
    # QDropEvent does not own its mime data; keep it alive for the event's lifetime.
    _KEEP_ALIVE.append(mime)
    return QDropEvent(
        QPointF(1, 1),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


@pytest.mark.parametrize(
    "key",
    [Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter],
)
def test_keyboard_push_button_activates_with_space_and_enter(
    qapp: QApplication, key: Qt.Key
) -> None:
    button = KeyboardPushButton("Activate")
    activations: list[bool] = []
    button.clicked.connect(lambda: activations.append(True))
    button.show()
    button.setFocus()
    qapp.processEvents()

    QTest.keyClick(button, key)

    assert activations == [True]
    button.close()


def test_hover_icon_button_swaps_icon_tint_on_hover(qapp: QApplication) -> None:
    normal = material_icon("add", LIGHT.text_secondary, size=20)
    hover = material_icon("add", LIGHT.primary, size=20)
    button = HoverIconButton(normal, hover)
    assert button.icon().pixmap(20).cacheKey() == normal.pixmap(20).cacheKey()

    button.enterEvent(QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5)))
    assert button.icon().pixmap(20).cacheKey() == hover.pixmap(20).cacheKey()

    button.leaveEvent(QEvent(QEvent.Type.Leave))
    assert button.icon().pixmap(20).cacheKey() == normal.pixmap(20).cacheKey()


@pytest.mark.parametrize("style_name", ["Fusion", "windows11"])
def test_hover_icon_button_focus_frame_does_not_cover_icon(
    qapp: QApplication, style_name: str
) -> None:
    available_styles = QStyleFactory.keys()
    if style_name not in available_styles:
        pytest.skip(f"Qt style {style_name} is unavailable")
    window = QWidget()
    window.setStyle(QStyleFactory.create(style_name))
    layout = QVBoxLayout(window)
    other = QPushButton("Other")
    icon = material_icon("add", LIGHT.text_secondary, size=20)
    button = HoverIconButton(icon, icon)
    button.setObjectName("iconButton")
    button.setIconSize(QSize(20, 20))
    button.setFixedSize(30, 30)
    layout.addWidget(other)
    layout.addWidget(button)
    window.setStyleSheet(stylesheet())
    window.show()
    window.activateWindow()
    other.setFocus()
    qapp.processEvents()
    assert other.hasFocus()
    unfocused = button.grab().toImage()

    QTest.keyClick(other, Qt.Key.Key_Tab)
    qapp.processEvents()
    assert button.hasFocus()
    focused = button.grab().toImage()
    assert focused.copy(5, 5, 20, 20) == unfocused.copy(5, 5, 20, 20)
    assert focused.pixelColor(15, 0).name() == LIGHT.accent
    assert unfocused.pixelColor(15, 0).name() != LIGHT.accent

    activations: list[bool] = []
    button.clicked.connect(lambda: activations.append(True))
    QTest.keyClick(button, Qt.Key.Key_Return)
    assert activations == [True]
    window.close()


def test_decimal_spin_box_accepts_comma_separator(qapp: QApplication) -> None:
    spin = DecimalSpinBox()
    spin.setRange(0, 10)

    assert spin.valueFromText("2,5") == 2.5
    state, text, _ = spin.validate("2,5", 3)
    assert state == QValidator.State.Acceptable
    assert text == "2.5"


def test_upm_spin_box_steps_between_supported_values(qapp: QApplication) -> None:
    spin = UpmSpinBox()
    assert spin.value() == 1000

    spin.stepBy(1)
    assert spin.value() == 1024
    spin.stepBy(2)
    assert spin.value() == 2048
    spin.stepBy(-1)
    assert spin.value() == 2000

    spin.setValue(16384)
    spin.stepBy(1)
    assert spin.value() == 16384
    spin.setValue(16)
    spin.stepBy(-1)
    assert spin.value() == 16


def test_stepper_field_buttons_step_the_spin_box(qapp: QApplication) -> None:
    spin = QSpinBox()
    spin.setRange(0, 10)
    spin.setValue(5)
    field = StepperField(spin)
    buttons = field.findChildren(QPushButton)

    assert spin.alignment() & Qt.AlignmentFlag.AlignCenter
    assert [button.text() for button in buttons] == ["−", "+"]
    buttons[1].click()
    buttons[1].click()
    buttons[0].click()
    assert spin.value() == 6


@pytest.mark.parametrize("spin_type", [QSpinBox, QDoubleSpinBox])
def test_stepper_field_buttons_clear_selection(
    qapp: QApplication, spin_type: type[QAbstractSpinBox]
) -> None:
    spin = spin_type()
    spin.setRange(0, 10)
    spin.setValue(5)
    field = StepperField(spin, tab_buttons=True)
    field.show()
    qapp.processEvents()

    line_edit = spin.lineEdit()
    line_edit.selectAll()
    assert line_edit.hasSelectedText()
    field.increment_button.click()
    assert not line_edit.hasSelectedText()

    for _ in range(3):
        field.decrement_button.click()
    assert not line_edit.hasSelectedText()

    before_repeat = spin.value()
    QTest.mousePress(field.increment_button, Qt.MouseButton.LeftButton)
    QTest.qWait(
        field.increment_button.autoRepeatDelay() + 2 * field.increment_button.autoRepeatInterval()
    )
    QTest.mouseRelease(field.increment_button, Qt.MouseButton.LeftButton)
    assert spin.value() > before_repeat
    assert not line_edit.hasSelectedText()

    field.increment_button.setFocus()
    QTest.keyClick(field.increment_button, Qt.Key.Key_Space)
    assert not line_edit.hasSelectedText()
    field.decrement_button.setFocus()
    QTest.keyClick(field.decrement_button, Qt.Key.Key_Return)
    assert not line_edit.hasSelectedText()


def test_conversion_selector_tracks_selection(qapp: QApplication) -> None:
    selector = ConversionSelector({"a": "First", "b": "Second"})
    changes: list[int] = []
    selector.currentIndexChanged.connect(changes.append)

    assert selector.currentIndex() == 0
    assert selector.currentData() == "a"
    assert selector.findData("b") == 1
    assert selector.findData("missing") == -1

    selector.setCurrentIndex(1)
    selector.setCurrentIndex(1)
    selector.setCurrentIndex(9)

    assert selector.currentData() == "b"
    assert changes == [1]


def test_conversion_selector_can_start_unselected(qapp: QApplication) -> None:
    selector = ConversionSelector({"a": "First", "b": "Second"}, select_first=False)
    assert selector.currentIndex() == -1
    assert selector.currentData() is None
    combo = selector.combo
    assert [combo.itemText(i) for i in range(combo.count())] == ["First", "Second"]
    selector.setCurrentIndex(1)
    assert selector.currentData() == "b"


def test_grouped_conversion_selector_preserves_indices(qapp: QApplication) -> None:
    selector = ConversionSelector(
        CONVERSIONS, select_first=False, group_headings=CONVERSION_GROUP_HEADINGS
    )
    selector.show()
    qapp.processEvents()
    combo = selector.combo
    texts = [combo.itemText(i) for i in range(combo.count())]
    assert texts == [
        "Outlines",
        CONVERSIONS["ttf2otf"],
        CONVERSIONS["otf2ttf"],
        "Web fonts",
        CONVERSIONS["ft2wf"],
        CONVERSIONS["woff2ft"],
        CONVERSIONS["woff22ft"],
        "Other",
        CONVERSIONS["var2static"],
        CONVERSIONS["ttc2sfnt"],
    ]
    model = combo.model()
    for row in (0, 3, 7):
        assert not model.flags(model.index(row, 0)) & Qt.ItemFlag.ItemIsEnabled
    assert selector.currentData() is None
    for index, key in enumerate(CONVERSIONS):
        assert selector.findData(key) == index
        selector.setCurrentIndex(index)
        assert selector.currentData() == key
        assert combo.currentText() == CONVERSIONS[key]


def test_dropped_paths_keeps_only_existing_local_paths(qapp: QApplication, tmp_path: Path) -> None:
    file = tmp_path / "font.ttf"
    file.touch()
    folder = tmp_path / "fonts"
    folder.mkdir()
    mime = mime_for(file, folder, tmp_path / "missing.ttf")
    mime.setUrls([*mime.urls(), QUrl("https://example.com/font.ttf")])

    assert [Path(p) for p in dropped_paths(drop_event(mime))] == [file, folder]


def test_accept_local_files_filters_drag_events(qapp: QApplication, tmp_path: Path) -> None:
    local = mime_for(tmp_path)
    remote = QMimeData()
    remote.setUrls([QUrl("https://example.com/font.ttf")])
    plain = QMimeData()
    plain.setText("text")

    for mime, accepted in ((local, True), (remote, False), (plain, False)):
        enter = QDragEnterEvent(
            QPoint(1, 1),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        enter.setAccepted(not accepted)
        accept_local_files(enter)
        assert enter.isAccepted() is accepted

        move = QDragMoveEvent(
            QPoint(1, 1),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        move.setAccepted(not accepted)
        accept_local_files(move)
        assert move.isAccepted() is accepted


def test_file_table_emits_dropped_paths_and_ignores_others(
    qapp: QApplication, tmp_path: Path
) -> None:
    table = FileTable()
    received: list[list[str]] = []
    table.paths_dropped.connect(received.append)
    font = tmp_path / "font.ttf"
    font.touch()

    accepted = drop_event(mime_for(font))
    table.dropEvent(accepted)
    ignored = drop_event(mime_for(tmp_path / "missing.ttf"))
    ignored.setAccepted(True)
    table.dropEvent(ignored)

    assert [[Path(p) for p in paths] for paths in received] == [[font]]
    assert accepted.isAccepted()
    assert not ignored.isAccepted()


def test_file_table_renders_and_configures_columns(qapp: QApplication) -> None:
    table = FileTable()
    table.resize(400, 200)
    assert table.muted_color.name() == LIGHT.text_disabled
    assert table.verticalHeader().isHidden()

    empty = table.grab().toImage()
    model = QStandardItemModel(1, 4)
    table.setModel(model)
    table.configure_columns()
    table.show()
    qapp.processEvents()
    assert table.verticalHeader().isHidden()
    assert table.horizontalHeader().isVisible()
    assert table.horizontalHeader().sectionSize(1) == 80
    assert table.horizontalHeader().sectionSize(3) == 70
    assert table.grab().toImage().size() == empty.size()


@pytest.mark.parametrize("widget_type", [DropZone, FileTable, InstanceTree])
def test_drag_highlight_and_local_drop(
    qapp: QApplication, tmp_path: Path, widget_type: type[DropZone | FileTable | InstanceTree]
) -> None:
    widget = widget_type()
    widget.setStyleSheet(stylesheet())
    widget.resize(600, 300)
    widget.show()
    qapp.processEvents()
    received: list[list[str]] = []
    widget.paths_dropped.connect(received.append)
    local = mime_for(tmp_path)
    remote = QMimeData()
    remote.setUrls([QUrl("https://example.com/font.ttf")])

    def enter(mime: QMimeData) -> QDragEnterEvent:
        return QDragEnterEvent(
            QPoint(1, 1),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

    rejected = enter(remote)
    widget.dragEnterEvent(rejected)
    assert not rejected.isAccepted()
    assert widget.property("dragOver") == "false"
    accepted = enter(local)
    widget.dragEnterEvent(accepted)
    assert accepted.isAccepted()
    assert widget.property("dragOver") == "true"
    widget.dragLeaveEvent(QDragLeaveEvent())
    assert widget.property("dragOver") == "false"
    widget.dragEnterEvent(enter(local))
    event = drop_event(local)
    widget.dropEvent(event)
    assert event.isAccepted()
    assert widget.property("dragOver") == "false"
    assert [[Path(path) for path in paths] for paths in received] == [[tmp_path]]
    invalid = drop_event(remote)
    widget.dropEvent(invalid)
    assert not invalid.isAccepted()
    assert [[Path(path) for path in paths] for paths in received] == [[tmp_path]]
    widget.close()


@pytest.mark.parametrize("widget_type", [DropZone, FileTable, InstanceTree])
def test_drag_events_are_delivered_to_drop_target(
    qapp: QApplication, tmp_path: Path, widget_type: type[DropZone | FileTable | InstanceTree]
) -> None:
    widget = widget_type()
    widget.resize(600, 300)
    widget.show()
    qapp.processEvents()
    target = widget if isinstance(widget, DropZone) else widget.viewport()
    mime = mime_for(tmp_path)
    event = QDragEnterEvent(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(target, event)
    assert event.isAccepted()
    assert widget.property("dragOver") == "true"
    QApplication.sendEvent(target, QDragLeaveEvent())
    assert widget.property("dragOver") == "false"
    widget.close()


def show_zone(qapp: QApplication, width: int = 600, height: int = 400) -> DropZone:
    zone = DropZone()
    zone.setStyleSheet(stylesheet())
    zone.resize(width, height)
    zone.show()
    qapp.processEvents()
    return zone


def enter_drag(zone: DropZone) -> None:
    # Keep the mime data referenced: the event only holds a pointer to it.
    mime = mime_for(Path.cwd())
    event = QDragEnterEvent(
        QPoint(1, 1),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    zone.dragEnterEvent(event)
    assert event.isAccepted()


def label_color(label: QLabel) -> str:
    return label.palette().color(label.foregroundRole()).name()


def assert_rest_state(zone: DropZone) -> None:
    assert zone.title.text() == DROP_ZONE_TITLE
    assert zone.glyph.isVisible() and zone.title.isVisible() and zone.formats.isVisible()
    assert label_color(zone.glyph) == LIGHT.dropzone_glyph


def format_chips(zone: DropZone) -> list[QLabel]:
    return [label for label in zone.findChildren(QLabel) if label.objectName() == "formatChip"]


def test_drop_zone_shows_glyph_title_and_format_chips_top_to_bottom(
    qapp: QApplication,
) -> None:
    zone = show_zone(qapp)
    # The add actions live in the files card header, not in the drop zone.
    assert zone.findChildren(QPushButton) == []
    assert_rest_state(zone)
    assert zone.glyph.text() == "Aa"
    assert [chip.text() for chip in format_chips(zone)] == list(DropZone.FORMATS)
    assert all(chip.parent() is zone.formats for chip in format_chips(zone))
    assert DROP_ZONE_TITLE == "Drop fonts or folders here"
    assert zone.accessibleDescription() == "Supported formats: TTF, OTF, WOFF, WOFF2, TTC, OTC"
    # Glyph, title, chips from the top, and no hint line any more.
    assert zone.glyph.geometry().bottom() < zone.title.geometry().top()
    assert zone.title.geometry().bottom() < zone.formats.geometry().top()
    names = {label.objectName() for label in zone.findChildren(QLabel)}
    assert names == {"dropZoneGlyph", "dropZoneTitle", "formatChip"}
    assert not hasattr(zone, "hint")
    # The block is centered vertically (the stretches above and below are equal).
    top = zone.glyph.geometry().top()
    bottom = zone.height() - zone.formats.geometry().bottom() - 1
    assert abs(top - bottom) <= 1
    zone.close()


def test_drop_zone_label_styles(qapp: QApplication) -> None:
    zone = show_zone(qapp)
    glyph = zone.glyph.font()
    assert glyph.family() == UI_FONT_FAMILY
    assert glyph.weight() == QFont.Weight.DemiBold
    assert glyph.letterSpacingType() == QFont.SpacingType.PercentageSpacing
    assert glyph.letterSpacing() == 96
    assert zone.glyph.objectName() == "dropZoneGlyph"
    assert zone.glyph.accessibleName() == ""
    assert zone.glyph.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert zone.title.objectName() == "dropZoneTitle"
    assert zone.title.font().pixelSize() == 22
    assert zone.title.font().weight() == QFont.Weight.DemiBold
    assert label_color(zone.title) == LIGHT.text
    for chip in format_chips(zone):
        assert chip.font().family() == mono_family()
        assert chip.font().pixelSize() == 10  # the drop zone's smaller chips
        assert label_color(chip) == LIGHT.accent
    zone.close()


@pytest.mark.parametrize("height", [320, 480, 800])
def test_drop_zone_visible_gap_between_glyph_and_title(qapp: QApplication, height: int) -> None:
    zone = show_zone(qapp, 700, height)
    image = zone.grab().toImage()
    x_range = range(zone.width() // 4, 3 * zone.width() // 4)

    def inked(y: int) -> bool:
        # Any pixel that is not the zone background (antialiased edges included).
        return any(image.pixelColor(x, y).name() != LIGHT.dropzone_bg for x in x_range)

    glyph = zone.glyph.geometry()
    title = zone.title.geometry()
    glyph_bottom = max(y for y in range(glyph.top(), glyph.bottom() + 1) if inked(y))
    title_top = min(y for y in range(title.top(), title.bottom() + 1) if inked(y))
    gap = title_top - glyph_bottom - 1
    # GLYPH_GAP from the baseline of "Aa" to the title's box, plus the room the title
    # line keeps above its capitals (from this system's font metrics, not a fixed value).
    metrics = zone.title.fontMetrics()
    above_caps = metrics.ascent() - metrics.capHeight()
    assert GLYPH_GAP - 1 <= gap <= GLYPH_GAP + above_caps + 2
    zone.close()


def test_drop_zone_drag_state_and_back(qapp: QApplication, tmp_path: Path) -> None:
    zone = show_zone(qapp)
    positions = [zone.glyph.geometry(), zone.title.geometry(), zone.formats.geometry()]
    enter_drag(zone)
    qapp.processEvents()
    assert zone.title.text() == DROP_ZONE_DRAGGING == "Release to add"
    assert not zone.formats.isVisible()
    assert zone.glyph.isVisible()
    assert label_color(zone.glyph) == LIGHT.dropzone_glyph_active
    # The hidden chips keep their room: nothing moves while dragging.
    assert positions == [zone.glyph.geometry(), zone.title.geometry(), zone.formats.geometry()]
    zone.dragLeaveEvent(QDragLeaveEvent())
    qapp.processEvents()
    assert_rest_state(zone)
    enter_drag(zone)
    mime = mime_for(tmp_path)
    zone.dropEvent(drop_event(mime))
    qapp.processEvents()
    assert_rest_state(zone)
    zone.close()


def test_drop_zone_scanning_state(qapp: QApplication) -> None:
    zone = show_zone(qapp)
    zone.set_scanning(True)
    assert zone.title.text() == DROP_ZONE_SCANNING == "Scanning…"
    assert not zone.formats.isVisible()
    assert zone.glyph.isVisible()
    assert label_color(zone.glyph) == LIGHT.dropzone_glyph
    zone.set_scanning(False)
    assert_rest_state(zone)
    zone.close()


def test_drop_zone_glyph_grows_with_the_zone_height_within_bounds(qapp: QApplication) -> None:
    zone = show_zone(qapp)
    sizes = []
    for height in (280, 320, 400, 480, 560, 900, 2000):
        zone.resize(700, height)
        qapp.processEvents()
        pixels = zone.glyph.font().pixelSize()
        assert pixels == zone.glyph_pixel_size()
        assert pixels == max(56, min(140, round(height * 0.25)))
        sizes.append(pixels)
    assert sizes == sorted(sizes)
    assert sizes[0] == 70 and sizes[-1] == 140
    zone.close()


@pytest.mark.parametrize("height", [279, 220, 160])
def test_drop_zone_hides_the_glyph_when_short_and_keeps_the_title(
    qapp: QApplication, height: int
) -> None:
    zone = show_zone(qapp, 600, height)
    assert not zone.glyph.isVisible()
    assert zone.title.isVisible() and zone.formats.isVisible()
    title = zone.title.geometry()
    assert title.top() >= 0 and title.bottom() < zone.height()
    # Without the glyph, title and formats stay centered.
    top = title.top()
    bottom = zone.height() - zone.formats.geometry().bottom() - 1
    assert abs(top - bottom) <= 1
    zone.resize(600, 280)
    qapp.processEvents()
    assert zone.glyph.isVisible()
    zone.close()


def test_drop_zone_frame_colors_follow_the_theme(qapp: QApplication) -> None:
    rest = zone_colors(False)
    drag = zone_colors(True)
    assert rest["background"].name() == LIGHT.dropzone_bg
    assert rest["border"].name() == LIGHT.border_strong
    assert drag["background"].name() == LIGHT.dropzone_bg_active
    assert drag["border"].name() == LIGHT.accent
    zone = show_zone(qapp)
    assert zone.grab().toImage().pixelColor(zone.width() // 2, 20).name() == LIGHT.dropzone_bg
    enter_drag(zone)
    image = zone.grab().toImage()
    assert image.pixelColor(zone.width() // 2, 20).name() == LIGHT.dropzone_bg_active
    zone.dragLeaveEvent(QDragLeaveEvent())
    zone.close()


def test_drop_zone_is_decorative_only(qapp: QApplication) -> None:
    zone = DropZone()
    assert zone.accessibleName() == "Font drop area"
    assert zone.toolTip() == ""
    assert not zone.hasMouseTracking()


def test_elided_label_tooltip_only_when_cut_or_explicit(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    label = ElidedLabel()
    label.resize(120, 20)
    shown: list[str] = []
    hidden: list[bool] = []
    monkeypatch.setattr(QToolTip, "showText", lambda _pos, text, *_args: shown.append(text))
    monkeypatch.setattr(QToolTip, "hideText", lambda: hidden.append(True))

    def hover() -> QHelpEvent:
        event = QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), label.mapToGlobal(QPoint(5, 5)))
        assert label.event(event)
        return event

    label.setText("Short")
    assert label.toolTip() == "" and label.tooltip_text() == ""
    assert not hover().isAccepted()
    assert shown == [] and hidden == [True]

    long_text = "A very long status line that cannot fit " * 4
    label.setText(long_text)
    assert label.toolTip() == ""
    assert label.display_text() != long_text
    assert label.tooltip_text() == long_text
    hover()
    assert shown == [long_text]

    # An explicit tooltip (e.g. an error detail) wins, cut or not.
    label.setToolTip("Error detail")
    label.setText("Short")
    assert label.tooltip_text() == "Error detail"
    hover()  # handled by QLabel itself, which shows the explicit tooltip
    assert shown == [long_text]


def test_profile_combo_items_have_no_tooltips(qapp: QApplication) -> None:
    selector = ConversionSelector(CONVERSIONS, group_headings=CONVERSION_GROUP_HEADINGS)
    model = selector.combo.model()
    assert isinstance(model, QStandardItemModel)
    for row in range(model.rowCount()):
        assert not model.item(row).toolTip()
