"""The footer status: run progress, run result, or a dismissible notice.

One state machine (``StatusState``) drives everything the footer shows on the left of
its main button: progress while a run is active (states 2 and 3 of the footer), the
outcome chip and counts once it ends (states 4 and 5), or a short notice. The window
swaps its main button (Convert, or Pause / Cancel) from the same state.
"""

from enum import Enum

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QHelpEvent,
    QIcon,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from fontvertx.gui.icons import material_icon
from fontvertx.gui.styles import FOOTER_HEIGHT, LIGHT, mono_family
from fontvertx.gui.tooltips import wrap_tip
from fontvertx.gui.widgets import ElidedLabel, KeyboardPushButton, centered_icon_pixels
from fontvertx.gui.worker import format_duration


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


ACTIVE_STATES = (StatusState.RUNNING, StatusState.PAUSED)
PAUSED_HINT = "The next font starts when you resume."
# Pause and Cancel take effect between fonts: the font being converted finishes first.
PAUSING_HINT = "Pauses when the current font is done."
CANCELLING_HINT = "Stops when the current font is done."


def format_elapsed(elapsed: float) -> str:
    hours, seconds = divmod(max(0, int(elapsed)), 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def format_message(
    state: StatusState, *, done: int, total: int, elapsed: float, skipped: int = 0, failed: int = 0
) -> str:
    """One-line description of a run status (accessibility announcements, tooltips)."""
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


def state_tone(state: StatusState, notice_tone: str = "") -> str:
    """Tone shared by the footer card, the chips and the result buttons."""
    if state is StatusState.RUNNING:
        return "running"
    if state is StatusState.DONE:
        return "success"
    if state in (StatusState.PAUSED, StatusState.WARNING):
        return "warning"
    if state in (StatusState.FAILED, StatusState.ERRORS, StatusState.FATAL):
        return "error"
    if state is StatusState.CANCELLED:
        return "neutral"
    return notice_tone


class RunPhase(Enum):
    """What an active run is doing, as the footer title and the chips show it."""

    RUNNING = "running"
    PAUSING = "pausing"  # Pause clicked: the current font is still converting
    CANCELLING = "cancelling"  # Cancel clicked: the current font is still converting
    PAUSED = "paused"


def run_phase(
    state: StatusState, *, pausing: bool = False, cancelling: bool = False
) -> RunPhase | None:
    """Phase of an active run; priority Paused > Cancelling > Pausing > Running."""
    if state is StatusState.PAUSED:
        return RunPhase.PAUSED
    if state is not StatusState.RUNNING:
        return None
    if cancelling:
        return RunPhase.CANCELLING
    if pausing:
        return RunPhase.PAUSING
    return RunPhase.RUNNING


# The one place for the wording of an active run: footer title, its hint, chip icon.
PHASE_TITLES = {
    RunPhase.RUNNING: "Converting…",
    RunPhase.PAUSING: "Pausing…",
    RunPhase.CANCELLING: "Cancelling…",
    RunPhase.PAUSED: "Paused",
}
PHASE_HINTS = {
    RunPhase.PAUSING: PAUSING_HINT,
    RunPhase.CANCELLING: CANCELLING_HINT,
    RunPhase.PAUSED: PAUSED_HINT,
}
PHASE_CHIP_ICONS = {
    RunPhase.RUNNING: "sync_alt",
    RunPhase.PAUSING: "pause",
    RunPhase.CANCELLING: "close",
    RunPhase.PAUSED: "pause",
}


def chip_content(
    state: StatusState,
    *,
    skipped: int = 0,
    failed: int = 0,
    pausing: bool = False,
    cancelling: bool = False,
) -> tuple[str, str]:
    """Text and icon name of the status chip (log window and footer result)."""
    phase = run_phase(state, pausing=pausing, cancelling=cancelling)
    if phase is not None:
        # "Running" rather than the footer's "Converting…"; the other phases read the same.
        text = "Running" if phase is RunPhase.RUNNING else PHASE_TITLES[phase]
        return text, PHASE_CHIP_ICONS[phase]
    if state is StatusState.DONE:
        return "Done", "check"
    if state is StatusState.WARNING:
        return f"{skipped} skipped", "warning"
    if state in (StatusState.ERRORS, StatusState.FAILED):
        return f"{failed} failed", "priority_high"
    if state is StatusState.FATAL:
        return "Error", "priority_high"
    if state is StatusState.CANCELLED:
        return "Cancelled", "close"
    raise ValueError("A notice has no chip")


Segment = tuple[str, bool]  # (text, monospaced)


def result_segments(
    state: StatusState,
    *,
    converted: int,
    total: int,
    elapsed: float,
    skipped: int = 0,
    failed: int = 0,
) -> list[Segment]:
    """Counts beside the outcome chip: numbers monospaced, never wrapped."""
    duration = (format_duration(elapsed), True)
    if state is StatusState.CANCELLED:
        return [(str(converted), True), (" of ", False), (str(total), True)] + [
            (" converted · ", False),
            duration,
        ]
    segments: list[Segment] = []
    if state is StatusState.FATAL:
        segments.append(("Conversion stopped · ", False))
    segments += [(str(converted), True), (" converted", False)]
    if skipped and state is not StatusState.WARNING:
        segments += [(" · ", False), (str(skipped), True), (" skipped", False)]
    segments += [(" · ", False), duration]
    return segments


RESULT_ICON_SIZE = 22  # white circle behind the notice glyph
RESULT_GLYPH_SIZE = 14
STATUS_GLYPH_SIZE = 20
PROGRESS_HEIGHT = 6
CHIP_ICON_SIZE = 16
CHIP_HEIGHT = 24  # rounded ends: radius 12px in the stylesheet
ACTION_ICON_SIZE = 18
ICON_BUTTON_SIZE = 38  # round icon-only View log / Open output folder


class StatusIcon(QLabel):
    """Status glyph, painted from its QIcon at the current device pixel ratio.

    With ``circle`` the glyph sits on a white disc (the footer's notice badge).
    The glyph is placed on whole device pixels (see ``centered_icon_pixels``).
    """

    def __init__(self, size: int = 20, glyph: int | None = None) -> None:
        super().__init__()
        self.setFixedSize(size, size)
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
        ratio = painter.device().devicePixelRatioF()
        glyph_px, offset_px = centered_icon_pixels(self.width(), self._glyph, ratio)
        pixmap = QPixmap(self._icon.pixmap(QSize(glyph_px, glyph_px), 1.0))
        pixmap.setDevicePixelRatio(ratio)
        painter.drawPixmap(QPointF(offset_px / ratio, offset_px / ratio), pixmap)


class ConversionProgress(QProgressBar):
    """Thin rounded progress bar (6px): accent while running, grey while paused.

    A real QProgressBar, so assistive technologies read its value.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("conversionProgress")
        self.setAccessibleName("Conversion progress")
        self.setTextVisible(False)
        self.setFixedHeight(PROGRESS_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setRange(0, 1)
        self.setValue(0)
        self.track = LIGHT.running_track
        self.fill = LIGHT.accent

    def set_colors(self, track: str, fill: str) -> None:
        self.track, self.fill = track, fill
        self.update()

    @property
    def fraction(self) -> float:
        span = self.maximum() - self.minimum()
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (self.value() - self.minimum()) / span))

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


class SegmentLabel(QWidget):
    """Single line of text runs, some monospaced; elided with "…" when cut, never wrapped.

    The color and size come from the stylesheet (``color``, ``font-size``); monospaced
    runs use the same pixel size in the monospaced family.
    """

    def __init__(self) -> None:
        super().__init__()
        self._segments: list[Segment] = []
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(1)

    def set_segments(self, segments: list[Segment]) -> None:
        self._segments = list(segments)
        self.setAccessibleName(self.text())
        self.updateGeometry()
        self.update()

    def segments(self) -> list[Segment]:
        return list(self._segments)

    def text(self) -> str:
        return "".join(text for text, _ in self._segments)

    def _mono(self) -> QFont:
        font = QFont(mono_family())
        font.setStyleHint(QFont.StyleHint.Monospace)
        base = self.font()
        if base.pixelSize() > 0:
            font.setPixelSize(base.pixelSize())
        else:
            font.setPointSizeF(base.pointSizeF())
        font.setWeight(base.weight())
        return font

    def _metrics(self, mono: bool) -> QFontMetrics:
        return QFontMetrics(self._mono() if mono else self.font())

    def natural_width(self) -> int:
        return sum(self._metrics(mono).horizontalAdvance(text) for text, mono in self._segments)

    def is_elided(self) -> bool:
        return self.natural_width() > self.contentsRect().width()

    def sizeHint(self) -> QSize:
        height = max(self._metrics(False).height(), self._metrics(True).height())
        return QSize(self.natural_width() + 1, height)

    def minimumSizeHint(self) -> QSize:
        return QSize(1, self.sizeHint().height())

    def event(self, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.ToolTip
            and isinstance(event, QHelpEvent)
            and not self.toolTip()
        ):
            # Without an explicit tooltip, show the full text only when it is cut.
            if self.is_elided():
                QToolTip.showText(event.globalPos(), self.text(), self)
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().event(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        rect = self.contentsRect()
        x = rect.x()
        right = rect.right() + 1
        for text, mono in self._segments:
            font = self._mono() if mono else self.font()
            metrics = QFontMetrics(font)
            width = metrics.horizontalAdvance(text)
            painter.setFont(font)
            baseline = rect.y() + (rect.height() - metrics.height()) // 2 + metrics.ascent()
            if x + width > right:
                elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, right - x)
                if not elided:
                    elided = "…"
                painter.drawText(x, baseline, elided)
                break
            painter.drawText(x, baseline, text)
            x += width


class StatusChip(QFrame):
    """Rounded outcome chip (icon + short text) filled with its tone."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("statusChip")
        self.setProperty("tone", "")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(CHIP_HEIGHT)
        self.icon = StatusIcon(CHIP_ICON_SIZE)
        self.label = ElidedLabel()
        self.label.setObjectName("statusChipText")
        self.label.setMinimumWidth(1)
        self.label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 10, 0)
        layout.setSpacing(4)
        layout.addWidget(self.icon)
        layout.addWidget(self.label, 1)
        self._icons: dict[str, QIcon] = {}
        self.icon_name = ""

    def text(self) -> str:
        return self.label.text()

    def set_content(self, text: str, icon_name: str, tone: str) -> None:
        icon = self._icons.get(icon_name)
        if icon is None:
            icon = self._icons[icon_name] = material_icon(
                icon_name, LIGHT.on_primary, size=CHIP_ICON_SIZE
            )
        self.icon.set_icon(icon)
        self.icon_name = icon_name
        self.label.setText(text)
        self.setAccessibleName(text)
        for widget in (self, self.label):
            widget.setProperty("tone", tone)
            widget.style().unpolish(widget)
            widget.style().polish(widget)


# Notice glyph per tone: (icon name, color, on a white circle).
_TONE_GLYPHS = {
    # Weight 600, like the step badges: weight 400 is too thin at 14px.
    "success": ("check_wght600", LIGHT.success_icon, True),
    "warning": ("priority_high", LIGHT.warn_fg, True),
    "error": ("priority_high", LIGHT.danger, True),
}
_TONE_TEXT = {
    "running": LIGHT.primary_tint_fg,
    "success": LIGHT.success_icon,
    "warning": LIGHT.warn_fg,
    "error": LIGHT.danger,
    "neutral": LIGHT.slate,
}


class StatusPill(QWidget):
    """Status content of the footer card, left of its main button.

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
        self.message = ""
        self.tone = ""
        self.compact = False
        self._icon_cache: dict[tuple[str, str], QIcon] = {}

        # Notice: glyph + message (+ dismiss).
        self.icon = StatusIcon(RESULT_ICON_SIZE, STATUS_GLYPH_SIZE)
        self._icons = {
            key: material_icon(name, color, size=RESULT_GLYPH_SIZE if circle else 20)
            for key, (name, color, circle) in _TONE_GLYPHS.items()
        }
        self.label = ElidedLabel()
        self.label.setObjectName("statusLabel")
        self.label.setProperty("footerStatus", True)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.label.setMinimumWidth(1)

        # Run (states 2 and 3): title · counter · current file, progress bar below.
        self.run_title = QLabel()
        self.run_title.setObjectName("runTitle")
        self.run_counter = QLabel()
        self.run_counter.setObjectName("runCounter")
        self.run_file = ElidedLabel()
        self.run_file.setObjectName("runFile")
        self.run_file.elide_mode = Qt.TextElideMode.ElideMiddle
        self.run_file.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.run_file.setMinimumWidth(1)
        self.progress = ConversionProgress()
        self.run_view = QWidget()
        self.run_view.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        run_line = QHBoxLayout()
        run_line.setContentsMargins(0, 0, 0, 0)
        run_line.setSpacing(8)
        run_line.addWidget(self.run_title)
        run_line.addWidget(self.run_counter)
        run_line.addWidget(self.run_file, 1)
        run_layout = QVBoxLayout(self.run_view)
        run_layout.setContentsMargins(0, 0, 0, 0)
        run_layout.setSpacing(0)
        run_layout.addStretch(1)
        run_layout.addLayout(run_line)
        run_layout.addSpacing(7)
        run_layout.addWidget(self.progress)
        run_layout.addStretch(1)

        # Result (states 4 and 5): chip + counts.
        self.chip = StatusChip()
        self.counts = SegmentLabel()
        self.counts.setObjectName("resultCounts")

        self.log_button = KeyboardPushButton("View log")
        self.output_button = KeyboardPushButton("Open output folder")
        for button in (self.log_button, self.output_button):
            button.setProperty("resultAction", True)
            button.setProperty("iconOnly", False)
            button.setIconSize(QSize(ACTION_ICON_SIZE, ACTION_ICON_SIZE))
            button.setAccessibleName(button.text())
            button.setToolTip(button.text())
        self._full_text = {self.log_button: "View log", self.output_button: "Open output folder"}
        self._icon_names = {self.log_button: "visibility", self.output_button: "folder_open"}
        # Measures the labelled buttons while they show only their icon.
        self._measure = KeyboardPushButton(self)
        self._measure.setProperty("resultAction", True)
        self._measure.setProperty("iconOnly", False)
        self._measure.setIconSize(QSize(ACTION_ICON_SIZE, ACTION_ICON_SIZE))
        self._measure.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._measure.hide()
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
        self.result_buttons_layout.addWidget(self.log_button)
        self.result_buttons_layout.addWidget(self.output_button)

        self.pill_layout = QHBoxLayout(self)
        self.pill_layout.setContentsMargins(0, 0, 0, 0)
        self.pill_layout.setSpacing(10)
        self.pill_layout.addWidget(self.icon)
        self.pill_layout.addWidget(self.label, 1)
        self.pill_layout.addWidget(self.run_view, 1)
        self.pill_layout.addWidget(self.chip)
        self.pill_layout.addWidget(self.counts, 1)
        self.pill_layout.addWidget(self.result_buttons)
        self.pill_layout.addWidget(self.close_button)
        for widget in (self.icon, self.label, self.run_view, self.chip, self.counts):
            widget.hide()
        self.hide()

    # --- state ---

    def set_state(
        self,
        state: StatusState,
        *,
        done: int,
        total: int,
        elapsed: float,
        skipped: int = 0,
        failed: int = 0,
        detail: str = "",
        notice_tone: str = "error",
        converted: int | None = None,
        current_file: str = "",
        cancelling: bool = False,
        pausing: bool = False,
    ) -> None:
        converted = done if converted is None else converted
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
        # The full status sentence: announced to assistive technologies.
        self.message = text
        tone = state_tone(state, notice_tone)
        notice = state is StatusState.NOTICE
        active = state in ACTIVE_STATES
        final = not notice and not active

        self.label.setText(text if notice else "")
        self.setAccessibleDescription(f"{text}\n{detail}" if detail and detail != text else text)
        if notice and tone in self._icons:
            circle = _TONE_GLYPHS[tone][2]
            self.icon.set_icon(
                self._icons[tone],
                circle=circle,
                glyph=RESULT_GLYPH_SIZE if circle else STATUS_GLYPH_SIZE,
            )
        self.icon.setVisible(notice and tone in self._icons)
        self.label.setVisible(notice)
        self.close_button.setVisible(notice)
        self.close_button.setIcon(
            material_icon("close", _TONE_TEXT.get(tone, LIGHT.slate), size=16)
        )

        self.run_view.setVisible(active)
        if active:
            paused = state is StatusState.PAUSED
            phase = run_phase(state, pausing=pausing, cancelling=cancelling) or RunPhase.RUNNING
            title = PHASE_TITLES[phase]
            line = PHASE_HINTS.get(phase, current_file)
            waiting = phase in (RunPhase.PAUSING, RunPhase.CANCELLING)
            self.run_title.setText(title)
            self.run_counter.setText(f"{done} / {total}")
            self.run_file.setText(line)
            # While waiting for the font being converted, its path stays one hover away.
            self.run_file.setToolTip(current_file if waiting else "")
            self.run_file.elide_mode = (
                Qt.TextElideMode.ElideMiddle
                if line == current_file and not waiting
                else Qt.TextElideMode.ElideRight
            )
            # Announce what is shown.
            self.setAccessibleDescription(
                " · ".join(part for part in (title, f"{done} / {total}", line) if part)
            )
            self.progress.set_colors(
                LIGHT.border_strong if paused else LIGHT.running_track,
                LIGHT.control_border_strong if paused else LIGHT.accent,
            )

        self.chip.setVisible(final)
        self.counts.setVisible(final)
        if final:
            chip_text, chip_icon = chip_content(state, skipped=skipped, failed=failed)
            self.chip.set_content(chip_text, chip_icon, tone)
            self.counts.set_segments(
                result_segments(
                    state,
                    converted=converted,
                    total=total,
                    elapsed=elapsed,
                    skipped=skipped,
                    failed=failed,
                )
            )
            self.counts.setToolTip(wrap_tip(detail) if detail else "")
        # View log stays reachable during a run (as an icon); the output folder only after.
        self.result_buttons.setVisible(active or final)
        self.output_button.setVisible(final)
        self.log_button.setProperty("danger", tone == "error" and final)

        for widget in (
            self,
            self.label,
            self.icon,
            self.run_title,
            self.log_button,
            self.output_button,
        ):
            widget.setProperty("state", tone)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self._sync_action_icons(tone)
        self.tone = tone
        self._sync_compact()
        self.toneChanged.emit(tone)
        self.update()
        self.show()

    # --- result buttons ---

    def _action_icon(self, name: str, color: str) -> QIcon:
        key = (name, color)
        icon = self._icon_cache.get(key)
        if icon is None:
            icon = self._icon_cache[key] = material_icon(
                name, color, size=ACTION_ICON_SIZE, disabled_color=LIGHT.text_disabled
            )
        return icon

    def _sync_action_icons(self, tone: str) -> None:
        for button, name in self._icon_names.items():
            if button.property("danger"):
                color = LIGHT.danger
            elif tone == "success":
                color = LIGHT.success_icon
            elif tone == "warning" and self.state is not StatusState.PAUSED:
                color = LIGHT.warn_fg
            else:
                color = LIGHT.slate
            button.setIcon(self._action_icon(name, color))

    def full_buttons_width(self) -> int:
        """Width of View log + Open output folder with their labels."""
        self._measure.ensurePolished()
        total = 0
        for button, text in self._full_text.items():
            self._measure.setIcon(button.icon())
            self._measure.setText(text)
            total += self._measure.sizeHint().width()
        return total + self.result_buttons_layout.spacing()

    def _required_width(self) -> int:
        spacing = self.pill_layout.spacing()
        return (
            self.chip.sizeHint().width()
            + self.counts.natural_width()
            + self.full_buttons_width()
            + 2 * spacing
        )

    def _set_compact(self, compact: bool) -> None:
        for button, text in self._full_text.items():
            button.setText("" if compact else text)
            button.setProperty("iconOnly", compact)
            button.style().unpolish(button)
            button.style().polish(button)
            # After the polish: the stylesheet's size limits of the other mode must not stay.
            if compact:
                button.setFixedSize(ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)
            else:
                button.setMinimumWidth(0)
                button.setMaximumWidth(16777215)
            button.updateGeometry()
        self.compact = compact
        # Lay the buttons out again now: this often runs inside the pill's own resize.
        self.result_buttons_layout.invalidate()
        self.result_buttons.updateGeometry()
        self.pill_layout.invalidate()
        self.pill_layout.activate()

    def _sync_compact(self) -> None:
        if self.state in ACTIVE_STATES:
            compact = True  # only View log is shown, as an icon
        elif self.state is None or self.state is StatusState.NOTICE:
            compact = False
        else:
            compact = self.contentsRect().width() < self._required_width()
        if compact != self.compact:
            self._set_compact(compact)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_compact()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._sync_compact()
