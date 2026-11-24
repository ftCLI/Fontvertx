"""Conversion worker and shared run-state helpers for the GUI."""

import logging
import threading
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from fontvertx.gui.logs import LogEntry, LogLevel
from fontvertx.models import ConversionRequest, FontOutcome, FontOutcomeKind
from fontvertx.service import ConverterService


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def exception_type(message: str) -> str | None:
    """Extract the exception class name from a 'SomeError: message' string."""
    name, separator, _ = message.partition(": ")
    candidate = name.rsplit(".", 1)[-1]
    return candidate if separator and candidate.isidentifier() else None


class RunState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"


class _LogBridge(logging.Handler):
    """Forwards INFO+ records from fontvertx loggers to the GUI conversion log.

    Records from ``fontvertx.service`` are skipped: conversion steps and
    per-font outcomes already reach the GUI through the service callbacks.
    """

    def __init__(self, emit) -> None:
        super().__init__(level=logging.INFO)
        self._emit = emit

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == "fontvertx.service":
            return
        level: LogLevel = "INFO"
        if record.levelno >= logging.ERROR:
            level = "ERROR"
        elif record.levelno >= logging.WARNING:
            level = "WARNING"
        self._emit(level, record.name, record.getMessage(), {})


class ConversionWorker(QThread):
    log_received = Signal(object)
    progress_changed = Signal(int, int)
    finished_conversion = Signal(object)
    failed = Signal(str)
    paused_changed = Signal(bool)

    def __init__(self, request: ConversionRequest) -> None:
        super().__init__()
        self.request = request
        self._current_input: Path | None = None
        # threading.Event operations are atomic; no extra lock is needed.
        self._running = threading.Event()
        self._running.set()

    def pause(self) -> None:
        if not self.isInterruptionRequested():
            self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def cancel(self) -> None:
        self.requestInterruption()
        # Always release a paused thread, so cancellation is not blocked by the pause.
        self._running.set()

    def wait_if_paused(self) -> None:
        if self._running.is_set():
            return
        self.paused_changed.emit(True)
        self._running.wait()
        self.paused_changed.emit(False)

    def run(self) -> None:
        bridge = _LogBridge(self._log)
        package_logger = logging.getLogger("fontvertx")
        package_logger.addHandler(bridge)
        try:
            result = ConverterService().convert(
                self.request,
                on_log=lambda message: self._log(
                    "INFO",
                    "conversion.step",
                    message,
                    {
                        "profile": self.request.conversion,
                        "input": (
                            self._current_input.name if self._current_input is not None else None
                        ),
                    },
                ),
                on_outcome=self._report_outcome,
                on_progress=lambda progress: self.progress_changed.emit(
                    progress.done, progress.total
                ),
                should_cancel=self.isInterruptionRequested,
                on_font_start=self._on_font_start,
                wait_if_paused=self.wait_if_paused,
            )
            self.finished_conversion.emit(result)
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")
        finally:
            package_logger.removeHandler(bridge)

    def _on_font_start(self, input_path: Path) -> None:
        self._current_input = input_path

    def _report_outcome(self, outcome: FontOutcome) -> None:
        duration = format_duration(outcome.elapsed)
        name = outcome.input_path.name
        if self.request.conversion == "var2static" and outcome.output_paths:
            name = f"{name} → {outcome.output_paths[0].name}"
        if outcome.kind is FontOutcomeKind.CONVERTED:
            self._log(
                "INFO",
                "font.converted",
                f"Converted {name} in {duration}",
                {
                    "input": outcome.input_path.name,
                    "outputs": [path.name for path in outcome.output_paths],
                    "elapsed_seconds": outcome.elapsed,
                },
                outcome=outcome,
            )
        elif outcome.kind is FontOutcomeKind.SKIPPED:
            self._log(
                "INFO",
                "font.skipped",
                f"Skipped {name}",
                {"input": outcome.input_path.name},
                outcome=outcome,
            )
        else:
            error = outcome.error or "Unknown error"
            self._log(
                "ERROR",
                "font.failed",
                f"{error} ({name}, {duration})",
                {
                    "input": outcome.input_path.name,
                    "elapsed_seconds": outcome.elapsed,
                    "error_type": exception_type(error),
                    "error": error,
                },
                outcome=outcome,
            )

    def _log(
        self,
        level: LogLevel,
        event: str,
        message: str,
        context: dict[str, object] | None = None,
        *,
        outcome: FontOutcome | None = None,
    ) -> None:
        self.log_received.emit(LogEntry.create(level, event, message, context, outcome=outcome))
