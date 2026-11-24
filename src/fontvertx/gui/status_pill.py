"""A single, dismissible presentation of the current footer status."""

from enum import Enum

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QHideEvent,
    QIcon,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPixmap,
    QShowEvent,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from fontvertx.gui.icons import material_icon
from fontvertx.gui.styles import FOOTER_HEIGHT, LIGHT
from fontvertx.gui.tooltips import wrap_tip
from fontvertx.gui.widgets import ElidedLabel, KeyboardPushButton, centered_icon_pixels


class StatusState(Enum):
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    DONE = "done"
    WARNING = "warning"
    FAILED = "failed"
    ERRORS = "errors"
    FATAL = "fatal"
    NOTICE = "notice"


def format_elapsed(elapsed: float) -> str:
    hours, seconds = divmod(max(0, int(elapsed)), 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def format_message(
    state: StatusState, *, done: int, total: int, elapsed: float, skipped: int = 0, failed: int = 0
) -> str:
    time = format_elapsed(elapsed)
    if state is StatusState.RUNNING:
        message = f"Converting — {done} of {total}"
    elif state is StatusState.PAUSED:
        message = f"Paused — {done} of {total}"
    elif state is StatusState.CANCELLED:
        message = f"Cancelled — {done} of {total} converted"
    elif state in (StatusState.DONE, StatusState.WARNING):
        message = f"Done — {done} converted"
        if skipped:
            message += f" · {skipped} skipped"
    elif state is StatusState.ERRORS:
        message = f"Done with errors — {done} converted · {failed} failed"
        if skipped:
            message += f" · {skipped} skipped"
    elif state is StatusState.FAILED:
        message = f"Failed — {done} of {total} converted"
    elif state is StatusState.FATAL:
        message = f"Error — conversion stopped · {done} converted"
    else:
        raise ValueError("A notice must provide its own message")
    return f"{message} · {time}"


def status_icon(state: StatusState) -> tuple[str, str]:
    if state is StatusState.RUNNING:
        return "progress_activity", LIGHT.primary_tint_fg
    if state is StatusState.PAUSED:
        return "pause_circle", LIGHT.warn_fg
    if state is StatusState.DONE:
        return "check_circle", LIGHT.success_fg
    if state is StatusState.WARNING:
        return "warning", LIGHT.warn_fg
    if state is StatusState.CANCELLED:
        return "cancel", LIGHT.slate
    return "error", LIGHT.danger


RESULT_ICON_SIZE = 22  # white circle behind the done / error / warning glyph
RESULT_GLYPH_SIZE = 14
STATUS_GLYPH_SIZE = 20
PROGRESS_SIZE = QSize(180, 4)


class StatusIcon(QLabel):
    """Status glyph, painted from its QIcon at the current device pixel ratio.

    With ``circle`` the glyph sits on a white disc (the footer's result badge).
    The glyph is placed on whole device pixels (see ``centered_icon_pixels``).
    """

    def __init__(self, size: int = 20, glyph: int | None = None) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self.angle = 0.0
        self.rotating = False
        self._icon = QIcon()
        self._glyph = glyph or size
        self._circle = False

    def set_icon(self, icon: QIcon, *, circle: bool = False, glyph: int | None = None) -> None:
        self._icon = icon
        self._circle = circle
        if glyph is not None:
            self._glyph = glyph
        # Keeps pixmap() meaningful for accessibility and callers; painting uses the icon.
        self.setPixmap(icon.pixmap(self.size(), self.devicePixelRatioF()))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        if self._icon.isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._circle:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(LIGHT.surface))
            painter.drawEllipse(QRectF(self.rect()))
        if self.rotating:
            painter.translate(self.width() / 2, self.height() / 2)
            painter.rotate(self.angle)
            painter.translate(-self.width() / 2, -self.height() / 2)
        ratio = painter.device().devicePixelRatioF()
        glyph_px, offset_px = centered_icon_pixels(self.width(), self._glyph, ratio)
        pixmap = QPixmap(self._icon.pixmap(QSize(glyph_px, glyph_px), 1.0))
        pixmap.setDevicePixelRatio(ratio)
        painter.drawPixmap(QPointF(offset_px / ratio, offset_px / ratio), pixmap)


class InlineProgress(QWidget):
    """Thin progress bar shown after the status text while a run is active."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(PROGRESS_SIZE)
        self.fraction = 0.0
        self.track = LIGHT.running_track
        self.fill = LIGHT.accent

    def set_progress(self, fraction: float, track: str, fill: str) -> None:
        self.fraction = max(0.0, min(1.0, fraction))
        self.track, self.fill = track, fill
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = self.height() / 2
        track = QPainterPath()
        track.addRoundedRect(QRectF(self.rect()), radius, radius)
        painter.fillPath(track, QColor(self.track))
        width = self.width() * self.fraction
        if width > 0:
            fill = QPainterPath()
            fill.addRoundedRect(QRectF(0, 0, width, self.height()), radius, radius)
            painter.fillPath(fill.intersected(track), QColor(self.fill))


# Glyph per tone: (icon name, color, on a white circle).
_TONE_GLYPHS = {
    "running": ("progress_activity", LIGHT.primary_tint_fg, False),
    "paused": ("pause_circle", LIGHT.warn_fg, False),
    # Weight 600, like the step badges: weight 400 is too thin at 14px.
    "success": ("check_wght600", LIGHT.success_icon, True),
    "warning": ("priority_high", LIGHT.warn_fg, True),
    "error": ("priority_high", LIGHT.danger, True),
    "neutral": ("cancel", LIGHT.slate, False),
}
_TONE_TEXT = {
    "running": LIGHT.primary_tint_fg,
    "success": LIGHT.success_icon,
    "warning": LIGHT.warn_fg,
    "error": LIGHT.danger,
    "neutral": LIGHT.slate,
}


class StatusPill(QWidget):
    """Status content of the footer card: icon, message, progress, result actions.

    It paints nothing itself: the footer card behind it carries the tone (``toneChanged``).
    """

    dismissed = Signal()
    toneChanged = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("resultPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(FOOTER_HEIGHT)
        self.state: StatusState | None = None
        self.tone = ""
        self.icon = StatusIcon(RESULT_ICON_SIZE, STATUS_GLYPH_SIZE)
        self._icons = {
            key: material_icon(name, color, size=RESULT_GLYPH_SIZE if circle else 20)
            for key, (name, color, circle) in _TONE_GLYPHS.items()
        }
        self._spinner = QTimer(self)
        self._spinner.setInterval(16)
        self._spinner.timeout.connect(self._rotate_spinner)
        self._progress = 0.0
        self.label = ElidedLabel()
        self.label.setObjectName("statusLabel")
        self.label.setProperty("footerStatus", True)
        # Natural width, shrinking (and eliding) when space runs out, so the progress bar
        # follows the text.
        self.label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.label.setMinimumWidth(1)
        self.progress = InlineProgress()
        self.last_run_button = KeyboardPushButton("View last run")
        self.output_button = KeyboardPushButton("Open output folder")
        for button in (self.last_run_button, self.output_button):
            button.setProperty("resultAction", True)
        self.close_button = KeyboardPushButton()
        self.close_button.setProperty("pillClose", True)
        self.close_button.setFixedSize(28, 28)
        self.close_button.setIconSize(QSize(16, 16))
        self.close_button.setAccessibleName("Dismiss")
        self.close_button.clicked.connect(self.dismissed)
        self.result_buttons = QWidget()
        self.result_buttons_layout = QHBoxLayout(self.result_buttons)
        self.result_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.result_buttons_layout.setSpacing(6)
        self.result_buttons_layout.addWidget(self.last_run_button)
        self.result_buttons_layout.addWidget(self.output_button)
        self.pill_layout = QHBoxLayout(self)
        self.pill_layout.setContentsMargins(0, 0, 0, 0)
        self.pill_layout.setSpacing(10)
        self.pill_layout.addWidget(self.icon)
        self.pill_layout.addWidget(self.label)
        self.pill_layout.addWidget(self.progress)
        self.pill_layout.addStretch(1)
        self.pill_layout.addWidget(self.result_buttons)
        self.pill_layout.addWidget(self.close_button)
        self.hide()

    def set_state(
        self,
        state: StatusState,
        *,
        done: int,
        total: int,
        elapsed: float,
        dialog_open: bool,
        skipped: int = 0,
        failed: int = 0,
        detail: str = "",
        notice_tone: str = "error",
        converted: int | None = None,
    ) -> None:
        text = (
            detail
            if state is StatusState.NOTICE
            else format_message(
                state, done=done, total=total, elapsed=elapsed, skipped=skipped, failed=failed
            )
        )
        if not text:
            raise ValueError("A visible status must not be empty")
        self.state = state
        tone = (
            "running"
            if state is StatusState.RUNNING
            else "success"
            if state is StatusState.DONE
            else "warning"
            if state in (StatusState.PAUSED, StatusState.WARNING)
            else "error"
            if state in (StatusState.FAILED, StatusState.ERRORS, StatusState.FATAL)
            else notice_tone
            if state is StatusState.NOTICE
            else "neutral"
            if state is StatusState.CANCELLED
            else ""
        )
        self.label.setText(text)
        self.label.setToolTip(
            wrap_tip(detail) if detail and state is not StatusState.NOTICE else ""
        )
        self.setAccessibleDescription(f"{text}\n{detail}" if detail and detail != text else text)
        icon_name = "paused" if state is StatusState.PAUSED else tone
        if icon_name not in self._icons:
            self.icon.hide()
        else:
            circle = _TONE_GLYPHS[icon_name][2]
            self.icon.set_icon(
                self._icons[icon_name],
                circle=circle,
                glyph=RESULT_GLYPH_SIZE if circle else STATUS_GLYPH_SIZE,
            )
            self.icon.show()
        self.close_button.setIcon(
            material_icon("close", _TONE_TEXT.get(tone, LIGHT.slate), size=16)
        )
        for widget in (self, self.label, self.icon, self.last_run_button, self.output_button):
            widget.setProperty("state", tone)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        final = state not in (StatusState.RUNNING, StatusState.PAUSED, StatusState.NOTICE)
        self.result_buttons.setVisible(final and not dialog_open)
        self.close_button.setVisible(
            not dialog_open and state is not StatusState.RUNNING and state is not StatusState.PAUSED
        )
        progress = done if converted is None else converted
        self._progress = max(0.0, min(1.0, progress / total)) if total > 0 else 0.0
        active = state in (StatusState.RUNNING, StatusState.PAUSED)
        self.progress.setVisible(active)
        if active:
            running = state is StatusState.RUNNING
            self.progress.set_progress(
                self._progress,
                LIGHT.running_track if running else LIGHT.warn_fill,
                LIGHT.accent if running else LIGHT.warn_accent,
            )
        self.icon.rotating = state is StatusState.RUNNING
        self._sync_spinner()
        self.tone = tone
        self.toneChanged.emit(tone)
        self.update()
        self.show()

    def _rotate_spinner(self) -> None:
        self.icon.angle = (self.icon.angle + 6.0) % 360
        self.icon.update()

    def _sync_spinner(self) -> None:
        if self.state is StatusState.RUNNING and self.isVisible():
            if not self._spinner.isActive():
                self._spinner.start()
        else:
            self._spinner.stop()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._sync_spinner()

    def hideEvent(self, event: QHideEvent) -> None:
        self._spinner.stop()
        super().hideEvent(event)
