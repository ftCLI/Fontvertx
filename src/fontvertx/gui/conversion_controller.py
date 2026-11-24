"""Owns the lifecycle of a conversion run for the converter window.

The window collects inputs and options; this controller owns the worker
thread, the run state machine (running/paused/cancelling), the elapsed-time
timer and the progress/log reporting, so that the run logic is concentrated
in one place instead of being spread across the window.
"""

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from fontvertx.gui.logs import LogEntry
from fontvertx.gui.profiles import CONVERSIONS
from fontvertx.gui.status_pill import StatusState
from fontvertx.gui.worker import ConversionWorker, RunState, exception_type
from fontvertx.models import ConversionRequest, ConversionResult, FontOutcome, FontOutcomeKind


def profile_name(conversion: str) -> str:
    """Short profile name for titles: "TTF → OTF" for "TTF → OTF (TrueType → PostScript)"."""
    return CONVERSIONS.get(conversion, conversion).split(" (", 1)[0]


@dataclass
class RunOutcome:
    total: int = 0
    converted: int = 0
    skipped: int = 0
    failed: int = 0
    elapsed: float = 0.0
    saved_files: list[Path] = field(default_factory=list)
    failed_files: list[Path] = field(default_factory=list)

    def record(self, outcome: FontOutcome) -> None:
        if outcome.kind is FontOutcomeKind.CONVERTED:
            self.converted += 1
            self.saved_files.extend(outcome.output_paths)
        elif outcome.kind is FontOutcomeKind.SKIPPED:
            self.skipped += 1
        else:
            self.failed += 1
            self.failed_files.append(outcome.input_path)


class ConversionController(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.w = window
        self.worker: ConversionWorker | None = None
        self.run_state = RunState.IDLE
        self.cancelling = False
        self.close_when_finished = False
        self.outcome = RunOutcome()
        self.session_started_at: float | None = None
        self.session_elapsed = 0.0
        self.progress_done = 0
        self.progress_total = 0
        self.last_run_available = False
        self.run_output_directory: Path | None = None
        self.run_input_directory: Path | None = None
        self.current_input: Path | None = None
        self.finished_at: datetime | None = None
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self.refresh_progress_status)

    @property
    def saved_files(self) -> list[Path]:
        return self.outcome.saved_files

    @saved_files.setter
    def saved_files(self, files: list[Path]) -> None:
        self.outcome.saved_files = files

    def start(self, request: ConversionRequest, total: int) -> None:
        w = self.w
        w._log_entries.clear()
        w.log.clear()
        self.last_run_available = False
        self.run_output_directory = w.output_directory
        self.run_input_directory = Path(request.input_paths[0]).parent
        w.progress.setRange(0, total)
        w.progress.setValue(0)
        w._set_output_available(False)
        w.cancel_button.setEnabled(True)
        w.log_window.set_profile(profile_name(request.conversion))
        self.current_input = None
        self.finished_at = None
        self.saved_files = []
        self.progress_done = 0
        self.progress_total = total
        self.outcome = RunOutcome(total=total)
        self.session_elapsed = 0.0
        self.cancelling = False
        self.run_state = RunState.RUNNING
        self.worker = ConversionWorker(request)
        self.worker.log_received.connect(self.on_worker_event)
        self.worker.paused_changed.connect(self.on_paused_changed)
        self.worker.progress_changed.connect(self.on_progress)
        self.worker.finished_conversion.connect(self.finished)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.worker_stopped)
        self.worker.font_started.connect(self.on_font_started)
        self.session_started_at = time.perf_counter()
        w._set_run_status(StatusState.RUNNING)
        w._update_buttons()
        w._append_log(
            LogEntry.create(
                "INFO",
                "conversion.started",
                f"Started {request.conversion} conversion",
                {
                    "profile": request.conversion,
                    "input_count": len(request.input_paths),
                    "inputs": [path.name for path in request.input_paths],
                    "target_count": total,
                },
            )
        )
        self.elapsed_timer.start()
        self.worker.start()

    def on_font_started(self, path: Path) -> None:
        self.current_input = path
        self.refresh_progress_status()

    def on_worker_event(self, event: LogEntry) -> None:
        if event.outcome is not None:
            self.outcome.record(event.outcome)
        self.w._append_log(event)

    def elapsed(self) -> float:
        if self.session_started_at is None:
            return self.session_elapsed
        return time.perf_counter() - self.session_started_at

    def finish_timer(self) -> None:
        self.elapsed_timer.stop()
        self.finished_at = datetime.now()
        if self.session_started_at is not None:
            self.session_elapsed = time.perf_counter() - self.session_started_at
            self.session_started_at = None
        self.outcome.elapsed = self.session_elapsed

    def refresh_progress_status(self) -> None:
        # Keeps rendering while a pause or a cancel waits for the current font.
        if self.run_state not in (RunState.RUNNING, RunState.PAUSING):
            return
        self.outcome.elapsed = self.elapsed()
        self.w._set_run_status(StatusState.RUNNING)

    def on_progress(self, done: int, total: int) -> None:
        self.w.progress.setRange(0, total)
        self.w.progress.setValue(done)
        self.progress_done = done
        self.progress_total = total
        self.outcome.total = total
        self.refresh_progress_status()

    def output_folder_to_open(self) -> Path | None:
        if self.run_output_directory is not None:
            return self.run_output_directory
        parents = {path.parent for path in self.saved_files}
        if parents:
            try:
                return Path(os.path.commonpath(parents))
            except ValueError:
                return min(parents)
        return self.run_input_directory

    def toggle_pause(self) -> None:
        if self.worker is None or self.cancelling:
            return
        if self.run_state is RunState.RUNNING:
            self.run_state = RunState.PAUSING
            self.w.pause_button.setEnabled(False)
            self.worker.pause()
            self.w._append_log(
                LogEntry.create(
                    "INFO",
                    "conversion.pause_requested",
                    "Pause requested: the current font finishes first",
                    {"done": self.progress_done, "total": self.progress_total},
                )
            )
            self.refresh_progress_status()
        elif self.run_state is RunState.PAUSED:
            self.worker.resume()

    def on_paused_changed(self, paused: bool) -> None:
        w = self.w
        if self.worker is None:
            return
        if paused:
            if self.run_state is not RunState.PAUSING or self.cancelling:
                return
            self.run_state = RunState.PAUSED
            self.finish_timer()
            w._set_run_status(StatusState.PAUSED)
            w._append_log(
                LogEntry.create(
                    "INFO",
                    "conversion.paused",
                    f"Paused at {self.progress_done} / {self.progress_total}",
                    {"done": self.progress_done, "total": self.progress_total},
                )
            )
        else:
            if self.run_state is not RunState.PAUSED:
                return
            self.run_state = RunState.RUNNING
            if not self.cancelling:
                self.session_started_at = time.perf_counter() - self.session_elapsed
                self.elapsed_timer.start()
                w._append_log(
                    LogEntry.create("INFO", "conversion.resumed", "Resumed conversion", {})
                )
            # Also when resuming because of a cancel: the footer shows "Cancelling…".
            self.refresh_progress_status()
        w._update_buttons()

    def cancel(self) -> None:
        self.request_cancel()

    def request_cancel(self) -> None:
        if self.worker is None or self.cancelling:
            return  # a second Cancel changes nothing
        self.w.cancel_button.setEnabled(False)
        self.cancelling = True
        self.worker.cancel()
        if self.run_state is not RunState.PAUSED:
            # From Paused the run stops almost at once; otherwise the font being
            # converted finishes first.
            self.w._append_log(
                LogEntry.create(
                    "INFO",
                    "conversion.cancel_requested",
                    "Cancel requested: the current font finishes first",
                    {"done": self.progress_done, "total": self.progress_total},
                )
            )
            self.refresh_progress_status()
        self.w._update_buttons()

    def finished(self, result: ConversionResult) -> None:
        w = self.w
        self.finish_timer()
        self.last_run_available = True
        if result.cancelled:
            w._append_log(
                LogEntry.create(
                    "WARNING",
                    "conversion.cancelled",
                    self.batch_summary(result),
                    {"elapsed_seconds": self.session_elapsed},
                )
            )
            w._set_run_status(StatusState.CANCELLED)
            w._set_output_available(self.output_folder_to_open() is not None)
            return
        if not result.ok:
            failed_outcomes = [
                outcome for outcome in result.outcomes if outcome.kind is FontOutcomeKind.FAILED
            ]
            failure_details = [
                f"{outcome.input_path.name}: {outcome.error or 'Unknown error'}"
                for outcome in failed_outcomes
            ]
            message = result.error or "; ".join(failure_details) or "Conversion failed."
            error_types = sorted(
                {
                    error_type
                    for error_text in ([result.error] if result.error else [])
                    + [outcome.error for outcome in failed_outcomes if outcome.error]
                    if (error_type := exception_type(error_text)) is not None
                }
            )
            w._append_log(
                LogEntry.create(
                    "ERROR",
                    "conversion.failed",
                    message,
                    {
                        "elapsed_seconds": self.session_elapsed,
                        "converted": self.outcome.converted,
                        "skipped": self.outcome.skipped,
                        "failed": self.outcome.failed,
                        "error_types": error_types,
                        "failures": [
                            {
                                "input": outcome.input_path.name,
                                "error_type": exception_type(outcome.error or ""),
                                "error": outcome.error,
                            }
                            for outcome in failed_outcomes
                        ],
                    },
                )
            )
            state = (
                StatusState.FATAL
                if not self.outcome.failed
                else StatusState.FAILED
                if not (self.outcome.converted or self.outcome.skipped)
                else StatusState.ERRORS
            )
            w._set_run_status(state, detail=message)
            w._set_output_available(self.output_folder_to_open() is not None)
            return
        w._append_log(
            LogEntry.create(
                "INFO",
                "conversion.completed",
                self.batch_summary(result),
                {
                    "elapsed_seconds": self.session_elapsed,
                    "converted": self.outcome.converted,
                    "skipped": self.outcome.skipped,
                    "failed": self.outcome.failed,
                },
            )
        )
        w.progress.setValue(w.progress.maximum())
        w._set_run_status(StatusState.WARNING if self.outcome.skipped else StatusState.DONE)
        w._set_output_available(self.output_folder_to_open() is not None)

    @staticmethod
    def status_summary(result: ConversionResult) -> str:
        counts = (
            (result.converted_count, "converted"),
            (result.skipped_count, "skipped"),
            (result.failed_count, "failed"),
        )
        return ", ".join(f"{count} {label}" for count, label in counts if count)

    @staticmethod
    def batch_summary(result: ConversionResult) -> str:
        return (
            f"{result.converted_count} converted, {result.skipped_count} skipped, "
            f"{result.failed_count} failed"
        )

    def show_error(
        self,
        message: str,
        log_event: str | None = "application.error",
        log_context: dict[str, object] | None = None,
        *,
        terminal: bool = False,
    ) -> None:
        w = self.w
        w._set_status(message, "error", terminal=terminal)
        if log_event is not None:
            w._append_log(
                LogEntry.create("ERROR", log_event, message, log_context or {"message": message})
            )
        w.progress.setRange(0, 1)
        w.progress.setValue(0)

    def failed(self, message: str) -> None:
        self.finish_timer()
        self.last_run_available = True
        self.w._append_log(
            LogEntry.create(
                "ERROR",
                "conversion.failed",
                f"Conversion failed: {message}",
                {
                    "error": message,
                    "error_type": exception_type(message),
                    "elapsed_seconds": self.session_elapsed,
                },
            )
        )
        self.w._set_run_status(StatusState.FATAL, detail=message)
        self.w._set_output_available(self.output_folder_to_open() is not None)

    def worker_stopped(self) -> None:
        self.finish_timer()
        worker = self.worker
        self.worker = None
        if worker is not None:
            # Schedule deletion instead of dropping the wrapper here: we are handling
            # the thread's own finished signal, so immediate GC could destroy the
            # QThread C++ object mid-signal.
            worker.deleteLater()
        self.run_state = RunState.IDLE
        self.w._update_buttons()
        if self.close_when_finished:
            self.w.close()

    def force_stop(self) -> None:
        """Terminate the worker thread immediately (last resort for a hung conversion)."""
        worker = self.worker
        if worker is not None and worker.isRunning():
            worker.terminate()
            worker.wait()

    def open_output_folder(self) -> None:
        output_directory = self.output_folder_to_open()
        if output_directory is not None and not QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(output_directory))
        ):
            self.w._set_status("Could not open the output folder.", "error")
