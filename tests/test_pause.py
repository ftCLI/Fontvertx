import threading
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt

from fontvertx import service as service_module
from fontvertx.gui.worker import ConversionWorker
from fontvertx.models import ConversionRequest, ConversionResult, TtfToOtfOptions
from fontvertx.service import ConverterService

FONTS = [Path(f"font{i}.ttf") for i in range(4)]


class FakeFont:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "FakeFont":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


@pytest.fixture
def fake_service(monkeypatch: pytest.MonkeyPatch) -> ConverterService:
    monkeypatch.setattr(service_module, "Font", FakeFont)
    monkeypatch.setattr(
        ConverterService, "_find_candidates", lambda self, request: [(p, 1, True) for p in FONTS]
    )
    monkeypatch.setattr(
        ConverterService, "_convert_font", lambda self, font, settings, on_log: [Path("out.otf")]
    )
    return ConverterService()


def make_request() -> ConversionRequest:
    return ConversionRequest(tuple(FONTS), TtfToOtfOptions())


def names(result: ConversionResult) -> list[str]:
    return [outcome.input_path.name for outcome in result.outcomes]


def run_in_thread(
    service: ConverterService, **kwargs: Any
) -> tuple[threading.Thread, list[ConversionResult]]:
    results: list[ConversionResult] = []
    thread = threading.Thread(
        target=lambda: results.append(service.convert(make_request(), **kwargs))
    )
    thread.start()
    return thread, results


def test_pause_and_resume_matches_uninterrupted_run(fake_service: ConverterService) -> None:
    expected = fake_service.convert(make_request())

    running = threading.Event()
    running.set()
    paused = threading.Event()
    converted = 0

    def wait_if_paused() -> None:
        if not running.is_set():
            paused.set()
            running.wait()

    def on_outcome(_: Any) -> None:
        nonlocal converted
        converted += 1
        if converted == 2:
            running.clear()

    thread, results = run_in_thread(
        fake_service, wait_if_paused=wait_if_paused, on_outcome=on_outcome
    )
    assert paused.wait(5)
    assert converted == 2
    running.set()
    thread.join(5)

    assert not thread.is_alive()
    assert names(results[0]) == names(expected)
    assert not results[0].cancelled


def test_cancel_while_paused_does_not_deadlock(fake_service: ConverterService) -> None:
    running = threading.Event()
    cancelled = threading.Event()
    paused = threading.Event()

    def wait_if_paused() -> None:
        if not running.is_set():
            paused.set()
            running.wait()

    thread, results = run_in_thread(
        fake_service, wait_if_paused=wait_if_paused, should_cancel=cancelled.is_set
    )
    assert paused.wait(5)
    cancelled.set()
    running.set()
    thread.join(5)

    assert not thread.is_alive()
    assert results[0].cancelled
    assert results[0].outcomes == ()


def test_pause_during_last_font_completes(fake_service: ConverterService) -> None:
    paused = False
    converted = 0

    def wait_if_paused() -> None:
        nonlocal paused
        paused = paused or converted == len(FONTS)

    def on_outcome(_: Any) -> None:
        nonlocal converted
        converted += 1

    result = fake_service.convert(
        make_request(), wait_if_paused=wait_if_paused, on_outcome=on_outcome
    )

    assert not result.cancelled
    assert len(result.outcomes) == len(FONTS)


def test_worker_cancel_unblocks_pause(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = ConversionWorker(make_request())
    states: list[bool] = []
    finished = threading.Event()
    worker.paused_changed.connect(states.append, Qt.ConnectionType.DirectConnection)
    worker.finished_conversion.connect(lambda _: finished.set(), Qt.ConnectionType.DirectConnection)

    def fake_convert(self: Any, request: Any, **kwargs: Any) -> ConversionResult:
        kwargs["wait_if_paused"]()
        return ConversionResult(cancelled=kwargs["should_cancel"]())

    monkeypatch.setattr(ConverterService, "convert", fake_convert)

    worker.pause()
    worker.start()
    for _ in range(50):
        if states:
            break
        worker.wait(100)
    assert states == [True]
    worker.cancel()
    assert worker.wait(5000)
    assert finished.is_set()
    assert states == [True, False]


def test_worker_resume_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = ConversionWorker(make_request())
    states: list[bool] = []
    worker.paused_changed.connect(states.append, Qt.ConnectionType.DirectConnection)

    def fake_convert(self: Any, request: Any, **kwargs: Any) -> ConversionResult:
        kwargs["wait_if_paused"]()
        return ConversionResult(cancelled=kwargs["should_cancel"]())

    monkeypatch.setattr(ConverterService, "convert", fake_convert)

    worker.pause()
    worker.start()
    for _ in range(50):
        if states:
            break
        worker.wait(100)
    worker.resume()
    assert worker.wait(5000)
    assert states == [True, False]
