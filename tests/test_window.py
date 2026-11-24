from __future__ import annotations

import json
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, QSettings, QSize, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDropEvent, QEnterEvent, QFont, QImage, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QWidget,
)
from shiboken6 import isValid

from fontvertx.gui import conversion_controller as conversion_controller_module
from fontvertx.gui import layout_manager, styles
from fontvertx.gui import scanner as scanner_module
from fontvertx.gui import window as window_module
from fontvertx.gui import worker as worker_module
from fontvertx.gui.conversion_controller import RunOutcome
from fontvertx.gui.logs import LogEntry
from fontvertx.gui.panels.source_panel import CARD_INSET, list_status_text
from fontvertx.gui.scanner import Source
from fontvertx.gui.status_pill import StatusState, chip_content, format_elapsed, format_message
from fontvertx.gui.styles import LIGHT, stylesheet
from fontvertx.gui.window import ConverterWindow, _window_sizes
from fontvertx.gui.worker import ConversionWorker, RunState, exception_type, format_duration
from fontvertx.inspection import FontInfo, NamedInstanceInfo
from fontvertx.models import (
    ConversionOptions,
    ConversionRequest,
    ConversionResult,
    FontOutcome,
    FontOutcomeKind,
)

Wait = Callable[[Callable[[], bool], float], None]

# The real minimum window size; offscreen screens would otherwise bound it lower.
MIN_SIZE = _window_sizes(None)[0]
MIN_WIDTH = MIN_SIZE.width()


def test_format_duration() -> None:
    assert format_duration(1.25) in ("1.2 s", "1.3 s")
    assert format_duration(75) == "1:15"
    assert format_duration(3725) == "1:02:05"


def test_exception_type() -> None:
    assert exception_type("ValueError: boom") == "ValueError"
    assert exception_type("fontTools.ttLib.TTLibError: boom") == "TTLibError"
    assert exception_type("no separator") is None
    assert exception_type("not an id: x") is None


def _outcome(kind: FontOutcomeKind, error: str | None = None, name: str = "a.ttf") -> FontOutcome:
    return FontOutcome(
        input_path=Path(name),
        kind=kind,
        output_paths=(Path("out") / "a.otf",) if kind is FontOutcomeKind.CONVERTED else (),
        error=error,
        elapsed=0.5,
    )


def _worker(conversion: str = "ttf2otf") -> ConversionWorker:
    request = ConversionRequest((Path("a.ttf"),), ConversionOptions())
    worker = ConversionWorker(request)
    worker.request = type("R", (), {"conversion": conversion, "input_paths": ()})()  # type: ignore[assignment]
    return worker


def test_worker_reports_outcomes(qapp: QApplication) -> None:
    worker = _worker()
    events: list[object] = []
    worker.log_received.connect(events.append)
    worker._report_outcome(_outcome(FontOutcomeKind.CONVERTED))
    worker._report_outcome(_outcome(FontOutcomeKind.SKIPPED))
    worker._report_outcome(_outcome(FontOutcomeKind.FAILED, "ValueError: bad"))
    worker._report_outcome(_outcome(FontOutcomeKind.FAILED))
    logs = [entry for entry in events if isinstance(entry, LogEntry)]
    assert len([entry for entry in logs if entry.outcome is not None]) == 4
    assert [entry.event for entry in logs] == [
        "font.converted",
        "font.skipped",
        "font.failed",
        "font.failed",
    ]
    assert "ValueError: bad" in logs[2].message
    assert logs[0].outcome is not None
    assert "outcome" not in json.loads(logs[0].to_json())


def test_worker_var2static_name_includes_output(qapp: QApplication) -> None:
    worker = _worker("var2static")
    events: list[object] = []
    worker.log_received.connect(events.append)
    worker._report_outcome(_outcome(FontOutcomeKind.CONVERTED))
    logs = [entry for entry in events if isinstance(entry, LogEntry)]
    assert "a.ttf → a.otf" in logs[0].message


def test_worker_run_emits_result_and_failure(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = ConversionResult()

    class Service:
        def convert(self, request: Any, **kwargs: Any) -> ConversionResult:
            kwargs["on_font_start"](Path("a.ttf"))
            kwargs["on_log"]("step")
            kwargs["on_progress"](type("P", (), {"done": 1, "total": 2})())
            return result

    monkeypatch.setattr(worker_module, "ConverterService", Service)
    worker = _worker()
    got: list[Any] = []
    progress: list[tuple[int, int]] = []
    logs: list[LogEntry] = []
    worker.finished_conversion.connect(got.append)
    worker.progress_changed.connect(lambda d, t: progress.append((d, t)))
    worker.log_received.connect(logs.append)
    worker.run()
    assert got == [result]
    assert progress == [(1, 2)]
    assert logs[0].context["input"] == "a.ttf"

    class Failing:
        def convert(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("nope")

    monkeypatch.setattr(worker_module, "ConverterService", Failing)
    failures: list[str] = []
    worker.failed.connect(failures.append)
    worker.run()
    assert failures == ["RuntimeError: nope"]


def test_worker_pause_resume_cancel(qapp: QApplication) -> None:
    worker = _worker()
    states: list[bool] = []
    worker.paused_changed.connect(states.append)
    worker.wait_if_paused()
    assert states == []
    worker.pause()
    threading.Timer(0.05, worker.resume).start()
    worker.wait_if_paused()
    assert states == [True, False]
    worker.pause()
    assert not worker._running.is_set()
    worker.cancel()
    assert worker._running.is_set()


@pytest.fixture
def win(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConverterWindow:
    ini = tmp_path / "settings.ini"
    monkeypatch.setattr(
        window_module,
        "QSettings",
        lambda: QSettings(str(ini), QSettings.Format.IniFormat),
    )
    # Closed and deleted (its scan threads stopped first) by the autouse cleanup in
    # conftest.py; its QSettings object already points at the temporary file.
    return ConverterWindow()


def test_sidebar_scrollbar_overlays_content_and_never_reserves_space(
    win: ConverterWindow, qapp: QApplication
) -> None:
    win.setStyleSheet(stylesheet())
    win.resize(1200, 1100)
    win.show()
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    for _ in range(8):
        qapp.processEvents()
    scroll = win.sidebar_scroll
    native = scroll.verticalScrollBar()
    overlay = win.sidebar_scrollbar
    assert scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert native.maximum() == 0
    assert overlay.isHidden()
    assert win.sidebar_overflow_fade.isHidden()
    width = win.profile_options.width()
    right_gap = scroll.width() - win.profile_options.geometry().right()
    column_width = scroll.width()

    win.resize(1200, 600)
    for _ in range(8):
        qapp.processEvents()
    assert native.maximum() > 0
    assert overlay.maximum() == native.maximum()
    assert overlay.pageStep() == native.pageStep()
    assert win.profile_options.width() == width
    assert scroll.width() == column_width
    assert scroll.width() - win.profile_options.geometry().right() == right_gap
    assert not win.sidebar_overflow_fade.isHidden()
    assert win.sidebar_overflow_fade.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    # Scrolling reveals the overlay; dragging it scrolls the area.
    native.setValue(10)
    assert overlay.isVisible() and overlay.value() == 10
    assert overlay.parentWidget() is scroll.parentWidget()
    assert overlay.geometry().left() > scroll.geometry().right()
    assert overlay.geometry().height() == scroll.height()
    overlay.setValue(20)
    assert native.value() == 20

    native.setValue(native.maximum())
    qapp.processEvents()
    assert win.sidebar_overflow_fade.isHidden()
    native.setValue(0)
    qapp.processEvents()
    assert not win.sidebar_overflow_fade.isHidden()
    assert win.sidebar_overflow_fade.geometry().bottom() == scroll.viewport().height() - 1


def _scan(win: ConverterWindow, paths: list[Path], wait: Wait) -> None:
    win._add_paths([str(p) for p in paths])
    wait(lambda: not win.file_list.scanning, 30.0)
    qapp = QApplication.instance()
    assert qapp is not None
    qapp.processEvents()


@pytest.fixture
def fonts(tmp_path: Path, fonts_dir: Path) -> Path:
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copy(fonts_dir / "IBMPlexSans-Regular.ttf", folder / "a.ttf")
    shutil.copy(fonts_dir / "IBMPlexSans-Regular.otf", folder / "b.otf")
    return folder


def test_card_step_numbers(win: ConverterWindow) -> None:
    for card, number in (
        (win.files_group, "1"),
        (win.conversion_group, "2"),
        (win.profile_options, "3"),
        (win.destination_group, "4"),
    ):
        badge = card.findChild(window_module.QLabel, "cardNumber")
        assert badge is not None
        assert badge.text() == number
        heading_container = badge.parentWidget()
        # The options card heading shares its row with the reset button, so it
        # carries no bottom margin (the gap is added as layout spacing); the other
        # cards keep the built-in 6px margin.
        expected_margin = 0 if card in (win.profile_options, win.files_group) else 6
        assert heading_container.layout().contentsMargins().bottom() == expected_margin


def test_initial_state(win: ConverterWindow) -> None:
    assert not win.convert_button.isEnabled()
    assert not win.overwrite.isChecked()
    assert win.convert_button.text() == "Convert"
    assert not win.view_log_button.isEnabled()
    assert win.status_pill.isHidden()
    assert win.summary.text() == "Add fonts to start converting"
    assert win._run_state is RunState.IDLE
    assert win.font_filter.isHidden()
    assert win.select_all_checkbox.isHidden()
    assert win.hide_incompatible.isHidden()
    assert all(not widget.isHidden() for widget in (win.add_button, win.add_folder_button))
    assert win.clear_button.isHidden()
    assert win.font_filter.placeholderText() == "Filter fonts…"
    assert "format" in win.font_filter.toolTip()
    assert win.conversion.currentData() is None
    assert not win.profile_options.isHidden()
    assert not win.profile_options.isEnabled()
    assert win.profile_options.no_profile_options.title.text() == "No options yet"
    assert win.profile_options.findChild(window_module.QLabel, "cardHeading").text() == (
        "Set options"
    )
    assert not hasattr(win, "conversion_required_hint")
    assert win.profile_options.isAncestorOf(win.recalc_bboxes)
    assert win.profile_options.isAncestorOf(win.recalc_timestamp)
    assert win.profile_options.isAncestorOf(win.reorder_tables)
    assert not hasattr(win, "advanced_settings_button")
    assert win.clear_button.text() == "Clear list"
    assert win.destination_edit.placeholderText() == ""
    assert not hasattr(win, "drop_hint")


def _rect_in_window(win: ConverterWindow, widget: QWidget) -> QRect:
    return widget.rect().translated(widget.mapTo(win, QPoint()))


@pytest.mark.parametrize("width", [MIN_WIDTH, 1055, 1200, 1400, 2000])
@pytest.mark.parametrize("populated", [False, True])
def test_add_actions_sit_in_the_files_card_header(
    app_font: None, win: ConverterWindow, tmp_path: Path, width: int, populated: bool
) -> None:
    win.setMinimumSize(MIN_SIZE)
    win.resize(width, 600)
    if populated:
        path = tmp_path / "font.ttf"
        win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    win.show()
    for _ in range(3):
        QApplication.processEvents()
    header = _rect_in_window(win, win.files_header)
    card = _rect_in_window(win, win.files_group)
    title = _rect_in_window(win, win.files_group.findChild(QLabel, "cardHeading"))
    add_files = _rect_in_window(win, win.add_button)
    add_folder = _rect_in_window(win, win.folder_split)
    assert win.files_header.isAncestorOf(win.add_button)
    assert win.files_header.isAncestorOf(win.folder_split)
    # Title on the left, then "Add files…", 8px, "Add folder…" with its chevron.
    assert title.right() < add_files.left()
    assert add_folder.left() - add_files.right() - 1 == 8
    assert header.contains(add_files) and header.contains(add_folder)
    assert card.right() - 1 - add_folder.right() == layout_manager.CARD_PADDING
    assert add_files.height() == add_folder.height() == styles.BUTTON_HEIGHT
    assert (
        _rect_in_window(win, win.add_folder_button).right()
        < _rect_in_window(win, win.folder_split.arrow_button).left()
    )
    # Text only: no leading icons; the chevron keeps its glyph.
    assert win.add_button.icon().isNull() and win.add_folder_button.icon().isNull()
    assert not win.folder_split.arrow_button.icon().isNull()
    assert win.add_button.accessibleName() == "Add files…"
    assert win.add_folder_button.accessibleName() == "Add folder…"
    assert win.content_scroll.horizontalScrollBar().maximum() == 0
    if populated:
        clear_rect = _rect_in_window(win, win.clear_button)
        hide_rect = _rect_in_window(win, win.hide_incompatible)
        assert not clear_rect.intersects(hide_rect)
        assert card.contains(clear_rect)


def test_add_files_is_emphasized_only_while_the_list_is_empty(
    app_font: None, win: ConverterWindow, tmp_path: Path
) -> None:
    win.resize(1200, 880)
    win.show()
    for _ in range(3):
        QApplication.processEvents()
    button = win.add_button

    def snapshot() -> tuple[QRect, str, str, QFont.Weight]:
        QApplication.processEvents()
        image = button.grab().toImage()
        return (
            _rect_in_window(win, button),
            image.pixelColor(6, button.height() // 2).name(),
            button.palette().color(button.foregroundRole()).name(),
            button.font().weight(),
        )

    empty = snapshot()
    assert button.property("emphasis") == "true"
    assert empty[1:] == (LIGHT.accent_tint, LIGHT.accent, QFont.Weight.DemiBold)
    assert win.add_folder_button.property("emphasis") in (None, "", "false")
    path = tmp_path / "font.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    populated = snapshot()
    assert button.property("emphasis") == "false"
    assert populated[1:] == (LIGHT.button, LIGHT.text, QFont.Weight.Medium)
    # Only colors and weight change: same size and position in the header.
    assert populated[0] == empty[0]
    assert button.accessibleName() == "Add files…"
    win._clear_files()
    assert snapshot()[0] == empty[0]
    assert button.property("emphasis") == "true"


def test_conversion_combo_elides_long_labels(app_font: None, win: ConverterWindow) -> None:
    win.resize(1200, 880)
    win.show()
    for _ in range(3):
        QApplication.processEvents()
    combo = win.conversion.combo
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    QApplication.processEvents()
    full = combo.currentText()
    elided = combo.elided_text()
    assert elided != full and elided.endswith("…")
    assert combo.fontMetrics().horizontalAdvance(elided) <= combo._edit_rect_width()
    assert combo.toolTip() == full
    # The popup keeps full item texts.
    widest = max(
        combo.view().fontMetrics().horizontalAdvance(combo.itemText(row))
        for row in range(combo.count())
    )
    assert combo.view().minimumWidth() >= widest
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    QApplication.processEvents()
    assert combo.elided_text() == combo.currentText()
    assert combo.toolTip() == ""
    # Size policy and height are unchanged.
    assert combo.height() == styles.FIELD_HEIGHT


def test_no_focus_ring_at_startup_and_first_tab_reaches_add_files(win: ConverterWindow) -> None:
    win.show()
    win.activateWindow()
    QTest.qWait(30)
    central = win.centralWidget()
    assert QApplication.focusWidget() is central
    assert central.focusPolicy() == Qt.FocusPolicy.NoFocus  # draws no focus ring
    for expected in (win.add_button, win.add_folder_button, win.folder_split.arrow_button):
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
        assert QApplication.focusWidget() is expected
    # Focus set later (click, Tab, code) is never taken back.
    win.conversion.combo.setFocus()
    QTest.qWait(30)
    assert QApplication.focusWidget() is win.conversion.combo


def test_clear_list_parks_focus(win: ConverterWindow, tmp_path: Path) -> None:
    path = tmp_path / "font.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    win.show()
    win.activateWindow()
    win.clear_button.setFocus()
    QApplication.processEvents()
    win.clear_button.click()
    QApplication.processEvents()
    assert QApplication.focusWidget() is win.centralWidget()


@pytest.mark.parametrize("size", [(800, 500), (1200, 880)])
def test_empty_drop_zone_ends_one_padding_above_the_card_bottom(
    app_font: None, win: ConverterWindow, tmp_path: Path, size: tuple[int, int]
) -> None:
    win.setMinimumSize(MIN_SIZE)
    win.resize(*size)
    win.show()
    for _ in range(3):
        QApplication.processEvents()
    card = _rect_in_window(win, win.files_group)
    zone = _rect_in_window(win, win.drop_zone)
    assert not win.scan_widget.isVisible()
    # Same inset at the bottom as on the sides: the card's 1px border + 16px padding.
    inset = 1 + layout_manager.CARD_PADDING
    assert zone.left() - card.left() == card.right() - zone.right() == inset
    assert card.bottom() - zone.bottom() == inset
    header_line = _rect_in_window(win, win.files_header_line)
    card_before = card
    path = tmp_path / "font.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    for _ in range(3):
        QApplication.processEvents()
    # Populated: the count row is back at the bottom; the card and header do not move.
    assert win.scan_widget.isVisible()
    assert _rect_in_window(win, win.files_group) == card_before
    assert _rect_in_window(win, win.files_header_line) == header_line


def test_options_card_has_one_enabled_state_in_the_empty_state(win: ConverterWindow) -> None:
    from PySide6.QtWidgets import QAbstractSpinBox, QCheckBox

    win.resize(1200, 880)
    win.show()
    for conversion in ("var2static", "ttf2otf", "otf2ttf", "ft2wf"):
        win.conversion.setCurrentIndex(win.conversion.findData(conversion))
        QApplication.processEvents()
        card = win.profile_options
        assert card.isEnabled()
        assert card.property("optionsState") == ""  # no cosmetic "dim" look
        checkboxes = [box for box in card.findChildren(QCheckBox) if box.isVisibleTo(card)]
        assert checkboxes
        assert all(box.isEnabled() for box in checkboxes), conversion
        # Only option dependencies disable a field: target UPM follows its checkbox.
        upm_field = card.target_upm_field
        if upm_field.isVisibleTo(card):
            expected = card.use_target_upm.isChecked()
            assert upm_field.isEnabled() is expected
            for control in (upm_field.decrement_button, upm_field.increment_button):
                assert control.isEnabled() is expected
        for spin in card.findChildren(QAbstractSpinBox):
            if spin.isVisibleTo(card) and spin is not card.target_upm:
                assert spin.isEnabled(), conversion


def test_files_header_line_spans_the_card(win: ConverterWindow) -> None:
    win.resize(1200, 880)
    win.show()
    for _ in range(3):
        QApplication.processEvents()
    card = _rect_in_window(win, win.files_group)
    header = _rect_in_window(win, win.files_header)
    line = _rect_in_window(win, win.files_header_line)
    # Inside the 1px card border on both sides, directly under the header row.
    assert line.left() == card.left() + 1
    assert line.right() == card.right() - 1
    assert line.height() == 1
    assert line.top() == header.bottom() + 1
    image = win.files_header_line.grab().toImage()
    assert image.pixelColor(image.width() // 2, 0).name() == LIGHT.border
    # 14px above and below the 32px header content.
    margins = win.files_header.layout().contentsMargins()
    assert (margins.top(), margins.bottom()) == (14, 14)


def test_files_card_takes_the_space_of_the_removed_strip(
    app_font: None, win: ConverterWindow, tmp_path: Path
) -> None:
    win.resize(1200, 880)
    path = tmp_path / "font.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    win.show()
    for _ in range(3):
        QApplication.processEvents()
    assert not hasattr(win, "drop_card")
    files = _rect_in_window(win, win.files_group)
    column = _rect_in_window(win, win.files_column)
    assert files == column  # the card fills the whole files column
    footer_card = _rect_in_window(win, win.footer_card)
    # Same gap above the footer card as the sidebar's last card can reach.
    assert footer_card.top() - files.bottom() - 1 == layout_manager.PAGE_MARGIN_BOTTOM
    # The table gets the room: from the filter row down to the count line.
    table = _rect_in_window(win, win.files_stack)
    assert table.height() > 560


@pytest.mark.parametrize("width", [MIN_WIDTH, 1200])
def test_footer_stays_fixed_when_card_scrolls(
    win: ConverterWindow, tmp_path: Path, width: int
) -> None:
    path = tmp_path / "font.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    win.setMinimumSize(MIN_SIZE)
    win.resize(width, 500)
    win.files.setMinimumHeight(700)
    win.show()
    for _ in range(5):
        QApplication.processEvents()
    assert win.content_scroll.verticalScrollBar().maximum() > 0
    before = win.footer.mapTo(win, QPoint())
    button_before = win.add_button.mapTo(win, QPoint())
    win.content_scroll.verticalScrollBar().setValue(
        win.content_scroll.verticalScrollBar().maximum()
    )
    QApplication.processEvents()
    assert win.footer.mapTo(win, QPoint()) == before
    assert win.add_button.mapTo(win, QPoint()).y() < button_before.y()
    # A floating card: the window background shows beside and below it.
    footer_rect = QRect(win.footer.mapTo(win, QPoint()), win.footer.size())
    footer = win.grab(footer_rect).toImage().scaled(win.footer.size())
    gap = styles.FOOTER_GAP
    assert footer.pixelColor(5, 5).name() == LIGHT.page
    assert footer.pixelColor(gap + 30, 5).name() == LIGHT.surface
    assert footer.pixelColor(gap + 30, 0).name() == LIGHT.border
    assert footer.pixelColor(gap + 30, footer.height() - 5).name() == LIGHT.page


@pytest.mark.parametrize("width", [MIN_WIDTH, 1400, 2000])
def test_font_controls_adapt_to_available_width(
    win: ConverterWindow, tmp_path: Path, width: int
) -> None:
    win.setMinimumSize(MIN_SIZE)
    win.resize(width, 600)
    path = tmp_path / "font.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    win.show()
    for _ in range(3):
        QApplication.processEvents()
    controls = (win.select_all_checkbox, win.font_filter, win.hide_incompatible)
    positions = [control.mapTo(win.files_group, QPoint()) for control in controls]
    required = sum(checkbox.sizeHint().width() for checkbox in (controls[0], controls[2]))
    required += 70 + 2 * win.file_options_row.spacing()
    available = win.files_group.width() - 34
    expected = (
        window_module.QBoxLayout.Direction.LeftToRight
        if available >= required
        else window_module.QBoxLayout.Direction.TopToBottom
    )
    assert win.file_options_row.direction() == expected
    if width == 2000:
        assert expected == window_module.QBoxLayout.Direction.LeftToRight
        assert positions[0].x() == pytest.approx(
            win.files_group.layout().contentsMargins().left() + CARD_INSET, abs=1
        )
    if expected == window_module.QBoxLayout.Direction.LeftToRight:
        centers = [
            point.y() + control.height() // 2
            for point, control in zip(positions, controls, strict=True)
        ]
        assert all(abs(center - centers[0]) <= 1 for center in centers)
        assert win.font_filter.width() >= 70
        for first, second in zip(controls, controls[1:], strict=False):
            first_right = first.mapTo(win.files_group, first.rect().topRight()).x()
            second_left = second.mapTo(win.files_group, QPoint()).x()
            assert second_left - first_right == win.file_options_row.spacing() + 1
    if expected == window_module.QBoxLayout.Direction.TopToBottom:
        assert positions[0].y() < positions[1].y() < positions[2].y()
    for control in controls:
        rect = control.rect().translated(control.mapTo(win.files_group, QPoint()))
        assert win.files_group.rect().contains(rect)


def test_font_controls_wrap_when_space_is_limited(win: ConverterWindow) -> None:
    win._update_input_layout(100)
    assert win.file_options_row.direction() == window_module.QBoxLayout.Direction.TopToBottom
    win._update_input_layout(1000)
    assert win.file_options_row.direction() == window_module.QBoxLayout.Direction.LeftToRight


def test_column_visibility_rejects_invalid_sender(
    win: ConverterWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(TypeError, match="must come from a QAction"):
        win._set_column_visible(True)
    monkeypatch.setattr(win, "sender", lambda: win.clear_button)
    with pytest.raises(TypeError, match="must come from a QAction"):
        win._set_column_visible(True)


def test_optional_columns_menu_persists_visibility(
    win: ConverterWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    win.show()
    QApplication.processEvents()
    assert win.font_filter.placeholderText() == window_module.FONT_FILTER_PLACEHOLDER
    header = win.files.horizontalHeader()
    assert header.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    assert [action.text() for action in win.column_menu.actions()] == ["Family", "Style"]
    assert all(
        action.isCheckable() and not action.isChecked() for action in win.column_menu.actions()
    )
    assert [win.files.isColumnHidden(i) for i in range(6)] == [
        False,
        False,
        False,
        False,
        True,
        True,
    ]
    assert header.sectionSize(4) == 0
    positions: list[QPoint] = []
    monkeypatch.setattr(win.column_menu, "popup", positions.append)
    header.customContextMenuRequested.emit(QPoint(10, 5))
    assert positions == [header.mapToGlobal(QPoint(10, 5))]
    family, style = win.column_menu.actions()
    family.trigger()
    style.trigger()
    assert not win.files.isColumnHidden(4) and not win.files.isColumnHidden(5)
    assert header.sectionSize(4) == 140 and header.sectionSize(5) == 140
    style.trigger()
    assert win.files.isColumnHidden(5)
    win._settings.sync()

    restarted = ConverterWindow()
    try:
        assert not restarted.files.isColumnHidden(4)
        assert restarted.files.isColumnHidden(5)
        assert [action.isChecked() for action in restarted.column_menu.actions()] == [True, False]
        assert all(not restarted.files.isColumnHidden(i) for i in range(4))
        restarted.column_menu.actions()[0].trigger()
        restarted._settings.sync()
        assert restarted.files.isColumnHidden(4)
    finally:
        restarted.close()


def test_preferences_are_persisted_between_sessions(win: ConverterWindow) -> None:
    win.overwrite.setChecked(True)
    index = win.conversion.findData("otf2ttf")
    win.conversion.setCurrentIndex(index)
    win.recalc_bboxes.setChecked(False)
    win.organization_levels = (("family",),)
    win.store.set_organization_levels("otf2ttf", win.organization_levels)
    win.profile_options.autohint.setChecked(False)
    win.profile_options.tolerance.setValue(2.5)
    win._save_active_profile_preferences()  # called by closeEvent in real usage
    win._settings.sync()
    assert not win.store.contains("options/overwrite")
    win.store.set_bool("options/overwrite", True)  # legacy setting from an earlier version

    restarted = ConverterWindow()
    try:
        assert not restarted.overwrite.isChecked()
        assert restarted.conversion.currentData() is None
        assert restarted.store.profile is None
        restarted.conversion.setCurrentIndex(restarted.conversion.findData("otf2ttf"))
        assert not restarted.recalc_bboxes.isChecked()
        assert restarted.organization_levels == (("family",),)
        assert not restarted.profile_options.autohint.isChecked()
        assert restarted.profile_options.tolerance.value() == 2.5
    finally:
        restarted.close()


def test_profile_preferences_are_kept_per_profile(win: ConverterWindow) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.organization_levels = (("family", "format"),)
    win.store.set_organization_levels("ttf2otf", win.organization_levels)
    win.profile_options.tolerance.setValue(2.0)

    # Organization levels are profile-scoped: the other profile starts empty,
    # and its options fall back to the factory defaults until customized.
    win.conversion.setCurrentIndex(win.conversion.findData("otf2ttf"))
    assert win.organization_levels == ()
    assert win.profile_options.tolerance.value() == 1.0
    win.organization_levels = (("outline",),)
    win.store.set_organization_levels("otf2ttf", win.organization_levels)
    win.profile_options.tolerance.setValue(0.5)

    # Switching back restores the first profile's preferences.
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    assert win.organization_levels == (("family", "format"),)
    assert win.profile_options.tolerance.value() == 2.0

    win.conversion.setCurrentIndex(win.conversion.findData("otf2ttf"))
    assert win.organization_levels == (("outline",),)
    assert win.profile_options.tolerance.value() == 0.5


def test_reset_button_is_centered_on_heading_text(win: ConverterWindow) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.profile_options.subroutinize.setChecked(False)
    win.show()
    QApplication.processEvents()
    button = win.profile_options.reset_button
    group = button.parentWidget()
    heading = group.findChild(QLabel, "cardHeading")
    assert heading is not None
    text_center_y = heading.mapTo(group, heading.rect().center()).y()
    button_center_y = button.mapTo(group, button.rect().center()).y()
    assert abs(text_center_y - button_center_y) <= 1


def test_profile_options_persist_immediately(win: ConverterWindow) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.profile_options.tolerance.setValue(2.0)
    win.profile_options.subroutinize.setChecked(False)

    stored = win.store.profile_options("ttf2otf")
    assert stored["tolerance"] == 2.0
    assert stored["subroutinize"] is False
    # The other profiles stay untouched.
    assert win.store.profile_options("otf2ttf") == {}


def test_restoring_profile_options_does_not_write_to_store(win: ConverterWindow) -> None:
    win.store.set_profile_options("ttf2otf", {"tolerance": 2.5})
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    assert win.profile_options.tolerance.value() == 2.5

    # Loading a never-customized profile must not create a store entry for it.
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    assert win.store.profile_options("ft2wf") == {}


def test_reset_button_restores_factory_defaults(win: ConverterWindow) -> None:
    win.store.set_profile_options("ttf2otf", {"tolerance": 2.5, "subroutinize": False})
    win.store.set_organization_levels("ttf2otf", (("family",),))
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    assert win.profile_options.tolerance.value() == 2.5
    assert not win.profile_options.subroutinize.isChecked()

    win.profile_options.reset_button.click()

    assert win.profile_options.tolerance.value() == 1.0
    assert win.profile_options.subroutinize.isChecked()
    assert win.store.profile_options("ttf2otf") == {}
    # Organization levels belong to the output card and survive the options reset.
    assert win.store.organization_levels_for("ttf2otf") == (("family",),)


def test_geometry_is_restored_between_sessions(win: ConverterWindow) -> None:
    # The offscreen platform clamps widths above ~798px, so stay below that.
    win.resize(760, 640)
    win.store.set_geometry(win.saveGeometry())
    win._settings.sync()

    restarted = ConverterWindow()
    try:
        assert restarted.size() == QSize(760, 640)
    finally:
        restarted.close()


def test_footer_tracks_selection_and_profile(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait
) -> None:
    _scan(win, [fonts], qtbot_wait)
    assert win.summary.text() == "Choose a conversion to start"
    assert win.convert_button.text() == "Convert"
    assert not win.convert_button.isEnabled()
    assert not win.hide_incompatible.isEnabled()
    win.font_filter.setText("a.ttf")
    assert win.summary.text() == "Choose a conversion to start"
    assert not win.convert_button.isEnabled()
    win.font_filter.clear()

    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    assert "2 fonts selected" in win.summary.text()
    assert win.convert_button.isEnabled()
    win.font_filter.setText("a.ttf")
    assert "1 font selected" in win.summary.text()
    assert win.convert_button.text() == "Convert 1 font"
    win._set_visible_checks(False)
    assert win.summary.text() == "Select compatible fonts or instances to continue."
    assert win.convert_button.text() == "Convert"
    assert not win.convert_button.isEnabled()
    win._clear_files()
    assert win.conversion.currentData() == "ft2wf"
    assert win.summary.text() == "Add fonts to start converting"


def test_footer_summary_omits_output_destination(
    win: ConverterWindow,
    fonts: Path,
    tmp_path: Path,
    qtbot_wait: Wait,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    expected = f"{window_module.CONVERSIONS['ft2wf']} · 2 fonts selected"
    assert win.summary.text() == expected

    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *args: str(output))
    )
    win.destination_folder_radio.setChecked(True)
    assert win.output_directory == output
    assert win.summary.text() == expected
    # No explicit tooltip: the summary only shows one when it is cut short.
    assert win.summary.toolTip() == ""
    elided = win.summary.display_text() != expected
    assert win.summary.tooltip_text() == (expected if elided else "")


def test_modify_rights_confirmation_can_be_remembered(
    win: ConverterWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialogs: list[QMessageBox] = []

    def accept_and_remember(dialog: QMessageBox) -> int:
        dialogs.append(dialog)
        assert dialog.checkBox() is not None
        assert dialog.checkBox().text() == "Remember this choice"
        assert "not responsible for users' violations of font EULAs" in dialog.informativeText()
        dialog.checkBox().setChecked(True)
        return int(QMessageBox.StandardButton.Yes)

    monkeypatch.setattr(QMessageBox, "exec", accept_and_remember)

    assert win._confirm_modify_rights()
    assert win._settings.value(window_module.MODIFY_RIGHTS_KEY, False, type=bool)
    assert win._confirm_modify_rights()
    assert len(dialogs) == 1


def test_modify_rights_confirmation_repeats_when_not_remembered(
    win: ConverterWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialogs: list[QMessageBox] = []

    def accept_without_remembering(dialog: QMessageBox) -> int:
        dialogs.append(dialog)
        assert dialog.checkBox() is not None
        assert not dialog.checkBox().isChecked()
        return int(QMessageBox.StandardButton.Yes)

    monkeypatch.setattr(QMessageBox, "exec", accept_without_remembering)

    assert win._confirm_modify_rights()
    assert win._confirm_modify_rights()
    assert len(dialogs) == 2
    assert not win._settings.contains(window_module.MODIFY_RIGHTS_KEY)


def _flush_deletions() -> None:
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize(
    "answer", [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Cancel]
)
def test_modify_rights_dialog_is_deleted_once_closed(
    win: ConverterWindow, monkeypatch: pytest.MonkeyPatch, answer: QMessageBox.StandardButton
) -> None:
    dialogs: list[QMessageBox] = []

    def answer_dialog(dialog: QMessageBox) -> int:
        dialogs.append(dialog)
        return int(answer)

    monkeypatch.setattr(QMessageBox, "exec", answer_dialog)
    assert win._confirm_modify_rights() == (answer == QMessageBox.StandardButton.Yes)
    _flush_deletions()
    assert not isValid(dialogs[0])
    assert win.findChildren(QMessageBox) == []


@pytest.mark.parametrize("accepted", [True, False])
def test_organization_dialog_is_deleted_once_closed(
    win: ConverterWindow, monkeypatch: pytest.MonkeyPatch, accepted: bool
) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.organization_levels = ()
    shown: list[QDialog] = []

    def fake_exec(dialog: QDialog) -> QDialog.DialogCode:
        shown.append(dialog)
        return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected

    monkeypatch.setattr(window_module.OrganizationDialog, "exec", fake_exec)
    # The levels the user would have chosen (read before the dialog is deleted).
    monkeypatch.setattr(
        window_module.OrganizationDialog, "levels", property(lambda _self: (("family",),))
    )
    win._show_organization_dialog()
    assert win.organization_levels == ((("family",),) if accepted else ())
    _flush_deletions()
    assert not isValid(shown[0])
    assert win.findChildren(window_module.OrganizationDialog) == []


def test_modify_rights_confirmation_cancelled(
    win: ConverterWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QMessageBox, "exec", lambda _dialog: int(QMessageBox.StandardButton.Cancel))
    assert not win._confirm_modify_rights()
    assert not win._settings.contains(window_module.MODIFY_RIGHTS_KEY)


def test_conversion_does_not_start_when_rights_confirmation_is_cancelled(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    monkeypatch.setattr(QMessageBox, "exec", lambda _dialog: int(QMessageBox.StandardButton.Cancel))

    win._start_conversion()

    assert win.worker is None
    assert not win._settings.contains(window_module.MODIFY_RIGHTS_KEY)


@pytest.mark.parametrize("width", [MIN_WIDTH, 1050, 1200])
def test_convert_button_fits_without_profile(
    app_font: None, win: ConverterWindow, width: int
) -> None:
    win.setMinimumSize(MIN_SIZE)
    win.resize(width, 500)
    win.show()
    for _ in range(3):
        QApplication.processEvents()
    button = win.convert_button
    assert button.isVisible() and not button.isEnabled()
    button_rect = button.rect().translated(button.mapTo(win, QPoint()))
    assert win.rect().contains(button_rect)
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    assert not button.isEnabled()


def test_result_status_remains_while_summary_tracks_selection_or_profile(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait
) -> None:
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    result = win.status_pill.message
    assert win.summary_zone.isHidden()
    assert not win.status_pill.chip.isHidden()
    win._update_buttons()
    assert win.status_pill.message == result
    assert win.summary_zone.isHidden()
    win.font_filter.setText("a.ttf")
    assert "1 font selected" in win.summary.text()
    assert win.summary_zone.isHidden()
    assert win.status_pill.message == result
    win.overwrite.setChecked(not win.overwrite.isChecked())
    win._set_output_available(False)
    assert win.status_pill.message == result
    assert not win.status_pill.isHidden()
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    win.conversion.setCurrentIndex(win.conversion.findData("woff2ft"))
    assert win.summary.text() == "No compatible fonts for this conversion"
    assert not win.summary_zone.isHidden()
    assert win.status_pill.isHidden()
    win._set_status("Converting… 0 / 1 · 0.0 s")
    assert win.summary_zone.isHidden()


def test_changing_profile_hides_entire_previous_result(
    win: ConverterWindow, tmp_path: Path
) -> None:
    _ready(win, tmp_path)
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    assert not win.status_pill.isHidden()
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    assert win.status_pill.isHidden()
    assert not win.summary_zone.isHidden()
    win._update_buttons()
    win._set_output_available(True)
    assert win.status_pill.isHidden()
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    assert not win.status_pill.isHidden()
    assert win.status_pill.message


def test_footer_counts_selected_instances(win: ConverterWindow, tmp_path: Path) -> None:
    path = tmp_path / "variable.ttf"
    win._on_font_found(
        path,
        FontInfo(
            path,
            "TTF",
            "TrueType",
            1000,
            variable=True,
            instances=(
                NamedInstanceInfo("Regular", (("wght", 400),)),
                NamedInstanceInfo("Bold", (("wght", 700),)),
            ),
        ),
    )
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    assert win.convert_button.text() == "Convert 2 instances"
    win.instance_tree.topLevelItem(0).child(0).setCheckState(0, Qt.CheckState.Unchecked)
    assert win.convert_button.text() == "Convert 1 instance"
    assert "1 instance selected" in win.summary.text()
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    font = win.instance_tree.topLevelItem(0)
    font.child(1).setCheckState(0, Qt.CheckState.Unchecked)
    font.child(0).setCheckState(0, Qt.CheckState.Checked)
    assert "1 instance selected" in win.summary.text()


@pytest.mark.parametrize(
    ("available", "minimum", "initial"),
    [
        (None, QSize(800, 500), QSize(1200, 880)),
        (QSize(1920, 1080), QSize(800, 500), QSize(1200, 880)),
        (QSize(1024, 768), QSize(800, 500), QSize(984, 688)),
        (QSize(800, 600), QSize(760, 500), QSize(760, 520)),
        (QSize(640, 480), QSize(600, 400), QSize(600, 400)),
    ],
)
def test_window_sizes_fit_available_screen(
    available: QSize | None, minimum: QSize, initial: QSize
) -> None:
    assert _window_sizes(available) == (minimum, initial)


def test_initial_window_fits_available_screen(win: ConverterWindow) -> None:
    screen = win.screen()
    assert screen is not None
    win.show()
    QApplication.processEvents()
    available = screen.availableGeometry()
    assert win.width() <= available.width()
    assert win.height() <= available.height()


def test_import_buttons_use_surface_and_interaction_colors(win: ConverterWindow) -> None:
    win.show()
    win.activateWindow()
    win.conversion.combo.setFocus()
    QApplication.processEvents()
    palette = LIGHT
    for button in (win.add_button,):
        assert button.objectName() == "importButton"
        assert button.height() == styles.BUTTON_HEIGHT
        win.conversion.combo.setFocus()
        QApplication.processEvents()
        mid = button.height() // 2
        # Empty list: "Add files…" is emphasized: accent tint, pressed text_selection_bg.
        assert button.property("emphasis") == "true"
        image = button.grab().toImage()
        assert image.pixelColor(5, mid).name() == palette.accent_tint
        assert image.pixelColor(button.width() // 2, 4).name() == palette.accent_tint
        button.setDown(True)
        QApplication.processEvents()
        image = button.grab().toImage()
        assert image.pixelColor(5, mid).name() == palette.text_selection_bg
        button.setDown(False)
        button.setFocus()
        QApplication.processEvents()
        image = button.grab().toImage()
        assert image.pixelColor(button.width() // 2, 0).name() == palette.accent
        button.setEnabled(False)
        QApplication.processEvents()
        image = button.grab().toImage()
        assert image.pixelColor(5, mid).name() == palette.import_disabled_bg
        button.setEnabled(True)


def test_import_tab_order(win: ConverterWindow, tmp_path: Path) -> None:
    path = tmp_path / "font.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.show()
    win.activateWindow()
    win.clear_button.setEnabled(True)
    QApplication.processEvents()
    win.add_button.setFocus()
    assert win.focusWidget() is win.add_button
    QTest.keyClick(win.add_button, Qt.Key.Key_Tab)
    assert win.focusWidget() is win.add_folder_button
    QTest.keyClick(win.add_folder_button, Qt.Key.Key_Tab)
    assert win.focusWidget() is win.folder_split.arrow_button
    QTest.keyClick(win.folder_split.arrow_button, Qt.Key.Key_Tab)
    assert win.focusWidget() is win.select_all_checkbox
    QTest.keyClick(win.select_all_checkbox, Qt.Key.Key_Tab)
    assert win.focusWidget() is win.font_filter
    QTest.keyClick(win.font_filter, Qt.Key.Key_Tab)
    assert win.focusWidget() is win.hide_incompatible
    QTest.keyClick(win.hide_incompatible, Qt.Key.Key_Tab)
    assert win.focusWidget() is win.clear_button
    QTest.keyClick(win.clear_button, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    assert win.focusWidget() is win.hide_incompatible
    QTest.keyClick(win.hide_incompatible, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    assert win.focusWidget() is win.font_filter
    win.files.setFocus()
    QTest.keyClick(win.files, Qt.Key.Key_Tab)
    assert win.focusWidget() is win.conversion.combo


@pytest.mark.parametrize("conversion", [None, "ttf2otf", "var2static"])
def test_conversion_selector_tab_order_follows_input(
    win: ConverterWindow, tmp_path: Path, conversion: str | None
) -> None:
    if conversion is not None:
        win.conversion.setCurrentIndex(win.conversion.findData(conversion))
    path = tmp_path / "font.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000, variable=True))
    win.show()
    win.activateWindow()
    QApplication.processEvents()
    inputs = win.instance_tree if conversion == "var2static" else win.files
    inputs.setFocus()
    assert win.focusWidget() is inputs

    QTest.keyClick(inputs, Qt.Key.Key_Tab)
    focused = win.focusWidget()
    assert focused is win.conversion.combo
    QTest.keyClick(focused, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    assert win.focusWidget() is inputs


def test_reset_button_tab_order_sits_between_conversion_and_options(
    win: ConverterWindow,
) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.profile_options.subroutinize.setChecked(False)
    win.show()
    win.activateWindow()
    QApplication.processEvents()
    combo = win.conversion.combo
    reset = win.profile_options.reset_button
    combo.setFocus()

    QTest.keyClick(combo, Qt.Key.Key_Tab)
    assert win.focusWidget() is reset
    QTest.keyClick(reset, Qt.Key.Key_Tab)
    assert win.focusWidget() is win.profile_options.tolerance_field.decrement_button
    QTest.keyClick(
        win.profile_options.tolerance_field.decrement_button,
        Qt.Key.Key_Tab,
        Qt.KeyboardModifier.ShiftModifier,
    )
    assert win.focusWidget() is reset
    QTest.keyClick(reset, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    assert win.focusWidget() is combo


@pytest.mark.parametrize("conversion", ["ttf2otf", "otf2ttf"])
@pytest.mark.parametrize("upm_enabled", [False, True])
def test_conversion_options_tab_order(
    win: ConverterWindow, conversion: str, upm_enabled: bool
) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData(conversion))
    profile = win.profile_options
    profile.use_target_upm.setChecked(upm_enabled)
    win.show()
    win.activateWindow()
    profile.tolerance_field.decrement_button.setFocus()
    QApplication.processEvents()

    expected = [
        profile.tolerance_field.decrement_button,
        profile.tolerance,
        profile.tolerance_field.increment_button,
    ]
    if conversion == "ttf2otf":
        expected.extend(
            [
                profile.simplify_field.decrement_button,
                profile.simplify,
                profile.simplify_field.increment_button,
            ]
        )
    expected.append(profile.use_target_upm)
    if upm_enabled:
        expected.extend(
            [
                profile.target_upm_field.decrement_button,
                profile.target_upm,
                profile.target_upm_field.increment_button,
            ]
        )
    expected.append(profile.subroutinize if conversion == "ttf2otf" else profile.autohint)

    for current, following in zip(expected, expected[1:], strict=False):
        assert win.focusWidget() is current
        QTest.keyClick(current, Qt.Key.Key_Tab)
        assert win.focusWidget() is following
    for current, previous in zip(reversed(expected[1:]), reversed(expected[:-1]), strict=False):
        QTest.keyClick(current, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
        assert win.focusWidget() is previous

    tolerance = profile.tolerance.value()
    QTest.keyClick(profile.tolerance_field.decrement_button, Qt.Key.Key_Space)
    assert profile.tolerance.value() == pytest.approx(tolerance - 0.1)
    QTest.keyClick(profile.tolerance_field.increment_button, Qt.Key.Key_Return)
    assert profile.tolerance.value() == pytest.approx(tolerance)


@pytest.mark.parametrize("upm_enabled", [False, True])
def test_variable_conversion_upm_tab_order(win: ConverterWindow, upm_enabled: bool) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    profile = win.profile_options
    profile.use_target_upm.setChecked(upm_enabled)
    win.show()
    win.activateWindow()
    profile.use_target_upm.setFocus()
    QApplication.processEvents()

    expected = [profile.use_target_upm]
    if upm_enabled:
        expected.extend(
            [
                profile.target_upm_field.decrement_button,
                profile.target_upm,
                profile.target_upm_field.increment_button,
            ]
        )
    expected.append(profile.subroutinize)
    for current, following in zip(expected, expected[1:], strict=False):
        assert win.focusWidget() is current
        QTest.keyClick(current, Qt.Key.Key_Tab)
        assert win.focusWidget() is following


def test_conversion_profile_heading_has_extra_top_spacing(win: ConverterWindow) -> None:
    layout = win.conversion_group.layout()
    assert layout is not None
    # The 11px gap below the heading = its 6px bottom margin + a 5px spacer.
    assert layout.itemAt(1).spacerItem().sizeHint().height() == 5
    assert layout.itemAt(2).widget() is win.conversion


def test_add_folder_scans_and_enables_convert(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait
) -> None:
    _scan(win, [fonts, fonts / "missing"], qtbot_wait)
    assert win._sources == [Source(fonts.resolve())]
    assert win.file_list.row_count == 2
    assert not win.convert_button.isEnabled()
    assert win.conversion.currentData() is None
    combo = win.conversion.combo
    assert [
        combo.itemText(i)
        for i in range(combo.count())
        if not combo.model().flags(combo.model().index(i, 0)) & Qt.ItemFlag.ItemIsEnabled
    ] == ["Outlines", "Web fonts", "Other"]
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    assert win.convert_button.isEnabled()
    assert "1 font selected" in win.summary.text()
    assert win.scan_label.text() == "2 fonts"
    assert len(win._selected_input_paths()) >= 1
    win._add_paths([str(fonts)])
    assert len(win._sources) == 1


def test_profile_can_be_chosen_before_input(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait
) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    assert not win.convert_button.isEnabled()
    _scan(win, [fonts], qtbot_wait)
    assert win.convert_button.isEnabled()
    assert "2 fonts selected" in win.summary.text()
    win.font_filter.setText("a.ttf")
    assert "1 font selected" in win.summary.text()


def test_input_choices_survive_profile_changes(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait
) -> None:
    _scan(win, [fonts], qtbot_wait)
    win.font_filter.setText("a.ttf")
    win._set_visible_checks(False)
    win.font_filter.clear()
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    assert not win.convert_button.isEnabled()
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    assert [path.name for path in win._selected_input_paths()] == ["b.otf"]
    win._clear_files()
    combo = win.conversion.combo
    assert all("compatible" not in combo.itemText(i) for i in range(combo.count()))


def test_list_controls_remain_visible_when_filter_matches_nothing(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait
) -> None:
    _scan(win, [fonts], qtbot_wait)
    win.font_filter.setText("no matching font")
    assert win.file_list.row_count == 2
    for control in (win.select_all_checkbox, win.hide_incompatible, win.font_filter):
        assert not control.isHidden()


@pytest.mark.parametrize(
    ("total", "shown", "hidden", "filtered", "expected"),
    [
        (0, 0, 0, False, ""),
        (1, 1, 0, False, "1 font"),
        (167, 167, 0, False, "167 fonts"),
        (167, 163, 4, False, "167 fonts · 4 incompatible hidden"),
        (167, 3, 0, True, "3 of 167 shown"),
        (167, 3, 4, True, "3 of 167 shown · 4 incompatible hidden"),
    ],
)
def test_list_status_text(
    total: int, shown: int, hidden: int, filtered: bool, expected: str
) -> None:
    assert list_status_text(total, shown, hidden, filtered=filtered) == expected


def test_list_status_filter_hide_and_scan_geometry(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.show()
    QApplication.processEvents()
    rect = win.files_stack.geometry()
    slot = win.scan_widget.geometry()
    assert win.scan_label.text() == "2 fonts"
    win.hide_incompatible.setChecked(True)
    assert win.scan_label.text() == "2 fonts · 1 incompatible hidden"
    win.font_filter.setText("a.ttf")
    assert win.scan_label.text() == "1 of 2 shown"
    win.font_filter.setText(".")
    assert win.scan_label.text() == "1 of 2 shown · 1 incompatible hidden"
    win.hide_incompatible.setChecked(False)
    assert win.scan_label.text() == "2 of 2 shown"
    win.font_filter.clear()
    with monkeypatch.context() as patch:
        patch.setattr(type(win.file_list), "scanning", property(lambda _: True))
        win._update_buttons()
        win._on_scan_progress(1, 4)
        QApplication.processEvents()
        assert not win.convert_button.isEnabled()
        assert win.convert_button.toolTip() == "Waiting for the scan to finish"
        assert win.scan_label.text() == "Scanning fonts… 1 / 4"
        assert "scan" not in win.summary.text().lower()
        assert win.files_stack.geometry() == rect
        assert win.scan_widget.geometry() == slot
    win._on_scan_finished()
    QApplication.processEvents()
    assert win.convert_button.toolTip() != "Waiting for the scan to finish"
    assert win.scan_label.text() == "2 fonts"
    assert win.files_stack.geometry() == rect
    assert win.scan_widget.geometry() == slot


def test_scan_progress_uses_running_colors(win: ConverterWindow) -> None:
    win.show()
    win.scan_progress.setRange(0, 4)
    win.scan_progress.setValue(2)
    win.scan_progress.show()
    QApplication.processEvents()
    image = win.scan_progress.grab().toImage()
    assert image.pixelColor(image.width() // 4, 3).name() == LIGHT.accent
    assert image.pixelColor(image.width() * 3 // 4, 3).name() == LIGHT.progress_track
    assert image.pixelColor(image.width() // 2 - 1, 0).name() != LIGHT.accent


def test_variable_list_status_counts_visible_fonts(win: ConverterWindow, tmp_path: Path) -> None:
    variable = tmp_path / "variable.ttf"
    static = tmp_path / "static.ttf"
    win._on_font_found(variable, FontInfo(variable, "TTF", "TrueType", 1000, variable=True))
    win._on_font_found(static, FontInfo(static, "TTF", "TrueType", 1000))
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    assert win.scan_label.text().startswith("2 fonts · 1 variable font")
    win.hide_incompatible.setChecked(True)
    assert win.scan_label.text().startswith("2 fonts · 1 incompatible hidden")
    win.font_filter.setText("variable.ttf")
    assert win.scan_label.text().startswith("1 of 2 shown · 1 variable font")
    win.font_filter.setText("ttf")
    assert win.scan_label.text().startswith("1 of 2 shown · 1 incompatible hidden")


def test_variable_font_selection_follows_input_checks(win: ConverterWindow, tmp_path: Path) -> None:
    path = tmp_path / "variable.ttf"
    info = FontInfo(path, "TTF", "TrueType", 1000, variable=True)
    win._on_font_found(path, info)
    win._set_visible_checks(False)
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    assert win.instance_tree.instance_count() == 0
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    win._set_visible_checks(True)
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    assert win.instance_tree.instance_count() == 1


def test_selected_incompatible_font_shows_full_reason(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait
) -> None:
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.show()
    QApplication.processEvents()
    incompatible = win.file_list.index_for_path(fonts / "b.otf")
    compatible = win.file_list.index_for_path(fonts / "a.ttf")
    assert incompatible.isValid()
    QTest.mouseClick(
        win.files.viewport(),
        Qt.MouseButton.LeftButton,
        pos=win.files.visualRect(incompatible).center(),
    )
    assert "Not a TrueType font" in win.scan_label.text()
    assert win.scan_label.toolTip() == ""
    elided = win.scan_label.display_text() != win.scan_label.text()
    assert win.scan_label.tooltip_text() == (win.scan_label.text() if elided else "")
    win.files.selectRow(compatible.row())
    assert "Not a TrueType font" not in win.scan_label.text()
    win.files.selectRow(incompatible.row())
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    assert "Not a TrueType font" not in win.scan_label.text()
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.files.selectRow(win.file_list.index_for_path(fonts / "b.otf").row())
    win.hide_incompatible.setChecked(True)
    assert "Not a TrueType font" not in win.scan_label.text()


def _row_widgets(win: ConverterWindow) -> list[QWidget]:
    layout = win.file_options_row
    items = (layout.itemAt(i) for i in range(layout.count()))
    return [w for item in items if item is not None and (w := item.widget()) is not None]


def _visible_row_widgets(win: ConverterWindow) -> list[QWidget]:
    return [widget for widget in _row_widgets(win) if not widget.isHidden()]


def test_variable_instance_actions_are_contextual(win: ConverterWindow, tmp_path: Path) -> None:
    assert not hasattr(win, "add_instance_button")
    assert not hasattr(win, "instance_view_controls")
    assert not hasattr(win, "filter_row")
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    assert win.expand_instances_button.isHidden()
    assert win.collapse_instances_button.isHidden()
    path = tmp_path / "variable.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000, variable=True))
    assert not win.expand_instances_button.isHidden()
    assert not win.collapse_instances_button.isHidden()
    font = win.instance_tree.topLevelItem(0)
    win.instance_tree.setCurrentItem(font)
    assert win.instance_tree.can_add()
    win.expand_instances_button.click()
    assert font.isExpanded()
    win.collapse_instances_button.click()
    assert not font.isExpanded()
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    assert win.expand_instances_button.isHidden()
    assert win.collapse_instances_button.isHidden()
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    win._clear_files()
    assert win.expand_instances_button.isHidden()
    assert win.collapse_instances_button.isHidden()


def _opaque_colors(image: QImage) -> set[str]:
    return {
        image.pixelColor(x, y).name()
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() == 255
    }


def test_instance_view_buttons_are_icon_only(win: ConverterWindow) -> None:
    for button, name in (
        (win.expand_instances_button, "Expand all"),
        (win.collapse_instances_button, "Collapse all"),
    ):
        assert button.text() == ""
        assert not button.icon().isNull()
        assert button.iconSize() == QSize(16, 16)
        size = styles.BUTTON_HEIGHT
        assert button.minimumSize() == button.maximumSize() == QSize(size, size)
        assert button.toolTip() == name
        assert button.accessibleName() == name
        assert button.objectName() == "quietIconButton"
        # Muted glyph at rest, full text color while hovered.
        rest = button.icon().pixmap(QSize(16, 16), 2.0).toImage()
        assert _opaque_colors(rest) == {LIGHT.text_muted}
        button.enterEvent(QEnterEvent(QPointF(), QPointF(), QPointF()))
        hover = button.icon().pixmap(QSize(16, 16), 2.0).toImage()
        assert _opaque_colors(hover) == {LIGHT.text}
        button.leaveEvent(QEvent(QEvent.Type.Leave))
        assert _opaque_colors(button.icon().pixmap(QSize(16, 16), 2.0).toImage()) == {
            LIGHT.text_muted
        }


def test_clear_list_is_a_ghost_button(win: ConverterWindow, tmp_path: Path) -> None:
    path = tmp_path / "font.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    win.resize(1200, 880)
    win.show()
    QApplication.processEvents()
    button = win.clear_button
    button.setEnabled(True)  # enabled with added sources; _on_font_found adds none
    QApplication.processEvents()
    assert button.objectName() == "ghostButton"
    assert button.accessibleName() == "Clear list"
    assert button.icon().isNull()
    assert button.height() == styles.BUTTON_HEIGHT
    assert button.palette().color(button.foregroundRole()).name() == LIGHT.text

    def sample() -> str:
        image = win.grab(_rect_in_window(win, button)).toImage()
        scale = image.devicePixelRatio()
        return image.pixelColor(round(6 * scale), round(button.height() // 2 * scale)).name()

    # No background at rest: the card shows through.
    assert sample() == LIGHT.surface
    button.setDown(True)
    QApplication.processEvents()
    assert sample() == LIGHT.ghost_pressed
    button.setDown(False)
    button.setEnabled(False)
    QApplication.processEvents()
    assert button.palette().color(button.foregroundRole()).name() == LIGHT.text_disabled
    # 8px between the toolbar controls.
    assert win.file_options_row.spacing() == 8


def _features(font: QFont) -> dict[str, int]:
    return {tag.toString().data().decode(): font.featureValue(tag) for tag in font.featureTags()}


def test_table_and_tree_fonts_have_slashed_zero_and_tabular_figures(
    win: ConverterWindow, tmp_path: Path
) -> None:
    from fontvertx.inspection import AxisInfo, NamedInstanceInfo

    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    path = tmp_path / "variable.ttf"
    info = FontInfo(
        path,
        "TTF",
        "TrueType",
        1000,
        variable=True,
        axes=(AxisInfo("wght", 100, 400, 900),),
        instances=(NamedInstanceInfo("Thin", (("wght", 100.0),)),),
    )
    win._on_font_found(path, info)
    static = tmp_path / "static.ttf"
    win.file_list.add_font(static, static.name, FontInfo(static, "TTF", "TrueType", 2048), True)
    wanted = {"ss02": 1, "tnum": 1}
    tree = win.instance_tree
    parent = tree.topLevelItem(0)
    fonts = [
        win.files.font(),
        win.files.horizontalHeader().font(),
        win.file_list.model.data(win.file_list.model.index(0, 3), Qt.ItemDataRole.FontRole),  # UPM
        tree.font(),
        tree.header().font(),
        parent.font(3),  # UPM
        parent.child(0).font(4),  # axis location
    ]
    for font in fonts:
        assert _features(font) == wanted
    # Monospaced chips are left alone.
    from fontvertx.gui.styles import chip_font

    assert "ss02" not in _features(chip_font())


def test_reset_is_a_ghost_button_and_keeps_the_header_height(win: ConverterWindow) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.resize(1200, 880)
    win.show()
    QApplication.processEvents()
    reset = win.profile_options.reset_button
    assert reset.objectName() == "ghostButton"
    assert reset.accessibleName() == "Restore default options"
    assert reset.height() == styles.BUTTON_HEIGHT
    header_row = win.profile_options.layout().itemAt(0).layout()
    assert header_row.geometry().height() == styles.BUTTON_HEIGHT
    assert not reset.isEnabled()  # options at defaults
    assert reset.palette().color(reset.foregroundRole()).name() == LIGHT.text_disabled
    win.profile_options.subroutinize.setChecked(not win.profile_options.subroutinize.isChecked())
    QApplication.processEvents()
    assert reset.isEnabled()
    assert reset.palette().color(reset.foregroundRole()).name() == LIGHT.text
    assert header_row.geometry().height() == styles.BUTTON_HEIGHT


def test_location_header_lines_up_with_the_cell_text() -> None:
    sheet = styles.build_stylesheet(LIGHT)
    block = sheet[sheet.index("QTreeWidget#instanceTree QHeaderView::section:last {") :]
    inset = styles.ITEM_PADDING_LEFT + styles.ITEM_TEXT_MARGIN
    assert f"padding-left: {inset}px;" in block.split("}", 1)[0]


def test_variable_row_chevrons_are_muted(win: ConverterWindow) -> None:
    icons = win.instance_tree._branch_icons
    for expanded in (False, True):
        rest = icons[(expanded, False)].pixmap(QSize(18, 18), 2.0).toImage()
        hover = icons[(expanded, True)].pixmap(QSize(18, 18), 2.0).toImage()
        assert _opaque_colors(rest) == {LIGHT.text_muted}
        assert _opaque_colors(hover) == {LIGHT.text}


def test_filter_row_contents_follow_the_profile(
    win: ConverterWindow, fonts: Path, tmp_path: Path, qtbot_wait: Wait
) -> None:
    first_four = [win.select_all_checkbox, win.font_filter, win.hide_incompatible, win.clear_button]
    assert _row_widgets(win) == [
        *first_four,
        win.expand_instances_button,
        win.collapse_instances_button,
    ]
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    assert _visible_row_widgets(win) == first_four
    # Outside instance mode the tree, and with it the "+ Instance" row action, is not shown.
    assert win.files_stack.currentWidget() is win.files
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    assert win.files_stack.currentWidget() is win.instance_tree
    path = tmp_path / "variable.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000, variable=True))
    assert _visible_row_widgets(win) == _row_widgets(win)


def test_instance_tree_starts_right_below_the_filter_row(
    win: ConverterWindow, tmp_path: Path
) -> None:
    """No second row of controls: the list starts one layout gap below the filter row."""
    win.resize(1600, 880)
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    path = tmp_path / "variable.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000, variable=True))
    win.show()
    for _ in range(3):
        QApplication.processEvents()
    assert win.file_options_row.direction() == window_module.QBoxLayout.Direction.LeftToRight
    row_bottom = max(
        widget.mapTo(win.files_group, widget.rect().bottomLeft()).y()
        for widget in _visible_row_widgets(win)
    )
    gap = win.files_stack.y() - row_bottom - 1
    assert gap == win.files_group_layout.spacing()


@pytest.mark.parametrize("width", [MIN_WIDTH, 1055, 1200, 1400, 2000])
def test_instance_toolbar_fits_input_area(win: ConverterWindow, tmp_path: Path, width: int) -> None:
    win.setMinimumSize(MIN_SIZE)
    win.resize(width, 500)
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    path = tmp_path / "variable.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000, variable=True))
    win.show()
    QApplication.processEvents()
    controls = (
        win.select_all_checkbox,
        win.font_filter,
        win.hide_incompatible,
        win.clear_button,
        win.expand_instances_button,
        win.collapse_instances_button,
    )
    for _ in range(3):
        QApplication.processEvents()
    rectangles = []
    for widget in controls:
        bounds = widget.rect().translated(widget.mapTo(win.files_group, widget.rect().topLeft()))
        assert win.files_group.rect().contains(bounds)
        assert all(not bounds.intersects(other) for other in rectangles)
        rectangles.append(bounds)
    assert win.font_filter.width() >= 40
    if win.file_options_row.direction() == window_module.QBoxLayout.Direction.LeftToRight:
        right = win.collapse_instances_button.mapTo(
            win.files_group, win.collapse_instances_button.rect().topRight()
        ).x()
        expected_right = (
            win.files_group.width()
            - win.files_group.layout().contentsMargins().right()
            - CARD_INSET
            - 1
        )
        assert expected_right - win.file_options_row.spacing() <= right <= expected_right + 1
        centers = [bounds.center().y() for bounds in rectangles]
        assert max(centers) - min(centers) <= 1
        # Clear list, expand, collapse: left to right at the end of the row.
        assert rectangles[3].right() < rectangles[4].left() < rectangles[5].left()
    else:
        assert all(
            upper.bottom() < lower.top()
            for upper, lower in zip(rectangles, rectangles[1:], strict=False)
        )


def test_instance_toolbar_wraps_when_space_is_limited(win: ConverterWindow, tmp_path: Path) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    path = tmp_path / "variable.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000, variable=True))
    win._update_input_layout(100)
    assert win.file_options_row.direction() == window_module.QBoxLayout.Direction.TopToBottom
    win._update_input_layout(1000)
    assert win.file_options_row.direction() == window_module.QBoxLayout.Direction.LeftToRight


def test_filter_row_breakpoint_counts_the_icon_buttons(
    win: ConverterWindow, tmp_path: Path
) -> None:
    """The row switches to vertical earlier in instance mode, where it holds two more buttons."""
    horizontal = window_module.QBoxLayout.Direction.LeftToRight
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    static_path = tmp_path / "a.ttf"
    win._on_font_found(static_path, FontInfo(static_path, "TTF", "TrueType", 1000))

    def breakpoint_width() -> int:
        width = 100
        while True:
            win._update_input_layout(width)
            if win.file_options_row.direction() == horizontal:
                return width
            width += 1

    static_breakpoint = breakpoint_width()
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    path = tmp_path / "variable.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000, variable=True))
    extra = 2 * (styles.BUTTON_HEIGHT + win.file_options_row.spacing())
    assert breakpoint_width() == static_breakpoint + extra


def test_instance_toolbar_tab_order(win: ConverterWindow, tmp_path: Path) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    path = tmp_path / "variable.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000, variable=True))
    win.instance_tree.setCurrentItem(win.instance_tree.topLevelItem(0))
    win.show()
    win.activateWindow()
    QApplication.processEvents()
    win.hide_incompatible.setFocus()
    QTest.keyClick(win.hide_incompatible, Qt.Key.Key_Tab)
    if win.clear_button.isEnabled():
        assert win.focusWidget() is win.clear_button
        QTest.keyClick(win.clear_button, Qt.Key.Key_Tab)
    assert win.focusWidget() is win.expand_instances_button
    QTest.keyClick(win.expand_instances_button, Qt.Key.Key_Tab)
    assert win.focusWidget() is win.collapse_instances_button


def test_select_all_and_clear(win: ConverterWindow, fonts: Path, qtbot_wait: Wait) -> None:
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win._set_visible_checks(False)
    assert win._selected_input_paths() == []
    assert not win.convert_button.isEnabled()
    win._set_visible_checks(True)
    assert win.convert_button.isEnabled()
    win._clear_files()
    assert win._sources == []
    assert not win.clear_button.isEnabled()


def test_output_controls_follow_visual_tab_order(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait
) -> None:
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.show()
    QApplication.processEvents()
    win.organization_button.setFocus()
    QTest.keyClick(win.organization_button, Qt.Key.Key_Tab)
    assert win.focusWidget() is win.convert_button
    QTest.keyClick(win.convert_button, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    assert win.focusWidget() is win.organization_button


def test_save_options_follow_profile_options_in_tab_order(win: ConverterWindow) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData("woff2ft"))
    win.show()
    QApplication.processEvents()
    win.recalc_bboxes.setFocus()
    QTest.keyClick(win.recalc_bboxes, Qt.Key.Key_Tab)
    assert win.focusWidget() is win.recalc_timestamp
    QTest.keyClick(win.recalc_timestamp, Qt.Key.Key_Tab)
    assert win.focusWidget() is win.reorder_tables
    QTest.keyClick(win.reorder_tables, Qt.Key.Key_Tab)
    assert win.focusWidget() is win.destination_source_radio


@pytest.mark.parametrize("conversion", [None, "ttf2otf", "ft2wf", "var2static"])
def test_general_settings_are_in_output_card(win: ConverterWindow, conversion: str | None) -> None:
    win.resize(1400, 900)
    if conversion is not None:
        win.conversion.setCurrentIndex(win.conversion.findData(conversion))
    win.show()
    QApplication.processEvents()
    organization = win.organization_button
    assert organization.isVisible() and organization.isEnabled()
    assert organization.mapTo(win.destination_group, organization.rect().topLeft()).y() > (
        win.overwrite.mapTo(win.destination_group, win.overwrite.rect().bottomLeft()).y()
    )
    assert win.sidebar_scroll.horizontalScrollBar().maximum() == 0


@pytest.mark.parametrize("width", [MIN_WIDTH, 1400])
def test_output_button_keeps_size_hint_at_different_sizes(win: ConverterWindow, width: int) -> None:
    win.setMinimumSize(MIN_SIZE)
    win.resize(width, 600)
    win.show()
    QApplication.processEvents()
    assert win.organization_button.width() >= win.organization_button.sizeHint().width()


@pytest.mark.parametrize("width", [MIN_WIDTH, 1200])
def test_footer_actions_remain_visible_after_conversion(
    app_font: None, win: ConverterWindow, width: int, tmp_path: Path
) -> None:

    win.setMinimumSize(MIN_SIZE)
    win.resize(width, 500)
    win.show()
    _ready(win, tmp_path)
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    QApplication.processEvents()
    QApplication.processEvents()
    for button in (win.convert_button, win.view_log_button, win.open_output_button):
        assert button.isVisible()
        assert win.rect().contains(button.mapTo(win, button.rect().topLeft()))
        assert win.rect().contains(button.mapTo(win, button.rect().bottomRight()))
    for button, name in (
        (win.view_log_button, "View log"),
        (win.open_output_button, "Open output folder"),
    ):
        assert button.accessibleName() == button.toolTip() == name
        assert button.text() in ("", name)
    assert win.status_pill.pill_layout.indexOf(win.status_pill.result_buttons) >= 0


def _edges(win: ConverterWindow, widget: QWidget) -> tuple[int, int]:
    """Left and right edge (inclusive) of ``widget`` in window coordinates."""
    left = widget.mapTo(win, QPoint()).x()
    return left, left + widget.width() - 1


def _assert_footer_aligned(win: ConverterWindow) -> None:
    """One footer card spanning the content above; Convert fixed and centered in it."""
    card = win.footer_card
    card_edges = _edges(win, card)
    assert card_edges[0] == _edges(win, win.files_group)[0]
    assert card_edges[1] == _edges(win, win.conversion_group)[1]
    assert card.height() == styles.FOOTER_CARD_HEIGHT
    assert win.footer.height() == styles.FOOTER_CARD_HEIGHT + styles.FOOTER_GAP
    convert = win.primary_slot  # Convert, or Pause / Cancel in its place
    assert convert.height() == styles.FOOTER_HEIGHT
    assert convert.minimumWidth() == convert.maximumWidth() == convert.width()
    assert win.convert_button.width() == convert.width()
    top = convert.mapTo(card, QPoint()).y()
    assert top == styles.FOOTER_PAD_V
    assert card.height() - top - convert.height() == styles.FOOTER_PAD_V
    assert card_edges[1] - _edges(win, convert)[1] == styles.FOOTER_PAD_RIGHT
    card_rect = QRect(card.mapTo(win, QPoint()), card.size())
    convert_rect = QRect(convert.mapTo(win, QPoint()), convert.size())
    pill = win.status_pill
    shown = [
        child
        for child in (
            pill.icon,
            pill.label,
            pill.run_view,
            pill.chip,
            pill.counts,
            pill.result_buttons,
            pill.close_button,
        )
        if pill.isVisible() and child.isVisible()
    ]
    for child in shown:
        child_rect = QRect(child.mapTo(win, QPoint()), child.size())
        assert card_rect.contains(child_rect)
        assert not child_rect.intersects(convert_rect)


def test_footer_card_spans_the_content_at_preferred_size(
    app_font: None, win: ConverterWindow, tmp_path: Path
) -> None:
    win.resize(1200, 880)
    win.show()
    for _ in range(5):
        QApplication.processEvents()
    widths, heights = [], []

    def measure() -> None:
        for _ in range(3):
            QApplication.processEvents()
        _assert_footer_aligned(win)
        widths.append(win.convert_button.width())
        heights.append(win.footer.height())

    measure()  # empty
    assert win.body_layout.direction() == window_module.QBoxLayout.Direction.LeftToRight
    card = _edges(win, win.footer_card)
    assert card == (_edges(win, win.files_group)[0], _edges(win, win.sidebar_scroll)[1])
    for sidebar_card in (win.conversion_group, win.profile_options, win.destination_group):
        assert _edges(win, sidebar_card)[1] == card[1]
    _ready(win, tmp_path)
    measure()  # ready
    win.converter.outcome.total = 1
    win._set_run_status(StatusState.RUNNING)
    measure()  # converting
    assert win.footer_card.property("tone") == "running"
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    measure()  # done
    assert win.footer_card.property("tone") == "success"
    assert len(set(widths)) == 1, widths
    assert len(set(heights)) == 1, heights
    assert "QWidget#actionBar" not in win.styleSheet()


@pytest.mark.parametrize("width", [1049, 1050, 1054, 1055, 1200])
@pytest.mark.parametrize("scrollbar_visible", [False, True])
def test_footer_card_follows_the_body_and_scrollbar(
    win: ConverterWindow, width: int, scrollbar_visible: bool, tmp_path: Path
) -> None:

    win.resize(width, 600)
    win.content_scroll.setVerticalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        if scrollbar_visible
        else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    win.show()
    _ready(win, tmp_path)
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    for _ in range(3):
        QApplication.processEvents()
    button = win.convert_button
    assert button.isVisible() and button.height() == styles.FOOTER_HEIGHT
    assert win.rect().contains(button.mapTo(win, button.rect().bottomRight()))
    outer = win.footer_outer_layout.contentsMargins()
    assert outer.left() == layout_manager.PAGE_MARGIN_H
    assert outer.bottom() == styles.FOOTER_GAP
    scrollbar = win.content_scroll.verticalScrollBar()
    inset = scrollbar.width() if scrollbar.isVisible() else 0
    assert outer.right() == layout_manager.PAGE_MARGIN_H + inset
    assert win.status_pill.height() == styles.FOOTER_HEIGHT
    _assert_footer_aligned(win)
    assert win.summary_zone.isHidden()
    for widget in (win.status_pill.chip, win.view_log_button, win.open_output_button):
        assert widget.isVisible()
        assert win.rect().contains(widget.mapTo(win, widget.rect().bottomRight()))


@pytest.mark.parametrize("width", [MIN_WIDTH, 1055, 1200])
def test_footer_geometry_does_not_jump_across_states(
    win: ConverterWindow, width: int, tmp_path: Path
) -> None:
    win.setMinimumSize(MIN_SIZE)
    win.resize(width, 600)
    _ready(win, tmp_path)
    win.show()
    for _ in range(3):  # the footer follows the scrollbar one event-loop turn later
        QApplication.processEvents()
    baseline = (
        win.footer.geometry(),
        win.content_scroll.geometry(),
        win.primary_slot.geometry(),
        win.status_zone.geometry(),
        win.files_group.mapTo(win, QPoint()),
    )
    win.converter.outcome.total = 1
    win.worker = _fake_worker(win)
    for state in (
        StatusState.RUNNING,
        StatusState.PAUSED,
        StatusState.CANCELLED,
        StatusState.DONE,
        StatusState.WARNING,
        StatusState.ERRORS,
        StatusState.FAILED,
        StatusState.FATAL,
    ):
        win._set_run_status(state, detail="failure" if state is StatusState.FATAL else "")
        win._update_buttons()
        QApplication.processEvents()
        active = state in (StatusState.RUNNING, StatusState.PAUSED)
        assert win.primary_slot.currentWidget() is (
            win.run_controls if active else win.convert_button
        )
        assert (
            win.footer.geometry(),
            win.content_scroll.geometry(),
            win.primary_slot.geometry(),
            win.status_zone.geometry(),
            win.files_group.mapTo(win, QPoint()),
        ) == baseline
        assert win.status_pill.height() == styles.FOOTER_HEIGHT
        _assert_footer_aligned(win)
    win.worker = None
    win._update_buttons()
    QApplication.processEvents()
    win._dismiss_status()
    QApplication.processEvents()
    assert win.footer.geometry() == baseline[0]
    assert win.content_scroll.geometry() == baseline[1]
    assert win.files_group.mapTo(win, QPoint()) == baseline[4]


def test_footer_swaps_convert_for_pause_and_cancel_during_a_run(
    win: ConverterWindow, tmp_path: Path
) -> None:
    _ready(win, tmp_path)
    win.show()
    assert win.convert_button.text() == "Convert 1 font"
    assert win.convert_button.isEnabled()
    win.convert_button.setFocus(Qt.FocusReason.TabFocusReason)
    win.worker = _fake_worker(win)
    win._run_state = RunState.RUNNING
    win._set_run_status(StatusState.RUNNING)
    win._update_buttons()
    # Convert disappears; Pause and Cancel take its place and Pause gets the focus.
    assert win.primary_slot.currentWidget() is win.run_controls
    assert win.convert_button.isHidden()
    assert not win.convert_button.isEnabled()
    assert not win.pause_button.isHidden() and not win.cancel_button.isHidden()
    assert win.focusWidget() is win.pause_button
    assert win.pause_button.text() == "Pause"
    # The cards stay visible but cannot be changed; the scroll areas still work.
    for card in (win.files_group, win.conversion_group, win.profile_options, win.destination_group):
        assert not card.isEnabled()
        assert not card.isHidden()
    assert win.content_scroll.isEnabled() and win.sidebar_scroll.isEnabled()
    assert not win.files.acceptDrops() and not win.drop_zone.acceptDrops()
    # View log stays reachable during the run; the output folder is not shown.
    assert not win.view_log_button.isHidden() and win.open_output_button.isHidden()
    win._run_state = RunState.PAUSED
    win._set_run_status(StatusState.PAUSED)
    win._update_buttons()
    assert win.pause_button.text() == "Resume"
    assert win.pause_button.property("runPrimary") is True
    assert win.primary_slot.currentWidget() is win.run_controls
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    # A result: Convert is back (enabled once the worker has stopped), cards unlocked.
    assert win.primary_slot.currentWidget() is win.convert_button
    assert win.focusWidget() is not win.pause_button
    for card in (win.files_group, win.conversion_group, win.profile_options, win.destination_group):
        assert card.isEnabled()
    assert win.files.acceptDrops() and win.drop_zone.acceptDrops()
    win.worker = None
    win._run_state = RunState.IDLE
    win._update_buttons()
    assert win.convert_button.isEnabled()
    assert win.convert_button.text() == "Convert 1 font"
    assert not win.convert_button.icon().isNull()
    win._set_visible_checks(False)
    assert win.convert_button.text() == "Convert"
    assert win.convert_button.icon().isNull()
    # The footer summary already says why; the button adds nothing.
    assert win.summary.text() == "Select compatible fonts or instances to continue."
    assert win.convert_button.toolTip() == ""
    assert not win.status_pill.isHidden()


def test_ctrl_enter_does_nothing_during_a_run(
    win: ConverterWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ready(win, tmp_path)
    started: list[object] = []
    monkeypatch.setattr(win.converter, "start", lambda *args: started.append(args))
    monkeypatch.setattr(win, "_confirm_modify_rights", lambda: True)
    win.worker = _fake_worker(win)
    win._run_state = RunState.RUNNING
    win._set_run_status(StatusState.RUNNING)
    win._update_buttons()
    for shortcut in win.convert_shortcuts:
        shortcut.activated.emit()
    win._start_conversion()
    assert started == []
    win.worker = None


def test_drops_and_wheel_while_cards_are_locked(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait, tmp_path: Path
) -> None:
    for index in range(40):
        shutil.copy(fonts / "a.ttf", fonts / f"copy{index}.ttf")
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.resize(1200, 600)
    win.show()
    QApplication.processEvents()
    win.worker = _fake_worker(win)
    win._run_state = RunState.RUNNING
    win._set_run_status(StatusState.RUNNING)
    win._update_buttons()
    count = win.file_list.row_count
    extra = tmp_path / "extra"
    extra.mkdir()
    shutil.copy(fonts / "a.ttf", extra / "extra.ttf")
    win.files.paths_dropped.emit([str(extra)])
    win.drop_zone.paths_dropped.emit([str(extra)])
    assert win.file_list.row_count == count
    assert [source.path for source in win._sources] == [fonts.resolve()]
    bar = win.files.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(0)
    viewport = win.files.viewport()
    center = QPointF(viewport.rect().center())
    event = QWheelEvent(
        center,
        QPointF(viewport.mapToGlobal(viewport.rect().center())),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(viewport, event)
    assert bar.value() > 0
    win.worker = None
    win._update_buttons()
    win.files.paths_dropped.emit([str(extra)])
    assert extra.resolve() in [source.path for source in win._sources]


def test_summary_log_link_after_dismiss_and_profile_change(
    win: ConverterWindow, tmp_path: Path
) -> None:
    _ready(win, tmp_path)
    assert win.history_button.isHidden()
    assert win.history_button.text() == "View log"
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    win._dismiss_status()
    assert not win.history_button.isHidden()
    assert not win.status_pill.isVisible()
    win.history_button.click()
    assert win.log_window.isVisible()
    assert not win.log_window.isModal()
    win.log_window.close()
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    assert win.status_pill.isHidden()
    assert not win.history_button.isHidden()


def test_view_log_opens_one_non_modal_window_and_raises_it(
    win: ConverterWindow, tmp_path: Path
) -> None:
    _ready(win, tmp_path)
    win.show()
    win._append_log(LogEntry.create("INFO", "conversion.started", "Started", {}))
    win.worker = _fake_worker(win)
    win._run_state = RunState.RUNNING
    win._set_run_status(StatusState.RUNNING)
    win._update_buttons()
    # During the run, View log stays reachable beside the progress.
    assert win.view_log_button.isEnabled() and not win.view_log_button.isHidden()
    assert win.view_log_button.accessibleName() == "View log"
    win.view_log_button.click()
    window = win.log_window
    assert window.isVisible() and not window.isModal()
    assert window.windowModality() is Qt.WindowModality.NonModal
    assert window.chip.text() == "Running"
    # Live log: new entries appear while it is open.
    before = window.log.count()
    win._append_log(LogEntry.create("INFO", "font.converted", "Converted a.ttf", {}))
    assert window.log.count() == before + 1
    # The main window is still usable: the footer controls work.
    assert win.pause_button.isEnabled()
    window.showMinimized()
    win.view_log_button.click()
    assert window.isVisible() and not window.isMinimized()
    assert [w for w in QApplication.topLevelWidgets() if isinstance(w, type(window))] == [window]
    win._run_state = RunState.PAUSED
    win._set_run_status(StatusState.PAUSED)
    assert window.chip.text() == "Paused"
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    assert window.chip.text() == "Done"
    # Closing the log stops nothing.
    window.close()
    assert win.status_pill.state is StatusState.DONE
    win.worker = None


@pytest.mark.parametrize(
    ("result", "chip"),
    [
        (lambda: ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)), "Done"),
        (
            lambda: ConversionResult(
                (
                    _outcome(FontOutcomeKind.CONVERTED),
                    _outcome(FontOutcomeKind.FAILED, "ValueError: bad", "b.ttf"),
                )
            ),
            "1 failed",
        ),
    ],
)
def test_narrow_footer_shows_result_actions_as_icons(
    app_font: None, win: ConverterWindow, tmp_path: Path, result: Any, chip: str
) -> None:
    win.setMinimumSize(MIN_SIZE)
    win.resize(MIN_SIZE)
    win.show()
    _ready(win, tmp_path)
    _finished(win, result())
    win._set_output_available(True)
    for _ in range(3):
        QApplication.processEvents()
    assert win.footer_card.width() <= 760
    pill = win.status_pill
    assert pill.chip.text() == chip
    assert pill.compact
    for button, name in (
        (win.view_log_button, "View log"),
        (win.open_output_button, "Open output folder"),
    ):
        assert button.text() == ""
        assert button.accessibleName() == button.toolTip() == name
        assert not button.icon().isNull()
        assert button.width() == button.height() == 38
        assert button.isVisible()
    # One line, never wrapped: the counts shrink with an ellipsis.
    assert pill.counts.height() <= pill.height()
    assert pill.chip.height() < pill.height()
    _assert_footer_aligned(win)
    # Wide again: the labels come back.
    win.resize(1200, MIN_SIZE.height())
    for _ in range(3):
        QApplication.processEvents()
    assert not pill.compact
    assert win.view_log_button.text() == "View log"
    assert win.open_output_button.text() == "Open output folder"


def test_narrow_footer_keeps_run_buttons_whole(
    app_font: None, win: ConverterWindow, tmp_path: Path
) -> None:
    win.setMinimumSize(MIN_SIZE)
    win.resize(MIN_SIZE)
    win.show()
    _ready(win, tmp_path)
    win.converter.current_input = tmp_path / ("very-long-folder-name-" * 8) / "font.ttf"
    win.converter.outcome.total = 146
    win.worker = _fake_worker(win)
    win._run_state = RunState.RUNNING
    win._set_run_status(StatusState.RUNNING)
    win._update_buttons()
    for _ in range(3):
        QApplication.processEvents()
    pill = win.status_pill
    for button in (win.pause_button, win.cancel_button):
        assert button.text() and button.width() >= button.minimumSizeHint().width()
    assert pill.run_file.display_text() != pill.run_file.text()
    assert "…" in pill.run_file.display_text()
    assert pill.run_file.display_text().endswith("font.ttf")  # elided in the middle
    _assert_footer_aligned(win)
    win.worker = None


def _run_with_logs(win: ConverterWindow, width: int) -> None:
    """A wide or narrow window with a run in progress (View log enabled)."""
    win.setMinimumSize(MIN_SIZE)
    win.resize(width, 600)
    win.show()
    win._append_log(LogEntry.create("INFO", "conversion.started", "Started", {}))
    win.converter.outcome.total = 4
    win.worker = _fake_worker(win)
    win._run_state = RunState.RUNNING
    win._set_run_status(StatusState.RUNNING)
    win._update_buttons()
    for _ in range(3):
        QApplication.processEvents()


def _labelled(win: ConverterWindow) -> bool:
    return win.view_log_button.text() == "View log" and not win.status_pill.compact


def _icon_only(win: ConverterWindow) -> bool:
    return win.status_pill.compact and all(
        button.text() == "" and button.size() == QSize(38, 38)
        for button in (win.view_log_button, win.open_output_button)
    )


def _cards_side_by_side(win: ConverterWindow) -> bool:
    return win.body_layout.direction() == window_module.QBoxLayout.Direction.LeftToRight


@pytest.mark.parametrize("width", [layout_manager.BODY_BREAKPOINT, 1200])
def test_result_buttons_labelled_with_cards_side_by_side(win: ConverterWindow, width: int) -> None:
    _run_with_logs(win, width)
    assert _cards_side_by_side(win)
    assert _labelled(win)  # during the run
    win._run_state = RunState.PAUSED
    win._set_run_status(StatusState.PAUSED)
    assert _labelled(win)
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    win._set_output_available(True)
    for _ in range(3):
        QApplication.processEvents()
    assert _labelled(win)  # after it
    assert win.open_output_button.text() == "Open output folder"
    win.worker = None


@pytest.mark.parametrize("width", [MIN_WIDTH, layout_manager.BODY_BREAKPOINT - 1])
def test_result_buttons_icon_only_with_stacked_cards(win: ConverterWindow, width: int) -> None:
    _run_with_logs(win, width)
    assert not _cards_side_by_side(win)
    assert _icon_only(win)  # during the run
    assert win.view_log_button.accessibleName() == win.view_log_button.toolTip() == "View log"
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    win._set_output_available(True)
    for _ in range(3):
        QApplication.processEvents()
    assert _icon_only(win)  # after it
    assert win.open_output_button.accessibleName() == "Open output folder"
    win.worker = None


def test_resizing_across_the_breakpoint_switches_cards_and_buttons_together(
    win: ConverterWindow,
) -> None:
    wide, narrow = 1200, layout_manager.BODY_BREAKPOINT - 1

    def resize(width: int) -> None:
        win.resize(width, 600)
        for _ in range(3):
            QApplication.processEvents()

    _run_with_logs(win, wide)
    assert _cards_side_by_side(win) and _labelled(win)
    resize(narrow)
    assert not _cards_side_by_side(win) and _icon_only(win)
    resize(wide)
    assert _cards_side_by_side(win) and _labelled(win)
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    win._set_output_available(True)
    resize(narrow)
    assert not _cards_side_by_side(win) and _icon_only(win)
    resize(wide)
    assert _cards_side_by_side(win) and _labelled(win)
    win.worker = None


@pytest.mark.parametrize(
    "width", [MIN_WIDTH, layout_manager.BODY_BREAKPOINT - 1, layout_manager.BODY_BREAKPOINT, 1200]
)
def test_convert_pause_and_cancel_always_keep_their_labels(
    win: ConverterWindow, tmp_path: Path, width: int
) -> None:
    _ready(win, tmp_path)
    win.setMinimumSize(MIN_SIZE)
    win.resize(width, 600)
    win.show()
    for _ in range(3):
        QApplication.processEvents()
    slot_width = win.primary_slot.width()
    assert win.convert_button.text() == "Convert 1 font"
    win.worker = _fake_worker(win)
    for state, run_state in (
        (StatusState.RUNNING, RunState.RUNNING),
        (StatusState.PAUSED, RunState.PAUSED),
        (StatusState.RUNNING, RunState.RUNNING),
    ):
        win._run_state = run_state
        win._set_run_status(state)
        win._update_buttons()
        QApplication.processEvents()
        assert win.pause_button.text() == ("Resume" if run_state is RunState.PAUSED else "Pause")
        assert win.cancel_button.text() == "Cancel"
        assert win.primary_slot.width() == slot_width
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    win.worker = None
    win._run_state = RunState.IDLE
    win._update_buttons()
    QApplication.processEvents()
    assert win.convert_button.text() == "Convert 1 font"
    assert win.primary_slot.width() == slot_width


@pytest.mark.parametrize("width", [MIN_WIDTH, 1200])
def test_state_changes_keep_the_button_mode(win: ConverterWindow, width: int) -> None:
    _run_with_logs(win, width)
    compact = win.status_pill.compact
    for state, run_state in (
        (StatusState.PAUSED, RunState.PAUSED),
        (StatusState.RUNNING, RunState.RUNNING),
    ):
        win._run_state = run_state
        win._set_run_status(state)
        assert win.status_pill.compact is compact
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    assert win.status_pill.compact is compact
    win._set_status("Logs saved.")
    win._dismiss_status()
    assert win.status_pill.compact is compact
    win.worker = None


@pytest.mark.parametrize("height", [600, 900])
def test_font_card_is_visually_separated_from_footer(win: ConverterWindow, height: int) -> None:
    win.resize(1200, height)
    win.show()
    for _ in range(3):
        QApplication.processEvents()
    card_bottom = win.files_group.mapTo(win, win.files_group.rect().bottomLeft()).y()
    footer_top = win.footer.mapTo(win, win.footer.rect().topLeft()).y()
    assert footer_top - card_bottom >= 12
    assert win.convert_button.isVisible()


def test_footer_elides_text_without_losing_tooltip(win: ConverterWindow) -> None:
    win.setMinimumSize(MIN_SIZE)
    win.resize(MIN_SIZE)
    win.show()
    text = "Long font selection and output path " * 20
    win.summary.setText(text)
    win._set_status(text)
    for _ in range(3):
        QApplication.processEvents()
    for label in (win.summary, win.status_pill.label):
        assert label.text() == label.tooltip_text() == text
        assert label.toolTip() == ""
        assert label.display_text().endswith("…")
        assert label.fontMetrics().horizontalAdvance(label.display_text()) <= label.width()
    win.resize(1200, MIN_SIZE.height())
    for _ in range(2):
        QApplication.processEvents()
    assert len(win.summary.display_text()) > 1


def test_footer_alignment_at_breakpoint_after_scanning(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait
) -> None:
    win.resize(1055, 600)
    win.show()
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    qtbot_wait(lambda: win.content_scroll.horizontalScrollBar().maximum() == 0)
    _assert_footer_aligned(win)
    assert win.convert_button.isEnabled()
    assert win.files_group.width() >= win.files_group.minimumSizeHint().width()
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    qtbot_wait(lambda: win.content_scroll.horizontalScrollBar().maximum() == 0)
    for _ in range(3):
        QApplication.processEvents()
    for button in (win.view_log_button, win.open_output_button):
        bounds = button.rect().translated(button.mapTo(win, button.rect().topLeft()))
        assert win.rect().contains(bounds)
    _assert_footer_aligned(win)


@pytest.mark.parametrize("variable", [False, True])
def test_footer_alignment_at_breakpoint_with_large_counts(
    win: ConverterWindow, variable: bool
) -> None:
    win.resize(1055, 600)
    if variable:
        path = Path("variable.ttf")
        win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000, variable=True))
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    win.show()
    win._update_body_layout()
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    for _ in range(5):
        QApplication.processEvents()
    assert win.content_scroll.horizontalScrollBar().maximum() == 0
    _assert_footer_aligned(win)


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_convert_shortcut_respects_enabled_state(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait, key: Qt.Key
) -> None:
    win.show()
    win.activateWindow()
    win.convert_button.clicked.disconnect()
    clicks: list[bool] = []
    win.convert_button.clicked.connect(lambda: clicks.append(True))
    QApplication.processEvents()
    QTest.keyClick(win.font_filter, key, Qt.KeyboardModifier.ControlModifier)
    assert not clicks
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    assert win.convert_button.isEnabled() and win.convert_button.isDefault()
    win.font_filter.setFocus()
    QTest.keyClick(win.font_filter, key, Qt.KeyboardModifier.ControlModifier)
    assert len(clicks) == 1
    win._set_visible_checks(False)
    assert not win.convert_button.isEnabled()
    QTest.keyClick(win.font_filter, key, Qt.KeyboardModifier.ControlModifier)
    assert len(clicks) == 1


@pytest.mark.parametrize("conversion", ["ttf2otf", "ft2wf", "var2static"])
def test_actions_stay_visible_while_content_scrolls(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait, conversion: str
) -> None:
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData(conversion))
    win.resize(1200, 600)
    win.show()
    QApplication.processEvents()
    QApplication.processEvents()
    scrollbar = win.sidebar_scroll.verticalScrollBar()
    assert scrollbar.maximum() > 0

    def button_position() -> tuple[int, int]:
        point = win.convert_button.mapTo(win, win.convert_button.rect().topLeft())
        assert win.rect().contains(point)
        assert win.rect().contains(
            win.convert_button.mapTo(win, win.convert_button.rect().bottomRight())
        )
        return point.x(), point.y()

    original = button_position()
    scrollbar.setValue(scrollbar.maximum())
    QApplication.processEvents()
    assert button_position() == original
    win._set_status("Converting…")
    QApplication.processEvents()
    status_panel_position = button_position()
    long_status = "A long conversion status " * 50
    win._set_status(long_status)
    QApplication.processEvents()
    assert button_position()[1] == status_panel_position[1]
    assert status_panel_position == original
    assert win.status_pill.label.tooltip_text() == long_status
    assert win.content_scroll.viewport().height() > 0


def test_font_area_shrinks_when_window_height_is_reduced(
    win: ConverterWindow, tmp_path: Path
) -> None:
    path = tmp_path / "font.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    win.resize(1200, 1000)
    win.show()
    QApplication.processEvents()
    large_height = win.files_stack.height()
    win.resize(1200, 760)
    QApplication.processEvents()
    assert 150 <= win.files_stack.height() < large_height


def test_desktop_layout_gives_font_table_more_height(win: ConverterWindow, tmp_path: Path) -> None:
    win.resize(1156, 984)
    path = tmp_path / "font.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.show()
    for _ in range(3):
        QApplication.processEvents()
    assert win.body_layout.direction() == window_module.QBoxLayout.Direction.LeftToRight
    assert win.files_stack.height() >= 500
    assert win.files_group.mapTo(win, win.files_group.rect().topLeft()).x() < (
        win.conversion_group.mapTo(win, win.conversion_group.rect().topLeft()).x()
    )
    win.resize(MIN_SIZE)
    QApplication.processEvents()
    assert win.body_layout.direction() == window_module.QBoxLayout.Direction.TopToBottom
    assert win.content_scroll.horizontalScrollBar().maximum() == 0
    win.resize(1156, 984)
    QApplication.processEvents()
    assert win.body_layout.direction() == window_module.QBoxLayout.Direction.LeftToRight


@pytest.mark.parametrize("conversion", ["ttf2otf", "otf2ttf", "ft2wf", "var2static", "woff2ft"])
def test_sidebar_fits_controls_without_expanding_on_wide_windows(
    win: ConverterWindow, tmp_path: Path, conversion: str
) -> None:
    win.resize(1400, 1000)
    win.conversion.setCurrentIndex(win.conversion.findData(conversion))
    path = tmp_path / "font.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    win.show()
    QApplication.processEvents()
    width = win.sidebar_scroll.width()
    table_width = win.files_stack.width()
    assert win.sidebar_scroll.horizontalScrollBar().maximum() == 0
    assert win.conversion.combo.width() >= win.conversion.combo.minimumSizeHint().width()
    assert win.conversion_group.height() == win.conversion_group.sizeHint().height()
    assert win.destination_group.height() == win.destination_group.sizeHint().height()
    win.resize(2000, 1000)
    QApplication.processEvents()
    assert win.sidebar_scroll.width() == width
    assert win.files_stack.width() > table_width


def test_sidebar_resizes_for_scan_counts_and_contracts_when_cleared(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait
) -> None:
    win.resize(1600, 1000)
    win.show()
    QApplication.processEvents()
    initial_width = win.sidebar_scroll.width()
    _scan(win, [fonts], qtbot_wait)
    QApplication.processEvents()
    assert win.sidebar_scroll.width() >= initial_width
    assert win.conversion.combo.width() >= win.conversion.combo.minimumSizeHint().width()
    win._clear_files()
    QApplication.processEvents()
    assert win.sidebar_scroll.width() == initial_width


def test_switching_profiles_preserves_column_widths(win: ConverterWindow) -> None:
    win.resize(1800, 1000)
    win.show()
    QApplication.processEvents()
    QApplication.processEvents()
    sidebar_width = win.sidebar_scroll.width()
    input_width = win.files_group.width()
    win.profile_options.tolerance.setValue(2.5)
    for conversion in window_module.CONVERSIONS:
        win.conversion.setCurrentIndex(win.conversion.findData(conversion))
        QApplication.processEvents()
        assert win.sidebar_scroll.width() == sidebar_width
        assert win.files_group.width() == input_width
        assert win.sidebar_scroll.horizontalScrollBar().maximum() == 0
    # Uncustomized profiles fall back to the defaults: after the full tour,
    # the last profile shows the factory tolerance, not the carried-over value.
    assert win.profile_options.tolerance.value() == 1.0


def test_profile_switch_keeps_width_when_organization_changes(win: ConverterWindow) -> None:
    win.resize(1800, 1000)
    win.show()
    QApplication.processEvents()
    QApplication.processEvents()
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.organization_levels = (("simplify",),)
    win._update_organization_button()
    win._update_body_layout()
    QApplication.processEvents()
    width = win.sidebar_scroll.width()
    win.conversion.setCurrentIndex(win.conversion.findData("woff2ft"))
    QApplication.processEvents()
    assert win.sidebar_scroll.width() == width
    assert win.sidebar_scroll.horizontalScrollBar().maximum() == 0


def test_organization_preview_tracks_options_and_profile(win: ConverterWindow) -> None:
    win.resize(1400, 900)
    win.show()
    QApplication.processEvents()
    assert win.organization_example.isHidden()
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.organization_levels = (("format", "outline"), ("upm",), ("tolerance", "simplify"))
    win._update_organization_button()
    QApplication.processEvents()
    assert win.organization_button.text() == "Organize output…"
    assert win.organization_preview.plain_path() == (
        "opentype_ps/upm_1000/tolerance_1_simplify_0/font.otf"
    )
    assert (
        win.organization_preview.mapTo(
            win.destination_group, win.organization_preview.rect().topLeft()
        ).y()
        > win.overwrite.mapTo(win.destination_group, win.overwrite.rect().bottomLeft()).y()
    )
    assert win.organization_preview.toolTip() == win.organization_preview.plain_path()
    assert not win.organization_example.isHidden()
    width = win.sidebar_scroll.width()
    win.profile_options.use_target_upm.setChecked(True)
    win.profile_options.target_upm.setValue(2048)
    win.profile_options.tolerance.setValue(2.5)
    win.profile_options.simplify.setValue(2)
    assert win.organization_preview.plain_path() == (
        "opentype_ps/upm_2048/tolerance_2.5_simplify_2/font.otf"
    )
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    QApplication.processEvents()
    # Organization levels are per-profile: ft2wf has the default flat output.
    assert win.organization_levels == ()
    assert win.organization_preview.plain_path() == "font.woff2"
    assert win.organization_example.isHidden()
    win.organization_levels = (("format", "outline"),)
    win._update_organization_button()
    assert win.organization_preview.plain_path() == "woff2_tt/font.woff2"
    win.profile_options.format_woff2.setChecked(False)
    assert win.organization_preview.plain_path() == "woff_tt/font.woff"
    assert win.sidebar_scroll.width() == width
    win.organization_levels = ()
    win._update_organization_button()
    assert win.organization_preview.plain_path() == "font.woff"
    assert win.organization_example.isHidden()
    assert win.organization_button.text() == "Organize output…"


def test_organization_example_collapses_without_profile(win: ConverterWindow) -> None:
    win.resize(1400, 1000)
    win.show()
    QApplication.processEvents()
    assert win.organization_example.isHidden()
    height_without_example = win.destination_group.height()
    win.organization_levels = (("family",),)
    win._update_organization_button()
    assert win.organization_example.isHidden()
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    QApplication.processEvents()
    assert win.organization_example.isHidden()
    assert win.destination_group.height() == height_without_example
    win.organization_levels = (("family",),)
    win._update_organization_button()
    QTest.qWait(50)
    assert not win.organization_example.isHidden()
    assert (
        win.destination_group.height()
        == height_without_example + win.organization_example.height() + 9
    )
    win.organization_levels = ()
    win._update_organization_button()
    QTest.qWait(50)
    assert win.organization_example.isHidden()
    assert win.destination_group.height() == height_without_example


def test_wrapping_example_does_not_move_other_cards(win: ConverterWindow, qtbot_wait: Wait) -> None:
    win.resize(1400, 1000)
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.organization_levels = (("family",),)
    win._update_organization_button()
    win.show()
    # The sidebar width settles after the deferred metrics pass that follows show().
    qtbot_wait(lambda: win._sidebar_metrics_measured)
    QTest.qWait(50)
    position = win.profile_options.mapTo(win, QPoint())
    size = win.profile_options.size()
    sidebar_width = win.sidebar_scroll.width()
    previous_height = win.organization_preview.height()
    win.organization_levels = (
        ("family", "format", "outline"),
        ("upm", "tolerance", "simplify"),
    )
    win._update_organization_button()
    QTest.qWait(50)
    assert win.organization_preview.height() > previous_height
    assert win.profile_options.mapTo(win, QPoint()) == position
    assert win.profile_options.size() == size
    assert win.sidebar_scroll.width() == sidebar_width


def test_organization_dialog_updates_preview_only_when_accepted(
    win: ConverterWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))

    class FakeDialog:
        levels = (("family",),)
        accepted = False

        def __init__(self, *args: object) -> None:
            pass

        def exec(self) -> QDialog.DialogCode:
            return QDialog.DialogCode.Accepted if self.accepted else QDialog.DialogCode.Rejected

        def deleteLater(self) -> None:  # noqa: N802 - Qt name
            pass

    monkeypatch.setattr(window_module, "OrganizationDialog", FakeDialog)
    win._show_organization_dialog()
    assert win.organization_preview.plain_path() == "font.otf"
    FakeDialog.accepted = True
    win._show_organization_dialog()
    assert win.organization_preview.plain_path() == "Sample Family/font.otf"
    assert not win.organization_example.isHidden()


@pytest.mark.parametrize("width", [MIN_WIDTH, 1400])
def test_organization_preview_fits_sidebar(win: ConverterWindow, width: int) -> None:
    win.setMinimumSize(MIN_SIZE)
    win.resize(width, 600)
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.organization_levels = (
        ("family", "format", "outline"),
        ("upm", "tolerance", "simplify"),
    )
    win._update_organization_button()
    win.show()
    QApplication.processEvents()
    preview = win.organization_preview
    bounds = preview.rect().translated(
        preview.mapTo(win.destination_group, preview.rect().topLeft())
    )
    assert win.destination_group.rect().contains(bounds)
    win.sidebar_scroll.ensureWidgetVisible(preview)
    QApplication.processEvents()
    viewport = win.sidebar_scroll.viewport()
    preview_bounds = preview.rect().translated(preview.mapTo(viewport, QPoint()))
    assert viewport.rect().intersects(preview_bounds)
    assert win.sidebar_scroll.horizontalScrollBar().maximum() == 0
    assert preview.height() >= preview.fontMetrics().height()


def test_empty_drop_zone_has_no_buttons(win: ConverterWindow) -> None:
    win.setMinimumSize(MIN_SIZE)
    win.resize(MIN_SIZE)
    win.show()
    for _ in range(3):
        QApplication.processEvents()
    zone = win.drop_zone
    assert zone.isVisible()
    assert not win.files_stack.isVisible()
    assert zone.findChildren(QPushButton) == []
    assert win.add_button.isVisible() and win.add_folder_button.isVisible()
    assert win.files_header.isAncestorOf(win.add_button)


def test_add_actions_stay_in_the_header_when_the_list_fills_and_empties(
    win: ConverterWindow, tmp_path: Path
) -> None:
    win.resize(1200, 900)
    win.show()
    QApplication.processEvents()
    assert win.files_header.isAncestorOf(win.add_button)
    path = tmp_path / "font.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    QApplication.processEvents()
    assert not win.drop_zone.isVisible()
    assert win.files_header.isAncestorOf(win.add_button)
    assert win.files_header.isAncestorOf(win.folder_split)
    win._clear_files()
    QApplication.processEvents()
    assert win.drop_zone.isVisible()
    assert win.files_header.isAncestorOf(win.add_button)
    assert win.files_header.isAncestorOf(win.folder_split)


@pytest.mark.parametrize("conversion", ["ttf2otf", "otf2ttf", "ft2wf", "var2static"])
def test_compact_window_keeps_controls_accessible(win: ConverterWindow, conversion: str) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData(conversion))
    win.resize(MIN_SIZE)
    win.show()
    QApplication.processEvents()
    assert win.width() == MIN_SIZE.width()
    assert win.height() == MIN_SIZE.height()
    for button in (
        win.convert_button,
        win.view_log_button,
        win.open_output_button,
    ):
        if not button.isVisible():
            continue
        assert win.rect().contains(button.mapTo(win, button.rect().bottomRight()))
        assert win.rect().contains(button.mapTo(win, button.rect().topLeft()))
    scroll = win.content_scroll
    assert scroll.verticalScrollBar().maximum() > 0
    assert win.sidebar_scroll.verticalScrollBar().maximum() == 0
    for widget in (win.conversion_group, win.files_group, win.destination_group):
        scroll.ensureWidgetVisible(widget)
        QApplication.processEvents()
        assert (
            scroll.viewport()
            .rect()
            .intersects(
                widget.rect().translated(widget.mapTo(scroll.viewport(), widget.rect().topLeft()))
            )
        )
    scroll.ensureWidgetVisible(win.sidebar_scroll)
    win.sidebar_scroll.ensureWidgetVisible(win.organization_button)
    QApplication.processEvents()
    assert (
        win.sidebar_scroll.viewport()
        .rect()
        .intersects(
            win.organization_button.rect().translated(
                win.organization_button.mapTo(
                    win.sidebar_scroll.viewport(), win.organization_button.rect().topLeft()
                )
            )
        )
    )


def test_check_states_survive_refresh(win: ConverterWindow, fonts: Path, qtbot_wait: Wait) -> None:
    _scan(win, [fonts], qtbot_wait)
    win._set_visible_checks(False)
    win._refresh_folder_contents()
    qtbot_wait(lambda: not win.file_list.scanning, 30.0)
    assert win._selected_input_paths() == []


def test_folder_recursion_is_per_source(
    win: ConverterWindow, fonts: Path, tmp_path: Path, qtbot_wait: Wait
) -> None:
    flat, deep = tmp_path / "flat", tmp_path / "deep"
    for folder in (flat, flat / "sub", deep, deep / "sub"):
        folder.mkdir(parents=True, exist_ok=True)
        shutil.copy(fonts / "a.ttf", folder / "a.ttf")
    win._add_paths([str(flat)])
    qtbot_wait(lambda: not win.file_list.scanning, 30.0)
    assert win.file_list.row_count == 1
    win._add_paths([str(deep)], recursive=True)
    qtbot_wait(lambda: not win.file_list.scanning, 30.0)
    assert win.file_list.row_count == 3
    assert win._sources == [Source(flat.resolve()), Source(deep.resolve(), True)]
    win._add_paths([str(flat)], recursive=True)
    qtbot_wait(lambda: not win.file_list.scanning, 30.0)
    assert win.file_list.row_count == 4
    win._add_paths([str(flat)])
    assert win._sources[0] == Source(flat.resolve(), True)


def test_folder_split_button_requests_recursion(
    win: ConverterWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    requests: list[bool] = []
    win.folder_split.folder_requested.connect(requests.append)
    win.add_folder_button.click()
    win.folder_split.add_folder_action.trigger()
    win.folder_split.add_folder_recursive_action.trigger()
    assert requests == [False, False, True]
    assert win.folder_split.arrow_button.menu() is win.folder_split.menu


def test_instance_mode_skips_static_fonts(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait
) -> None:
    _scan(win, [fonts], qtbot_wait)
    index = win.conversion.findData("var2static")
    win.conversion.setCurrentIndex(index)
    assert win._is_instance_mode()
    assert win.files_stack.currentWidget() is win.instance_tree
    assert not win.font_filter.isHidden()
    assert win.font_filter.placeholderText() == "Filter fonts or instances…"
    assert win.select_all_checkbox.text() == "Select all"
    assert "instances" in win.select_all_checkbox.toolTip()
    assert win.instance_tree.skipped_count() == 2
    assert "No fonts found" not in win.scan_label.text() or win.file_list.row_count == 0
    win._toggle_visible_checks()
    assert win._selected_input_paths() == []
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    assert win.files_stack.currentWidget() is win.files
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))


def test_scan_progress_labels(win: ConverterWindow) -> None:
    win._on_scan_progress(0, 0)
    assert win.scan_label.text() == "Counting fonts…"
    win._on_scan_progress(1, 4)
    assert win.scan_label.text() == "Scanning fonts… 1 / 4"
    win._cancel_scan()
    assert not win._scan_cancelled


def test_scan_stopped_returns_to_rest(win: ConverterWindow) -> None:
    win._on_scan_progress(260, 2028)
    win._scan_cancelled = True
    win._on_scan_finished()
    assert win.scan_progress.isHidden()
    assert win.scan_label.text() == ""
    assert not win.scan_label.wordWrap()
    win._refresh_folder_contents()
    assert win.scan_progress.isHidden()


def test_empty_zone_switches_on_first_font_and_clear(
    win: ConverterWindow, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert win.files_stack.isHidden() and not win.drop_zone.isHidden()
    for control in (win.select_all_checkbox, win.hide_incompatible, win.font_filter):
        assert control.isHidden()
    win.conversion.setCurrentIndex(win.conversion.findData("var2static"))
    assert win.files_stack.isHidden()
    with monkeypatch.context() as patch:
        patch.setattr(type(win.file_list), "scanning", property(lambda _: True))
        win._update_buttons()
        assert win.drop_zone.title.text() == "Scanning…"
        path = tmp_path / "font.ttf"
        win._on_font_found(path, FontInfo(path, "SFNT", "TrueType", 1000))
        assert win.files_stack.currentWidget() is win.instance_tree
        assert not win.files_stack.isHidden() and win.drop_zone.isHidden()
        for control in (win.select_all_checkbox, win.hide_incompatible, win.font_filter):
            assert not control.isHidden()
        win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
        assert win.files_stack.currentWidget() is win.files
    win._clear_files()
    assert win.files_stack.isHidden() and not win.drop_zone.isHidden()
    assert win.drop_zone.title.text() == "Drop fonts or folders here"
    for control in (win.select_all_checkbox, win.hide_incompatible, win.font_filter):
        assert control.isHidden()


def test_drop_zone_scanning_until_first_font(
    win: ConverterWindow,
    fonts: Path,
    monkeypatch: pytest.MonkeyPatch,
    qtbot_wait: Wait,
) -> None:
    proceed_first, proceed_second = threading.Event(), threading.Event()
    original = scanner_module.inspect_font
    calls = 0

    def inspect(path: Path) -> FontInfo | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            proceed_first.wait(10)
        else:
            proceed_second.wait(10)
        return original(path)

    monkeypatch.setattr(scanner_module, "inspect_font", inspect)
    try:
        win._add_paths([str(fonts)])
        assert win.file_list.scanning
        assert win.files_stack.isHidden()
        assert win.drop_zone.title.text() == "Scanning…"
        assert not win.scan_widget.isHidden()
        assert not win.scan_stop_button.isHidden()
        for control in (win.select_all_checkbox, win.hide_incompatible, win.font_filter):
            assert control.isHidden()
        proceed_first.set()
        qtbot_wait(lambda: win.file_list.row_count == 1)
        assert win.file_list.scanning
        assert win.files_stack.currentWidget() is win.files
        for control in (win.select_all_checkbox, win.hide_incompatible, win.font_filter):
            assert not control.isHidden()
    finally:
        proceed_first.set()
        proceed_second.set()
        qtbot_wait(lambda: not win.file_list.scanning)


def test_import_buttons_use_input_dialogs(
    win: ConverterWindow, fonts: Path, monkeypatch: pytest.MonkeyPatch, qtbot_wait: Wait
) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        staticmethod(lambda *a, **k: ([str(fonts / "a.ttf")], "")),
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(fonts))
    )
    win.add_button.click()
    qtbot_wait(lambda: not win.file_list.scanning)
    assert win.file_list.row_count == 1
    win._clear_files()
    win.add_folder_button.click()
    qtbot_wait(lambda: not win.file_list.scanning)
    assert win.file_list.row_count == 2


def test_empty_scan_keeps_list_controls_hidden(
    win: ConverterWindow, tmp_path: Path, qtbot_wait: Wait
) -> None:
    _scan(win, [tmp_path], qtbot_wait)
    assert win.file_list.row_count == 0
    assert win.files_stack.isHidden() and not win.drop_zone.isHidden()
    assert win.scan_label.text() == ""
    for control in (win.select_all_checkbox, win.hide_incompatible, win.font_filter):
        assert control.isHidden()


def test_drop_zone_adds_dropped_files(win: ConverterWindow, fonts: Path, qtbot_wait: Wait) -> None:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(fonts / "a.ttf"))])
    event = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    win.drop_zone.dropEvent(event)
    assert event.isAccepted()
    qtbot_wait(lambda: not win.file_list.scanning)
    assert win.file_list.row_count == 1
    assert win.files_stack.currentWidget() is win.files


def test_destination_modes(
    win: ConverterWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chosen = tmp_path / "out"
    chosen.mkdir()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(chosen))
    )
    win.destination_folder_radio.setChecked(True)
    assert win.output_directory == chosen
    assert win.destination_edit.isEnabled()
    win.destination_source_radio.setChecked(True)
    assert win.output_directory is None
    assert win.destination_edit.text() == ""
    assert win.destination_edit.placeholderText() == ""
    # Dialog cancelled with no previous directory falls back to "same as source".
    win._settings.remove(window_module.OUTPUT_DIR_KEY)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    win.destination_folder_radio.setChecked(True)
    assert win.destination_source_radio.isChecked()


def test_choose_files_and_folder(
    win: ConverterWindow, fonts: Path, monkeypatch: pytest.MonkeyPatch, qtbot_wait: Wait
) -> None:
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        staticmethod(lambda *a, **k: ([str(fonts / "a.ttf")], "")),
    )
    win.add_button.click()
    qtbot_wait(lambda: not win.file_list.scanning, 30.0)
    assert win.file_list.row_count == 1
    assert win._saved_dir(window_module.INPUT_DIR_KEY) == str(fonts)
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(fonts))
    )
    win.add_folder_button.click()
    qtbot_wait(lambda: not win.file_list.scanning, 30.0)
    assert win.file_list.row_count == 2


def test_options_reflect_controls(win: ConverterWindow, tmp_path: Path) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.overwrite.setChecked(False)
    win.organization_levels = (("family", "format"), ("outline", "upm"))
    win.output_directory = tmp_path
    settings = win._options()
    assert settings.overwrite is False
    assert settings.organization_levels == (("family", "format"), ("outline", "upm"))
    assert settings.output_dir == tmp_path


def test_save_logs(win: ConverterWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    win._save_logs()
    assert win.status_pill.property("state") == "warning"
    win._append_log(LogEntry.create("INFO", "x.y", "hello", {}))
    target = tmp_path / "logs.jsonl"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    win._save_logs()
    assert json.loads(target.read_text(encoding="utf-8").splitlines()[0])["event"] == "x.y"
    assert "Logs saved" in win.status_pill.message
    bad = tmp_path / "no" / "dir" / "l.jsonl"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(bad), ""))
    )
    win._save_logs()
    assert win.status_pill.property("state") == "error"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    win._save_logs()


def test_save_options_are_stored_per_profile(win: ConverterWindow) -> None:
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win.recalc_bboxes.setChecked(False)
    win.recalc_timestamp.setChecked(True)
    assert win.store.profile_options("ttf2otf")["recalc_bboxes"] is False
    assert win.store.profile_options("ttf2otf")["recalc_timestamp"] is True

    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    assert win.recalc_bboxes.isChecked()
    assert not win.recalc_timestamp.isChecked()

    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    assert not win.recalc_bboxes.isChecked()
    assert win.recalc_timestamp.isChecked()

    win.profile_options.reset_button.click()
    assert win.recalc_bboxes.isChecked()
    assert not win.recalc_timestamp.isChecked()
    assert win.reorder_tables.isChecked()
    assert win.store.profile_options("ttf2otf") == {}


def test_output_folder_to_open(win: ConverterWindow, tmp_path: Path) -> None:
    assert win._output_folder_to_open() is None
    win._saved_files = [tmp_path / "a" / "x.otf", tmp_path / "b" / "y.otf"]
    assert win._output_folder_to_open() == tmp_path
    win.output_directory = tmp_path / "o"
    assert win._output_folder_to_open() == tmp_path
    win._run_output_directory = tmp_path / "original"
    assert win._output_folder_to_open() == tmp_path / "original"


def test_open_output_folder_failure(
    win: ConverterWindow, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    win._run_output_directory = tmp_path
    monkeypatch.setattr(
        conversion_controller_module.QDesktopServices, "openUrl", staticmethod(lambda url: False)
    )
    win._open_output_folder()
    assert win.status_pill.property("state") == "error"
    monkeypatch.setattr(
        conversion_controller_module.QDesktopServices, "openUrl", staticmethod(lambda url: True)
    )
    win._open_output_folder()


def _center_y(win: ConverterWindow, widget: QWidget) -> int:
    """Vertical center of ``widget`` in window coordinates."""
    return widget.mapTo(win, QPoint(0, widget.height() // 2)).y()


def _ready(win: ConverterWindow, tmp_path: Path) -> None:
    """Load a compatible font and choose a profile, so Convert is enabled."""
    path = tmp_path / "ready.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))


def _finished(win: ConverterWindow, result: ConversionResult) -> None:
    win.converter.outcome = RunOutcome(total=max(win._progress_total, len(result.outcomes)))
    for outcome in result.outcomes:
        win.converter.outcome.record(outcome)
    win._conversion_finished(result)


def test_conversion_finished_success(win: ConverterWindow, tmp_path: Path) -> None:

    result = ConversionResult((_outcome(FontOutcomeKind.CONVERTED),))
    win._session_elapsed = 24.2
    _ready(win, tmp_path)
    _finished(win, result)
    assert win.status_pill.message == "Done — 1 converted · 0:24"
    assert win.status_pill.property("state") == "success"
    assert win.summary_zone.isHidden()
    assert win.status_pill.chip.text() == "Done"
    assert win.status_pill.counts.text() == "1 converted · 24.2 s"
    assert win.log_window.chip.text() == "Done"
    assert win.log_window.chip.property("tone") == "success"
    assert win.log_window.summary.text().startswith("1 converted · 24.2 s · finished ")
    assert win.open_output_button.isEnabled()
    assert win._log_entries[-1].event == "conversion.completed"
    assert win._log_entries[-1].message == "1 converted, 0 skipped, 0 failed"


def test_conversion_finished_counts_nonzero_outcomes(win: ConverterWindow) -> None:
    win._session_elapsed = 1.0
    result = ConversionResult(
        (_outcome(FontOutcomeKind.CONVERTED), _outcome(FontOutcomeKind.SKIPPED))
    )
    _finished(win, result)
    assert win.status_pill.message == "Done — 1 converted · 1 skipped · 0:01"
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.SKIPPED),)))
    assert win.status_pill.message == "Done — 0 converted · 1 skipped · 0:01"
    _finished(win, ConversionResult())
    assert win.status_pill.message == "Done — 0 converted · 0:01"
    win._set_status("Ready")
    assert win.status_pill.property("state") == ""
    # A notice does not change the log window, which still shows the last run.
    assert win.log_window.chip.property("tone") == "success"


def test_conversion_finished_with_failures(win: ConverterWindow, tmp_path: Path) -> None:

    result = ConversionResult(
        (
            _outcome(FontOutcomeKind.CONVERTED),
            _outcome(FontOutcomeKind.FAILED, "ValueError: bad", "b.ttf"),
        )
    )
    _ready(win, tmp_path)
    _finished(win, result)
    assert win.status_pill.property("state") == "error"
    assert win.summary_zone.isHidden()
    assert "b.ttf: ValueError: bad" in win.status_pill.counts.toolTip()
    assert "1 converted · 1 failed" in win.status_pill.message
    assert "0 skipped" not in win.status_pill.message
    assert win._log_entries[-1].event == "conversion.failed"
    assert win.open_output_button.isEnabled()
    _finished(win, ConversionResult(error="Boom: x"))
    assert "Boom: x" in win.status_pill.counts.toolTip()


def test_conversion_finished_cancelled(win: ConverterWindow, tmp_path: Path) -> None:

    result = ConversionResult((_outcome(FontOutcomeKind.CONVERTED),), cancelled=True)
    _ready(win, tmp_path)
    _finished(win, result)
    assert win.status_pill.message.startswith("Cancelled — 1 of 1 converted · ")
    assert "0 skipped" not in win.status_pill.message
    assert win.status_pill.property("state") == "neutral"
    assert win.summary_zone.isHidden()
    assert win.open_output_button.isEnabled()
    assert win._log_entries[-1].event == "conversion.cancelled"
    win._session_elapsed = 1.0
    _finished(win, ConversionResult(cancelled=True))
    assert win.status_pill.message == "Cancelled — 0 of 0 converted · 0:01"


def test_conversion_without_output_disables_output_action(win: ConverterWindow) -> None:
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.SKIPPED),)))
    assert not win.view_log_button.isHidden()
    assert not win.open_output_button.isEnabled()


def test_conversion_without_saved_files_opens_run_input_folder(
    win: ConverterWindow, tmp_path: Path
) -> None:
    win.converter.run_input_directory = tmp_path
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.SKIPPED),)))
    assert win.open_output_button.isEnabled()
    assert win._output_folder_to_open() == tmp_path


def test_conversion_failed(win: ConverterWindow, tmp_path: Path) -> None:

    _ready(win, tmp_path)
    win._conversion_failed("RuntimeError: x")
    assert win.status_pill.message.startswith("Error — conversion stopped")
    assert "RuntimeError: x" in win.status_pill.counts.toolTip()
    assert win.summary_zone.isHidden()
    assert win._log_entries[-1].context["error_type"] == "RuntimeError"


def test_fatal_error_keeps_individual_results_and_output_paths(
    win: ConverterWindow, tmp_path: Path
) -> None:
    _ready(win, tmp_path)
    win.converter.outcome = RunOutcome(total=4)
    saved = tmp_path / "nested" / "converted.otf"
    win.converter.outcome.record(FontOutcome(Path("a.ttf"), FontOutcomeKind.CONVERTED, (saved,)))
    win.converter.outcome.record(FontOutcome(Path("b.ttf"), FontOutcomeKind.SKIPPED))
    win.converter.outcome.record(FontOutcome(Path("c.ttf"), FontOutcomeKind.FAILED))
    win._session_elapsed = 3
    win._conversion_failed("RuntimeError: unexpected")
    outcome = win.converter.outcome
    assert (outcome.total, outcome.converted, outcome.skipped, outcome.failed) == (4, 1, 1, 1)
    assert outcome.saved_files == [saved]
    assert outcome.failed_files == [Path("c.ttf")]
    assert win.status_pill.chip.text() == "Error"
    assert win.status_pill.counts.text() == "Conversion stopped · 1 converted · 1 skipped · 3.0 s"
    assert win.status_pill.message == "Error — conversion stopped · 1 converted · 0:03"
    assert win.status_pill.counts.toolTip() == "RuntimeError: unexpected"
    assert win.open_output_button.isEnabled()
    assert win._output_folder_to_open() == saved.parent


def test_transient_error_restores_last_result(win: ConverterWindow, tmp_path: Path) -> None:
    _ready(win, tmp_path)
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    result = win.status_pill.message
    win._set_status("Could not save logs: denied", "error")
    assert win.status_pill.state is StatusState.NOTICE
    assert win.status_pill.result_buttons.isHidden()
    assert win.status_pill.message == "Could not save logs: denied"
    win.status_pill.close_button.click()
    assert win.status_pill.state is StatusState.DONE
    assert win.status_pill.message == result
    win.status_pill.close_button.click()
    assert win.status_pill.isHidden()
    assert not win.summary_zone.isHidden()


def test_final_actions_do_not_depend_on_log_window(win: ConverterWindow, tmp_path: Path) -> None:
    _ready(win, tmp_path)
    win.show()
    win._show_log_window()
    QApplication.processEvents()
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),)))
    assert not win.status_pill.result_buttons.isHidden()
    assert not win.open_output_button.isHidden()
    win.log_window.close()
    QApplication.processEvents()
    assert not win.status_pill.result_buttons.isHidden()
    assert win.status_pill.close_button.isHidden()


def test_worker_fatal_after_partial_success_preserves_outcome(
    win: ConverterWindow,
    fonts: Path,
    tmp_path: Path,
    qtbot_wait: Wait,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = tmp_path / "nested" / "converted.otf"

    class Service:
        def convert(self, request: Any, **kwargs: Any) -> None:
            kwargs["on_outcome"](
                FontOutcome(request.input_paths[0], FontOutcomeKind.CONVERTED, (saved,))
            )
            kwargs["on_progress"](type("Progress", (), {"done": 1, "total": 2})())
            kwargs["on_outcome"](FontOutcome(request.input_paths[0], FontOutcomeKind.SKIPPED))
            raise RuntimeError("after saved file")

    monkeypatch.setattr(worker_module, "ConverterService", Service)
    monkeypatch.setattr(win, "_confirm_modify_rights", lambda: True)
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    win._start_conversion()
    qtbot_wait(lambda: win.worker is None, 30)
    assert win.converter.outcome.converted == 1
    assert win.converter.outcome.skipped == 1
    assert win.converter.outcome.saved_files == [saved]
    assert win.status_pill.state is StatusState.FATAL
    assert "1 converted" in win.status_pill.message
    assert "after saved file" in win.status_pill.counts.toolTip()
    assert not win.status_pill.result_buttons.isHidden()
    assert not win.log_window.isVisible()  # the run never opens the log by itself
    assert win.primary_slot.currentWidget() is win.convert_button
    assert win.files_group.isEnabled()


def test_partial_and_complete_failures_use_distinct_states(win: ConverterWindow) -> None:
    failure = _outcome(FontOutcomeKind.FAILED, "invalid")
    _finished(win, ConversionResult((failure,)))
    assert win.status_pill.state is StatusState.FAILED
    assert win.status_pill.message.startswith("Failed — 0 of 1 converted")
    _finished(win, ConversionResult((failure, _outcome(FontOutcomeKind.SKIPPED))))
    assert win.status_pill.state is StatusState.ERRORS
    assert win.status_pill.message.startswith("Done with errors — 0 converted · 1 failed")


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (StatusState.RUNNING, "Converting — 2 of 4 · 1:05"),
        (StatusState.PAUSED, "Paused — 2 of 4 · 1:05"),
        (StatusState.CANCELLED, "Cancelled — 2 of 4 converted · 1:05"),
        (StatusState.DONE, "Done — 2 converted · 1 skipped · 1:05"),
        (StatusState.ERRORS, "Done with errors — 2 converted · 1 failed · 1 skipped · 1:05"),
        (StatusState.FAILED, "Failed — 2 of 4 converted · 1:05"),
        (StatusState.FATAL, "Error — conversion stopped · 2 converted · 1:05"),
    ],
)
def test_status_message_format(state: StatusState, expected: str) -> None:
    assert format_message(state, done=2, total=4, elapsed=65, skipped=1, failed=1) == expected
    assert format_elapsed(3600) == "1:00:00"


def _fake_worker(win: ConverterWindow) -> ConversionWorker:
    worker = ConversionWorker(ConversionRequest((Path("a.ttf"),), ConversionOptions()))
    win.worker = worker
    return worker


def test_pause_resume_state_machine(win: ConverterWindow) -> None:
    worker = _fake_worker(win)
    win._run_state = RunState.RUNNING
    win._toggle_pause()
    assert win._run_state is RunState.PAUSING
    assert not worker._running.is_set()
    win._on_paused_changed(True)
    assert win._run_state is RunState.PAUSED
    assert win.pause_button.text() == "Resume"
    assert win.status_pill.message.startswith("Paused")
    win._toggle_pause()
    assert worker._running.is_set()
    win._on_paused_changed(False)
    assert win._run_state is RunState.RUNNING
    assert win._log_entries[-1].event == "conversion.resumed"
    win._elapsed_timer.stop()
    win.worker = None
    win._on_paused_changed(True)


def _converting(win: ConverterWindow, tmp_path: Path) -> ConversionWorker:
    """A run in progress on a (not started) worker, converting font 2 of 4."""
    worker = _fake_worker(win)
    win._run_state = RunState.RUNNING
    win.converter.outcome.total = 4
    win.converter.progress_done = 1
    win.converter.current_input = tmp_path / "big" / "font.ttf"
    win.converter.session_started_at = 0.0
    win._elapsed_timer.start()
    win._set_run_status(StatusState.RUNNING)
    win._update_buttons()
    return worker


def test_pause_request_says_the_current_font_finishes_first(
    win: ConverterWindow, tmp_path: Path
) -> None:
    _converting(win, tmp_path)
    pill = win.status_pill
    current = str(tmp_path / "big" / "font.ttf")
    assert pill.run_title.text() == "Converting…"
    assert pill.run_file.text() == current
    assert pill.run_file.toolTip() == ""
    win.pause_button.click()
    assert win._run_state is RunState.PAUSING
    assert pill.run_title.text() == "Pausing…"
    assert pill.run_file.text() == "Pauses when the current font is done."
    assert pill.run_file.elide_mode is Qt.TextElideMode.ElideRight
    assert pill.run_file.toolTip() == current
    assert pill.accessibleDescription() == (
        "Pausing… · 1 / 4 · Pauses when the current font is done."
    )
    assert win._log_entries[-1].event == "conversion.pause_requested"
    assert win._log_entries[-1].message == "Pause requested: the current font finishes first"
    assert win.log.item(win.log.count() - 1).text() == win._log_entries[-1].display_text()
    # Buttons keep their labels; Pause waits, Cancel stays available.
    assert win.pause_button.text() == "Pause" and not win.pause_button.isEnabled()
    assert win.cancel_button.text() == "Cancel" and win.cancel_button.isEnabled()
    # Progress and timer refreshes keep rendering, and keep "Pausing…".
    win._on_conversion_progress(2, 4)
    assert pill.run_counter.text() == "2 / 4"
    assert win.progress.value() == 2
    win._refresh_progress_status()
    assert pill.run_title.text() == "Pausing…"
    assert win._elapsed_timer.isActive()
    win._on_paused_changed(True)
    assert pill.run_title.text() == "Paused"
    assert pill.run_file.text() == "The next font starts when you resume."
    assert pill.run_file.toolTip() == ""
    assert pill.accessibleDescription().startswith("Paused · 2 / 4")
    win._elapsed_timer.stop()
    win.worker = None


def test_cancel_request_says_the_current_font_finishes_first(
    win: ConverterWindow, tmp_path: Path
) -> None:
    worker = _converting(win, tmp_path)
    pill = win.status_pill
    win.cancel_button.click()
    assert win._cancelling and worker._running.is_set()
    assert pill.run_title.text() == "Cancelling…"
    assert pill.run_file.text() == "Stops when the current font is done."
    assert pill.run_file.toolTip() == str(tmp_path / "big" / "font.ttf")
    assert pill.accessibleDescription() == (
        "Cancelling… · 1 / 4 · Stops when the current font is done."
    )
    assert win._log_entries[-1].event == "conversion.cancel_requested"
    assert win._log_entries[-1].message == "Cancel requested: the current font finishes first"
    entries = len(win._log_entries)
    win._request_cancel()
    assert len(win._log_entries) == entries
    win._on_conversion_progress(2, 4)
    assert pill.run_title.text() == "Cancelling…"
    assert pill.run_counter.text() == "2 / 4"
    assert win.cancel_button.text() == "Cancel" and not win.cancel_button.isEnabled()
    assert not win.pause_button.isEnabled()
    win._elapsed_timer.stop()
    win.worker = None


def test_cancel_while_pausing_wins_over_pausing(win: ConverterWindow, tmp_path: Path) -> None:
    _converting(win, tmp_path)
    win.pause_button.click()
    win._request_cancel()
    assert win.status_pill.run_title.text() == "Cancelling…"
    # The pause no longer happens once the run is cancelling.
    win._on_paused_changed(True)
    assert win._run_state is RunState.PAUSING
    assert win.status_pill.run_title.text() == "Cancelling…"
    win._elapsed_timer.stop()
    win.worker = None


def test_cancel_from_paused_logs_no_request(win: ConverterWindow, tmp_path: Path) -> None:
    worker = _converting(win, tmp_path)
    win._toggle_pause()
    win._on_paused_changed(True)
    entries = len(win._log_entries)
    win._request_cancel()
    assert worker._running.is_set()
    assert len(win._log_entries) == entries
    assert win.status_pill.run_title.text() == "Paused"
    # The worker resumes to stop: the footer renders the cancel at once.
    win._on_paused_changed(False)
    assert win._run_state is RunState.RUNNING
    assert win.status_pill.run_title.text() == "Cancelling…"
    assert not any(entry.event == "conversion.resumed" for entry in win._log_entries)
    win._elapsed_timer.stop()
    win.worker = None


def _chip(win: ConverterWindow) -> tuple[str, str, str]:
    chip = win.log_window.chip
    return chip.text(), chip.icon_name, chip.property("tone")


@pytest.mark.parametrize(
    ("state", "pausing", "cancelling", "expected"),
    [
        (StatusState.RUNNING, False, False, ("Running", "sync_alt")),
        (StatusState.RUNNING, True, False, ("Pausing…", "pause")),
        (StatusState.RUNNING, False, True, ("Cancelling…", "close")),
        (StatusState.RUNNING, True, True, ("Cancelling…", "close")),
        (StatusState.PAUSED, True, True, ("Paused", "pause")),
        (StatusState.CANCELLED, False, True, ("Cancelled", "close")),
        (StatusState.DONE, True, True, ("Done", "check")),
    ],
)
def test_chip_content_follows_the_run_phase(
    state: StatusState, pausing: bool, cancelling: bool, expected: tuple[str, str]
) -> None:
    assert chip_content(state, pausing=pausing, cancelling=cancelling) == expected


def test_log_window_chip_follows_pausing(win: ConverterWindow, tmp_path: Path) -> None:
    _converting(win, tmp_path)
    assert _chip(win) == ("Running", "sync_alt", "running")
    win.pause_button.click()
    assert _chip(win) == ("Pausing…", "pause", "running")
    assert win.log_window.chip.text() == win.status_pill.run_title.text()
    # While the current font finishes, refreshes keep the chip and the live summary.
    win._on_conversion_progress(2, 4)
    assert _chip(win) == ("Pausing…", "pause", "running")
    assert win.log_window.summary.text().startswith("2 / 4 · ")
    win._on_paused_changed(True)
    assert _chip(win) == ("Paused", "pause", "warning")
    win._elapsed_timer.stop()
    win.worker = None


def test_log_window_chip_follows_cancelling(win: ConverterWindow, tmp_path: Path) -> None:
    _converting(win, tmp_path)
    win.cancel_button.click()
    assert _chip(win) == ("Cancelling…", "close", "running")
    assert win.log_window.chip.text() == win.status_pill.run_title.text()
    win._on_conversion_progress(2, 4)
    assert _chip(win) == ("Cancelling…", "close", "running")
    _finished(win, ConversionResult((_outcome(FontOutcomeKind.CONVERTED),), cancelled=True))
    assert _chip(win) == ("Cancelled", "close", "neutral")
    win.worker = None


def test_log_window_chip_cancel_while_paused(win: ConverterWindow, tmp_path: Path) -> None:
    _converting(win, tmp_path)
    win._toggle_pause()
    win._on_paused_changed(True)
    assert _chip(win) == ("Paused", "pause", "warning")
    win._request_cancel()
    assert _chip(win) == ("Paused", "pause", "warning")
    win._on_paused_changed(False)  # resumes only to stop
    assert _chip(win) == ("Cancelling…", "close", "running")
    _finished(win, ConversionResult(cancelled=True))
    assert _chip(win) == ("Cancelled", "close", "neutral")
    win.worker = None


def test_cancel_conversion_without_confirmation(win: ConverterWindow) -> None:
    worker = _fake_worker(win)
    win._cancel_conversion()
    assert win._cancelling
    assert not win.cancel_button.isEnabled()
    win._toggle_pause()
    assert win._run_state is RunState.IDLE
    assert worker._running.is_set()


def test_start_conversion_missing_input(
    win: ConverterWindow, fonts: Path, qtbot_wait: Wait, monkeypatch: pytest.MonkeyPatch
) -> None:
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(a[1])))
    for path in fonts.iterdir():
        path.unlink()
    win._start_conversion()
    assert shown == ["Input unavailable"]
    assert win.worker is None


def test_full_conversion_end_to_end(
    win: ConverterWindow,
    fonts: Path,
    tmp_path: Path,
    qtbot_wait: Wait,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _scan(win, [fonts], qtbot_wait)
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(out)))
    win.destination_folder_radio.setChecked(True)
    monkeypatch.setattr(win, "_confirm_modify_rights", lambda: True)
    win.show()
    win._start_conversion()
    assert win.primary_slot.currentWidget() is win.run_controls
    assert win.focusWidget() is win.pause_button
    assert not win.files_group.isEnabled()
    assert not win.log_window.isVisible()
    assert win.log_window.title.text() == "Last run · TTF → OTF"
    qtbot_wait(lambda: win.worker is None, 60.0)
    assert win.primary_slot.currentWidget() is win.convert_button
    assert win.files_group.isEnabled()
    assert win.convert_button.isEnabled()
    assert win.status_pill.message.startswith("Done")
    assert any(out.rglob("*.otf"))
    assert win.view_log_button.isEnabled()
    assert not win.view_log_button.isHidden()
    assert not win.open_output_button.isHidden()
    win.destination_source_radio.setChecked(True)
    assert win._output_folder_to_open() == out
    win.output_directory = tmp_path / "different"
    assert win._output_folder_to_open() == out
    assert win.save_logs_button.isEnabled()
    assert win.progress.value() == win.progress.maximum()


def test_close_event_idle_accepts(win: ConverterWindow) -> None:
    event = QCloseEvent()
    win.closeEvent(event)
    assert event.isAccepted()


class _RunningWorker:
    def __init__(self) -> None:
        self.cancelled = False
        self.resumed = False
        self.terminated = False

    def isRunning(self) -> bool:
        return True

    def cancel(self) -> None:
        self.cancelled = True

    def resume(self) -> None:
        self.resumed = True

    def pause(self) -> None:
        pass

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, *_args: object) -> bool:
        return True


def test_close_event_while_running(win: ConverterWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    win.worker = _RunningWorker()  # type: ignore[assignment]
    win._run_state = RunState.RUNNING
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
    )
    event = QCloseEvent()
    win.closeEvent(event)
    assert not event.isAccepted()
    assert not win._close_when_finished
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )
    win.closeEvent(event)
    assert win._close_when_finished
    win._cancelling = True
    event = QCloseEvent()
    win.closeEvent(event)
    assert not event.isAccepted()
    win.worker = None
    win._close_when_finished = False


def test_close_event_offers_force_close_for_a_stuck_worker(
    win: ConverterWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = _RunningWorker()
    win.worker = worker  # type: ignore[assignment]
    win._run_state = RunState.RUNNING
    answers = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: next(answers)))
    event = QCloseEvent()
    win.closeEvent(event)
    assert event.isAccepted()
    assert worker.terminated

    worker2 = _RunningWorker()
    win.worker = worker2  # type: ignore[assignment]
    win._run_state = RunState.RUNNING
    answers = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.No])
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: next(answers)))
    event2 = QCloseEvent()
    win.closeEvent(event2)
    assert not event2.isAccepted()
    assert not worker2.terminated
    win.worker = None


@pytest.mark.parametrize("button", ["Resume", "Cancel conversion", "Keep window open"])
def test_close_event_while_paused(
    win: ConverterWindow, monkeypatch: pytest.MonkeyPatch, button: str
) -> None:
    worker = _RunningWorker()
    win.worker = worker  # type: ignore[assignment]
    win._run_state = RunState.PAUSED

    boxes: list[QMessageBox] = []

    def fake_exec(box: QMessageBox) -> int:
        boxes.append(box)
        target = next(b for b in box.buttons() if b.text() == button)
        monkeypatch.setattr(box, "clickedButton", lambda: target)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    event = QCloseEvent()
    win.closeEvent(event)
    assert not event.isAccepted()
    assert worker.resumed == (button == "Resume")
    assert worker.cancelled == (button == "Cancel conversion")
    _flush_deletions()
    assert not isValid(boxes[0])  # the question box does not outlive its answer
    win.worker = None
    win._cancelling = False
    win._close_when_finished = False


def test_worker_stopped_closes_when_requested(win: ConverterWindow) -> None:
    win._close_when_finished = True
    win._worker_stopped()
    assert not win.isVisible()
    assert win._run_state is RunState.IDLE


def test_convert_reason_messages(win: ConverterWindow, tmp_path: Path) -> None:
    assert win.summary.text() == "Add fonts to start converting"
    win.conversion.setCurrentIndex(win.conversion.findData("ttf2otf"))
    assert win.summary.text() == "Add fonts to start converting"
    assert not win.convert_button.isEnabled()
    path = tmp_path / "font.otf"
    win._on_font_found(path, FontInfo(path, "OTF", "PostScript", 1000))
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    win.conversion.setCurrentIndex(win.conversion.findData("otf2ttf"))
    assert win.convert_button.isEnabled()
    assert win.convert_button.text() == "Convert 1 font"
    assert win._step_badges[0].property("state") == "valid"
    assert win._step_badges[1].property("state") == "valid"


def test_overwrite_panel_tracks_checkbox(win: ConverterWindow) -> None:
    assert not win.overwrite_panel.property("active")
    assert win._step_badges[3].property("state") == ""
    win.overwrite.setChecked(True)
    assert win.overwrite_panel.property("active")
    assert win._step_badges[3].property("state") == ""


def test_overwrite_card_text_follows_the_checkbox(win: ConverterWindow) -> None:
    win.show()
    QApplication.processEvents()
    hint = win.overwrite_panel.findChild(QLabel, "overwriteHint")
    assert hint is not None

    def colors() -> tuple[str, str]:
        QApplication.processEvents()
        return (
            win.overwrite.palette().color(win.overwrite.foregroundRole()).name(),
            hint.palette().color(hint.foregroundRole()).name(),
        )

    assert colors() == (LIGHT.text, LIGHT.text_muted)
    win.overwrite.setChecked(True)
    assert colors() == (LIGHT.warning, LIGHT.warn_fg)
    image = win.overwrite_panel.grab().toImage()
    assert image.pixelColor(image.width() - 6, image.height() // 2).name() == LIGHT.warn_panel_bg
    win.overwrite.setChecked(False)
    assert colors() == (LIGHT.text, LIGHT.text_muted)


def test_drop_zone_is_hidden_once_the_list_has_fonts(win: ConverterWindow, tmp_path: Path) -> None:
    win.resize(1200, 880)
    win.show()
    QApplication.processEvents()
    assert win.drop_zone.isVisible()
    path = tmp_path / "font.ttf"
    win._on_font_found(path, FontInfo(path, "TTF", "TrueType", 1000))
    QApplication.processEvents()
    assert not win.drop_zone.isVisible()
    assert win.files_stack.isVisible()
    win._clear_files()
    QApplication.processEvents()
    assert win.drop_zone.isVisible()
