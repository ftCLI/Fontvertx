"""Modal dialog that shows conversion progress, controls and logs."""

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QFocusEvent,
    QHideEvent,
    QIcon,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from fontvertx.gui.conversion_log import ConversionLog
from fontvertx.gui.icons import material_icon
from fontvertx.gui.status_pill import StatusIcon, StatusState, status_icon
from fontvertx.gui.styles import LIGHT
from fontvertx.gui.tooltips import wrap_tip
from fontvertx.gui.widgets import KeyboardPushButton


class DialogButton(KeyboardPushButton):
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


class ConversionProgress(QProgressBar):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("conversionProgress")
        self.setFixedHeight(8)
        self.state = StatusState.RUNNING
        self.fraction = 0.0
        self.setTextVisible(False)

    def set_run_state(self, state: StatusState, converted: int, total: int) -> None:
        self.state = state
        self.fraction = (
            1.0
            if state in (StatusState.DONE, StatusState.WARNING, StatusState.ERRORS)
            else (max(0.0, min(1.0, converted / total)) if total else 0.0)
        )
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        track, fill = {
            StatusState.RUNNING: (LIGHT.progress_track, LIGHT.primary),
            StatusState.PAUSED: (LIGHT.warn_fill, LIGHT.warn_accent),
            StatusState.CANCELLED: (LIGHT.border, LIGHT.control_border_strong),
            StatusState.DONE: (LIGHT.success_border, LIGHT.success_icon),
            StatusState.WARNING: (LIGHT.warn_bg, LIGHT.warn_border),
        }.get(self.state, (LIGHT.danger_bg, LIGHT.danger))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 4, 4)
        painter.fillPath(path, QColor(track))
        painter.setClipPath(path)
        fill_width = self.width() * self.fraction
        fill_path = QPainterPath()
        fill_path.addRoundedRect(
            QRectF(0, 0, fill_width, self.height()), min(4.0, fill_width / 2), 4
        )
        painter.fillPath(fill_path, QColor(fill))


class FileLabel(QLabel):
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        text = self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideMiddle, self.width()
        )
        self.style().drawItemText(
            painter,
            self.rect(),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.palette(),
            self.isEnabled(),
            text,
            self.foregroundRole(),
        )


class ConversionDialog(QDialog):
    """Hosts status, progress, Pause/Cancel and an expandable log; never closes mid-run."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Conversion")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(700)
        self._running = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.status = QLabel()
        self.status.setObjectName("statusLabel")
        self.status.setProperty("conversionStatus", True)
        self.status_icon = StatusIcon(18)
        self._state: StatusState | None = None
        self._status_icons: dict[StatusState, QIcon] = {
            state: material_icon(*status_icon(state), size=18)
            for state in StatusState
            if state is not StatusState.NOTICE
        }
        self._spinner = QTimer(self)
        self._spinner.setInterval(16)
        self._spinner.timeout.connect(self._rotate_spinner)
        status_row = QWidget()
        status_row.setFixedHeight(20)
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        status_layout.addWidget(self.status_icon)
        status_layout.addWidget(self.status, 1)
        self.progress = ConversionProgress()
        self.progress.setRange(0, 1)
        self.progress.setTextVisible(False)

        self.pause_button = DialogButton("Pause")
        self.pause_button.setToolTip(
            wrap_tip("Pause after the font being converted; Resume continues with the next one.")
        )
        self.cancel_button = DialogButton("Cancel")
        self.cancel_button.setToolTip(
            wrap_tip("Stops the conversion. Files already converted are kept.")
        )
        self.logs_toggle = DialogButton("Show logs")
        self.logs_toggle.setCheckable(True)
        self.save_logs_button = DialogButton("Save logs")
        self.save_logs_button.setEnabled(False)
        self.open_output_button = DialogButton("Open output folder")
        self.open_output_button.setEnabled(False)
        self.close_button = DialogButton("Close")
        self.close_button.setObjectName("primaryButton")
        self.file_line = FileLabel()
        self.file_line.setObjectName("conversionFileLine")
        self.file_line.setFixedHeight(16)
        self.file_line.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

        self.log = ConversionLog()
        self.log.setMinimumHeight(260)
        self.log.setVisible(False)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.logs_toggle)
        buttons.addWidget(self.save_logs_button)
        buttons.addStretch()
        buttons.addWidget(self.open_output_button)
        self._buttons = buttons

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(status_row)
        layout.setSpacing(0)
        layout.addSpacing(10)
        layout.addWidget(self.progress)
        layout.addSpacing(8)
        layout.addWidget(self.file_line)
        layout.addLayout(buttons)
        self._log_spacing = QWidget()
        self._log_spacing.setFixedHeight(9)
        self._log_spacing.hide()
        layout.addWidget(self._log_spacing)
        layout.addWidget(self.log, 1)

        self.logs_toggle.toggled.connect(self._set_logs_visible)
        self.close_button.clicked.connect(self.accept)
        self.setTabOrder(self.logs_toggle, self.save_logs_button)
        self.setTabOrder(self.save_logs_button, self.open_output_button)
        self.setTabOrder(self.open_output_button, self.pause_button)
        self.setTabOrder(self.pause_button, self.cancel_button)
        self.setTabOrder(self.cancel_button, self.close_button)
        self.set_running(False)

    def set_running(self, running: bool) -> None:
        self._running = running
        for button in (self.pause_button, self.cancel_button, self.close_button):
            self._buttons.removeWidget(button)
        last_item = self._buttons.itemAt(self._buttons.count() - 1)
        if last_item is not None and last_item.spacerItem():
            self._buttons.takeAt(self._buttons.count() - 1)
        self.pause_button.setVisible(running)
        self.cancel_button.setVisible(running)
        self.close_button.setVisible(not running)
        if running:
            self._buttons.addWidget(self.pause_button)
            self._buttons.addSpacing(8)
            self._buttons.addWidget(self.cancel_button)
        else:
            self._buttons.addWidget(self.close_button)

    def set_status(self, text: str, state: str = "") -> None:
        self.status.setText(text)
        self.status.setToolTip(text if state == "error" else "")
        self.status.setProperty("state", state)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def set_run_status(
        self,
        state: StatusState,
        text: str,
        detail: str = "",
        *,
        converted: int = 0,
        total: int = 0,
        failed_files: list[Path] | None = None,
    ) -> None:
        if state is StatusState.NOTICE:
            raise ValueError("A notice is not a run status")
        self._state = state
        tone = (
            "running"
            if state is StatusState.RUNNING
            else "warning"
            if state in (StatusState.PAUSED, StatusState.WARNING)
            else "neutral"
            if state is StatusState.CANCELLED
            else "success"
            if state is StatusState.DONE
            else "error"
        )
        self.set_status(text, tone)
        self.status.setToolTip(wrap_tip(detail) if detail else "")
        self.status_icon.set_icon(self._status_icons[state])
        self.status_icon.rotating = state is StatusState.RUNNING
        self.progress.set_run_state(state, converted, total)
        names = failed_files or []
        text_line = ""
        if state in (StatusState.ERRORS, StatusState.FAILED, StatusState.FATAL) and names:
            text_line = f"Failed: {names[0].name}"
            if len(names) > 1:
                text_line += f" and {len(names) - 1} more"
        self.file_line.setText(text_line)
        self.file_line.setToolTip(text_line)
        self.file_line.setProperty("failed", bool(text_line))
        self.file_line.style().unpolish(self.file_line)
        self.file_line.style().polish(self.file_line)
        self._sync_spinner()

    def _rotate_spinner(self) -> None:
        self.status_icon.angle = (self.status_icon.angle + 6) % 360
        self.status_icon.update()

    def _sync_spinner(self) -> None:
        if self._state is StatusState.RUNNING and self.isVisible():
            if not self._spinner.isActive():
                self._spinner.start()
        else:
            self._spinner.stop()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._sync_spinner()

    def hideEvent(self, event: QHideEvent) -> None:
        self._spinner.stop()
        super().hideEvent(event)

    def _set_logs_visible(self, visible: bool) -> None:
        self.logs_toggle.setText("Hide logs" if visible else "Show logs")
        self._log_spacing.setVisible(visible)
        self.log.setVisible(visible)
        if not visible:
            self.setMinimumHeight(0)
            self.adjustSize()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._running:
            event.ignore()
            return
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self._running:
            event.ignore()
            return
        super().keyPressEvent(event)
