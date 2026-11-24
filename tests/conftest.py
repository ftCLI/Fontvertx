import os
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

FONTS_DIR = Path(__file__).parent / "fixtures" / "fonts"


@pytest.fixture(autouse=True)
def _isolated_log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep setup_logging (called by the CLI and the GUI entry point) away from
    # the real per-user log directory during tests.
    monkeypatch.setenv("FONTVERTX_LOG_DIR", str(tmp_path / "logs"))


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    # Same neutral base style as the real application entry point.
    app.setStyle("Fusion")
    return app


@pytest.fixture
def app_font(qapp: QApplication) -> Iterator[None]:
    """The application's real fonts (Inter UI, JetBrains Mono), as main() sets them."""
    from fontvertx.__main__ import _app_font, _mono_family

    original = qapp.font()
    qapp.setFont(_app_font())
    _mono_family()  # registers JetBrains Mono
    yield
    qapp.setFont(original)


@pytest.fixture
def qtbot_wait(qapp: QApplication) -> Callable[[Callable[[], bool], float], None]:
    def wait(condition: Callable[[], bool], timeout: float = 20.0) -> None:
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(10)
        poll.timeout.connect(lambda: loop.quit() if condition() else None)
        QTimer.singleShot(int(timeout * 1000), loop.quit)
        poll.start()
        if not condition():
            loop.exec()
        poll.stop()
        if not condition():
            raise TimeoutError("Condition not met in time")

    return wait


@pytest.fixture
def fonts_dir() -> Path:
    return FONTS_DIR


@pytest.fixture
def ttf_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.ttf"
    shutil.copy(FONTS_DIR / "IBMPlexSans-Regular.ttf", path)
    return path
