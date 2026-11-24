from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QCloseEvent, QColor, QFont, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from fontvertx.gui.conversion_dialog import ConversionDialog
from fontvertx.gui.logs import LogEntry
from fontvertx.gui.status_pill import StatusState
from fontvertx.gui.styles import LIGHT, mono_family, stylesheet


@pytest.fixture
def dialog(qapp: QApplication) -> Iterator[ConversionDialog]:
    parent = QWidget()
    dlg = ConversionDialog(parent)
    yield dlg
    dlg.deleteLater()
    parent.deleteLater()


def test_initial_state_is_idle(dialog: ConversionDialog) -> None:
    assert dialog.isModal()
    assert dialog.windowTitle() == "Conversion"
    assert dialog.pause_button.isHidden()
    assert dialog.cancel_button.isHidden()
    assert not dialog.close_button.isHidden()
    assert not dialog.save_logs_button.isEnabled()
    assert not dialog.open_output_button.isEnabled()
    assert dialog.log.isHidden()
    assert not dialog.status.property("mono")
    assert dialog.log.font().family() == mono_family()
    assert dialog.log.font().styleHint() == QFont.StyleHint.Monospace


def test_set_running_toggles_buttons(dialog: ConversionDialog) -> None:
    dialog.set_running(True)
    assert not dialog.pause_button.isHidden()
    assert not dialog.cancel_button.isHidden()
    assert dialog.close_button.isHidden()
    dialog.set_running(False)
    assert dialog.pause_button.isHidden()
    assert not dialog.close_button.isHidden()


def test_set_status_updates_text_property_and_tooltip(dialog: ConversionDialog) -> None:
    dialog.set_status("boom", "error")
    assert dialog.status.text() == "boom"
    assert dialog.status.toolTip() == "boom"
    assert dialog.status.property("state") == "error"
    dialog.set_status("ok", "done")
    assert dialog.status.toolTip() == ""
    assert dialog.status.property("state") == "done"


def test_logs_toggle_shows_and_hides_log(dialog: ConversionDialog) -> None:
    dialog.logs_toggle.setChecked(True)
    assert not dialog.log.isHidden()
    assert dialog.logs_toggle.text() == "Hide logs"
    dialog.logs_toggle.setChecked(False)
    assert dialog.log.isHidden()
    assert dialog.logs_toggle.text() == "Show logs"


def test_close_event_ignored_while_running(dialog: ConversionDialog) -> None:
    dialog.set_running(True)
    event = QCloseEvent()
    dialog.closeEvent(event)
    assert not event.isAccepted()
    dialog.set_running(False)
    event = QCloseEvent()
    dialog.closeEvent(event)
    assert event.isAccepted()


def _escape() -> QKeyEvent:
    return QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)


def test_escape_ignored_while_running(dialog: ConversionDialog) -> None:
    dialog.set_running(True)
    event = _escape()
    dialog.keyPressEvent(event)
    assert not event.isAccepted()


def test_escape_rejects_when_idle(dialog: ConversionDialog) -> None:
    dialog.show()
    dialog.keyPressEvent(_escape())
    assert not dialog.isVisible()


def test_close_button_accepts(dialog: ConversionDialog) -> None:
    dialog.show()
    dialog.close_button.click()
    assert not dialog.isVisible()
    assert dialog.result() == ConversionDialog.DialogCode.Accepted


@pytest.mark.parametrize(
    ("state", "track", "fill", "fraction"),
    [
        (StatusState.RUNNING, LIGHT.progress_track, LIGHT.primary, 0.25),
        (StatusState.PAUSED, LIGHT.warn_fill, LIGHT.warn_accent, 0.25),
        (StatusState.CANCELLED, LIGHT.border, LIGHT.control_border_strong, 0.25),
        (StatusState.DONE, LIGHT.success_border, LIGHT.success_icon, 1),
        (StatusState.WARNING, LIGHT.warn_bg, LIGHT.warn_border, 1),
        (StatusState.ERRORS, LIGHT.danger_bg, LIGHT.danger, 1),
        (StatusState.FAILED, LIGHT.danger_bg, LIGHT.danger, 0.25),
        (StatusState.FATAL, LIGHT.danger_bg, LIGHT.danger, 0.25),
    ],
)
def test_progress_colors_and_geometry(
    dialog: ConversionDialog, state: StatusState, track: str, fill: str, fraction: float
) -> None:
    dialog.setStyleSheet(stylesheet())
    dialog.set_running(True)
    dialog.set_run_status(state, "status", converted=1, total=4)
    dialog.show()
    QApplication.processEvents()
    assert dialog.progress.height() == 8
    assert dialog.progress.fraction == fraction
    image = dialog.progress.grab().toImage()
    assert image.pixelColor(image.width() // 8, 4).name() == fill
    if fraction < 1:
        assert image.pixelColor(image.width() * 3 // 4, 4).name() == track
        end = round(image.width() * fraction) - 1
        assert image.pixelColor(end, 0).name() != fill
    assert image.pixelColor(0, 0) != QColor(fill)


def test_dialog_geometry_remains_stable(dialog: ConversionDialog) -> None:
    dialog.setStyleSheet(stylesheet())
    dialog.set_running(True)
    dialog.show()
    QApplication.processEvents()
    positions = [
        button.mapTo(dialog, QPoint()) for button in (dialog.logs_toggle, dialog.save_logs_button)
    ]
    height = dialog.height()
    margins = dialog.layout().contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (16, 16, 16, 16)
    assert dialog.status.parentWidget().y() == 16
    assert dialog.height() - (dialog.logs_toggle.y() + dialog.logs_toggle.height()) == 16
    assert (
        dialog.cancel_button.mapTo(dialog, QPoint()).x()
        - (dialog.pause_button.mapTo(dialog, QPoint()).x() + dialog.pause_button.width())
        == 16
    )
    for state in StatusState:
        if state is StatusState.NOTICE:
            continue
        dialog.set_run_status(state, "message", converted=1, total=4)
        dialog.set_running(state in (StatusState.RUNNING, StatusState.PAUSED))
        QApplication.processEvents()
        assert dialog.height() == height
        assert [
            button.mapTo(dialog, QPoint())
            for button in (dialog.logs_toggle, dialog.save_logs_button)
        ] == positions
        assert dialog.file_line.height() == 16
        if state not in (StatusState.RUNNING, StatusState.PAUSED):
            assert dialog._buttons.indexOf(dialog.pause_button) == -1
            assert dialog._buttons.indexOf(dialog.cancel_button) == -1
            assert (
                dialog.close_button.x()
                - (dialog.open_output_button.x() + dialog.open_output_button.width())
                == 8
            )
            assert dialog.close_button.geometry().right() == dialog.width() - 17


def test_failed_files_and_empty_live_file_line(dialog: ConversionDialog) -> None:
    files = [Path("one.ttf"), Path("two.ttf"), Path("three.ttf")]
    dialog.set_run_status(StatusState.RUNNING, "running", failed_files=files)
    assert dialog.file_line.text() == ""
    dialog.set_run_status(StatusState.PAUSED, "paused", failed_files=files)
    assert dialog.file_line.text() == ""
    dialog.set_run_status(StatusState.ERRORS, "errors", failed_files=files)
    assert dialog.file_line.text() == "Failed: one.ttf and 2 more"
    dialog.set_run_status(StatusState.FAILED, "failed", failed_files=files[:1])
    assert dialog.file_line.text() == "Failed: one.ttf"
    dialog.set_run_status(StatusState.DONE, "done", failed_files=files)
    assert dialog.file_line.text() == ""
    dialog.show()
    QApplication.processEvents()
    width = dialog.width()
    dialog.set_run_status(StatusState.ERRORS, "errors", failed_files=[Path("A" * 300 + ".ttf")])
    QApplication.processEvents()
    assert dialog.width() == width


def test_open_and_mouse_focus_vs_keyboard(dialog: ConversionDialog) -> None:
    dialog.setStyleSheet(stylesheet())
    dialog.set_running(True)
    dialog.show()
    dialog.activateWindow()
    QApplication.processEvents()
    assert dialog.focusWidget() is dialog
    assert not dialog.logs_toggle.property("keyboardFocus")
    QTest.mouseClick(dialog.logs_toggle, Qt.MouseButton.LeftButton)
    assert not dialog.logs_toggle.property("keyboardFocus")
    dialog.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.keyClick(dialog, Qt.Key.Key_Tab)
    assert dialog.focusWidget() is dialog.logs_toggle
    assert dialog.logs_toggle.property("keyboardFocus")
    before = dialog.logs_toggle.isChecked()
    QTest.keyClick(dialog.logs_toggle, Qt.Key.Key_Return)
    assert dialog.logs_toggle.isChecked() != before
    dialog.setFocus(Qt.FocusReason.OtherFocusReason)
    before = dialog.logs_toggle.isChecked()
    QTest.keyClick(dialog, Qt.Key.Key_Return)
    assert dialog.logs_toggle.isChecked() == before
    assert dialog.isVisible()


def test_tab_order_matches_button_layout(dialog: ConversionDialog) -> None:
    dialog.set_running(True)
    dialog.save_logs_button.setEnabled(True)
    dialog.open_output_button.setEnabled(True)
    dialog.show()
    dialog.activateWindow()
    QApplication.processEvents()
    for button in (
        dialog.logs_toggle,
        dialog.save_logs_button,
        dialog.open_output_button,
        dialog.pause_button,
        dialog.cancel_button,
    ):
        QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Tab)
        assert dialog.focusWidget() is button


def test_log_lines_copy_scroll_and_padding(dialog: ConversionDialog) -> None:
    dialog.setStyleSheet(stylesheet())
    entries = [
        LogEntry("12:34:56", "INFO", "conversion", "long " + "x" * 250, {"input": "a.ttf"}),
        LogEntry("12:34:57", "WARNING", "skip", "skipped", {"input": "b.ttf"}),
        LogEntry("12:34:58", "ERROR", "failed", "failed", {}),
    ]
    for entry in entries:
        dialog.log.append_entry(entry)
    dialog.show()
    dialog.logs_toggle.click()
    QApplication.processEvents()
    assert dialog.log.viewport().geometry().x() == 15
    assert dialog.log.viewport().geometry().y() == 13
    assert dialog.log.font().pixelSize() == 12
    assert dialog.log.horizontalScrollBar().maximum() > 0
    for i in range(len(entries)):
        assert dialog.log.visualItemRect(dialog.log.item(i)).height() == 20
        dialog.log.item(i).setSelected(True)
    QTest.keyClick(dialog.log, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QApplication.clipboard().text() == "\n".join(entry.display_text() for entry in entries)
    assert dialog.log.item(0).text() == entries[0].display_text()


def test_log_wider_later_and_clear(dialog: ConversionDialog) -> None:
    dialog.setStyleSheet(stylesheet())
    dialog.show()
    dialog.logs_toggle.click()
    dialog.log.append_entry(LogEntry("t", "INFO", "a", "short", {}))
    QApplication.processEvents()
    old_max = dialog.log.horizontalScrollBar().maximum()
    dialog.log.append_entry(LogEntry("t", "ERROR", "b", "long" * 300, {}))
    QApplication.processEvents()
    assert dialog.log.horizontalScrollBar().maximum() > old_max
    dialog.log.clear()
    dialog.log.append_entry(LogEntry("t", "INFO", "a", "short", {}))
    QApplication.processEvents()
    assert dialog.log.horizontalScrollBar().maximum() == old_max


def test_log_scrollbar_corner_is_surface_color(dialog: ConversionDialog) -> None:
    dialog.setStyleSheet(stylesheet())
    dialog.show()
    dialog.logs_toggle.click()
    entry = LogEntry("t", "INFO", "event", "long" * 300, {})
    for _ in range(40):
        dialog.log.append_entry(entry)
    QApplication.processEvents()
    assert dialog.log.horizontalScrollBar().maximum() > 0
    assert dialog.log.verticalScrollBar().maximum() > 0
    corner = dialog.log.findChild(QWidget, "conversionLogCorner")
    assert corner is not None
    assert corner.grab().toImage().pixelColor(corner.width() // 2, corner.height() // 2).name() == (
        LIGHT.surface
    )
