from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from fontvertx.gui.log_window import LOG_WINDOW_TITLE, LogWindow
from fontvertx.gui.logs import LogEntry
from fontvertx.gui.styles import LIGHT, mono_family, stylesheet


@pytest.fixture
def parent(qapp: QApplication) -> QWidget:
    # A top-level widget: the autouse cleanup in conftest.py deletes it, and the log
    # window (its child) with it.
    return QWidget()


@pytest.fixture
def window(parent: QWidget) -> Iterator[LogWindow]:
    yield LogWindow(parent)


def test_initial_state_is_non_modal_and_always_shows_the_log(window: LogWindow) -> None:
    assert not window.isModal()
    assert window.windowModality() is Qt.WindowModality.NonModal
    assert window.windowTitle() == LOG_WINDOW_TITLE
    assert window.title.text() == "Last run"
    assert window.chip.isHidden()
    assert not window.log.isHidden()
    assert not window.save_logs_button.isEnabled()
    assert window.save_logs_button.text() == "Save logs…"
    assert window.close_button.text() == "Close"
    assert window.log.font().family() == mono_family()
    assert window.log.font().styleHint() == QFont.StyleHint.Monospace
    # No run controls here: they live in the main window's footer.
    for name in ("pause_button", "cancel_button", "progress", "open_output_button", "logs_toggle"):
        assert not hasattr(window, name)


def test_title_chip_and_summary(window: LogWindow) -> None:
    window.set_profile("TTF → OTF")
    assert window.title.text() == "Last run · TTF → OTF"
    window.set_run_status(
        "6 failed",
        "priority_high",
        "error",
        [("140", True), (" converted · ", False), ("12.4 s", True)],
    )
    assert not window.chip.isHidden()
    assert window.chip.text() == "6 failed"
    assert window.chip.property("tone") == "error"
    assert window.summary.text() == "140 converted · 12.4 s"
    assert window.summary.segments()[0] == ("140", True)
    window.set_profile("")
    assert window.title.text() == "Last run"


def test_closing_never_blocks(window: LogWindow, parent: QWidget) -> None:
    parent.show()
    window.show()
    window.close_button.click()
    assert not window.isVisible()
    window.show()
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert not window.isVisible()
    window.show()
    window.close()
    assert not window.isVisible()


def test_show_and_raise_reuses_the_window(window: LogWindow, parent: QWidget) -> None:
    parent.show()
    window.show_and_raise()
    assert window.isVisible()
    window.showMinimized()
    window.show_and_raise()
    assert window.isVisible() and not window.isMinimized()
    assert [w for w in QApplication.topLevelWidgets() if isinstance(w, LogWindow)] == [window]


def test_buttons_tab_order_and_keyboard_focus_ring(window: LogWindow) -> None:
    window.setStyleSheet(stylesheet())
    window.save_logs_button.setEnabled(True)
    window.show()
    window.activateWindow()
    QApplication.processEvents()
    window.log.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.keyClick(window.log, Qt.Key.Key_Tab)
    assert window.focusWidget() is window.save_logs_button
    assert window.save_logs_button.property("keyboardFocus")
    QTest.keyClick(window.save_logs_button, Qt.Key.Key_Tab)
    assert window.focusWidget() is window.close_button
    QTest.mouseClick(window.save_logs_button, Qt.MouseButton.LeftButton)
    assert not window.save_logs_button.property("keyboardFocus")
    # Buttons sit at the bottom right, Save logs… before Close.
    assert window.save_logs_button.x() < window.close_button.x()
    assert window.close_button.geometry().right() > window.width() // 2


def test_log_lines_copy_scroll_and_padding(window: LogWindow) -> None:
    window.setStyleSheet(stylesheet())
    entries = [
        LogEntry("12:34:56", "INFO", "conversion", "long " + "x" * 250, {"input": "a.ttf"}),
        LogEntry("12:34:57", "WARNING", "skip", "skipped", {"input": "b.ttf"}),
        LogEntry("12:34:58", "ERROR", "failed", "failed", {}),
    ]
    for entry in entries:
        window.log.append_entry(entry)
    window.show()
    QApplication.processEvents()
    assert window.log.viewport().geometry().x() == 15
    assert window.log.viewport().geometry().y() == 13
    assert window.log.font().pixelSize() == 12
    assert window.log.horizontalScrollBar().maximum() > 0
    for i in range(len(entries)):
        assert window.log.visualItemRect(window.log.item(i)).height() == 20
        window.log.item(i).setSelected(True)
    QTest.keyClick(window.log, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert QApplication.clipboard().text() == "\n".join(entry.display_text() for entry in entries)


def test_log_wider_later_and_clear(window: LogWindow) -> None:
    window.setStyleSheet(stylesheet())
    window.show()
    window.log.append_entry(LogEntry("t", "INFO", "a", "short", {}))
    QApplication.processEvents()
    old_max = window.log.horizontalScrollBar().maximum()
    window.log.append_entry(LogEntry("t", "ERROR", "b", "long" * 300, {}))
    QApplication.processEvents()
    assert window.log.horizontalScrollBar().maximum() > old_max
    window.log.clear()
    window.log.append_entry(LogEntry("t", "INFO", "a", "short", {}))
    QApplication.processEvents()
    assert window.log.horizontalScrollBar().maximum() == old_max


def test_log_scrollbar_corner_is_surface_color(window: LogWindow) -> None:
    window.setStyleSheet(stylesheet())
    window.show()
    entry = LogEntry("t", "INFO", "event", "long" * 300, {})
    for _ in range(40):
        window.log.append_entry(entry)
    QApplication.processEvents()
    assert window.log.horizontalScrollBar().maximum() > 0
    assert window.log.verticalScrollBar().maximum() > 0
    corner = window.log.findChild(QWidget, "conversionLogCorner")
    assert corner is not None
    image = corner.grab().toImage()
    assert image.pixelColor(corner.width() // 2, corner.height() // 2).name() == LIGHT.surface


def test_escape_key_event_closes(window: LogWindow) -> None:
    window.show()
    window.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    assert not window.isVisible()
