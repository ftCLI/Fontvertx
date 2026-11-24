"""Non-modal window that shows the log of the last conversion run.

It only shows: the run itself is driven from the main window's footer, and closing
this window never stops or changes a conversion.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from fontvertx.gui.conversion_log import ConversionLog
from fontvertx.gui.status_pill import Segment, SegmentLabel, StatusChip
from fontvertx.gui.widgets import KeyboardPushButton

LOG_WINDOW_TITLE = "Conversion log"


class DialogButton(KeyboardPushButton):
    """Dialog button whose focus ring shows only for keyboard focus."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.setProperty("conversionButton", True)
        self.setProperty("keyboardFocus", False)
        self.setAutoDefault(False)
        self.setDefault(False)

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        self.setProperty(
            "keyboardFocus",
            event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason),
        )
        self.style().unpolish(self)
        self.style().polish(self)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.setProperty("keyboardFocus", False)
        self.style().unpolish(self)
        self.style().polish(self)


class LogWindow(QDialog):
    """Title "Last run · <profile>", outcome chip, summary line, live log, Save / Close."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(LOG_WINDOW_TITLE)
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumSize(700, 420)

        self.title = QLabel("Last run")
        self.title.setObjectName("logWindowTitle")
        self.chip = StatusChip()
        self.chip.hide()
        self.summary = SegmentLabel()
        self.summary.setObjectName("logWindowSummary")

        self.log = ConversionLog()
        self.log.setMinimumHeight(260)

        self.save_logs_button = DialogButton("Save logs…")
        self.save_logs_button.setEnabled(False)
        self.close_button = DialogButton("Close")
        self.close_button.setObjectName("primaryButton")
        self.close_button.clicked.connect(self.close)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.title, 1)
        header.addWidget(self.chip)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        buttons.addStretch(1)
        buttons.addWidget(self.save_logs_button)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addSpacing(4)
        layout.addWidget(self.summary)
        layout.addSpacing(12)
        layout.addWidget(self.log, 1)
        layout.addSpacing(12)
        layout.addLayout(buttons)
        self.setTabOrder(self.log, self.save_logs_button)
        self.setTabOrder(self.save_logs_button, self.close_button)

    def set_profile(self, profile: str) -> None:
        self.title.setText(f"Last run · {profile}" if profile else "Last run")

    def set_run_status(
        self, chip_text: str, chip_icon: str, tone: str, summary: list[Segment]
    ) -> None:
        self.chip.set_content(chip_text, chip_icon, tone)
        self.chip.show()
        self.summary.set_segments(summary)

    def show_and_raise(self) -> None:
        """Show the window, or bring the existing one to the front."""
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
