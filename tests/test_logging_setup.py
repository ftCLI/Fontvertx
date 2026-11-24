import logging
import sys
from pathlib import Path

import pytest

from fontvertx.logging_setup import (
    LOG_FILE_NAME,
    PACKAGE_LOGGER_NAME,
    default_log_dir,
    font_logger,
    setup_logging,
)


@pytest.fixture
def package_logger() -> logging.Logger:
    logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    yield logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.setLevel(logging.NOTSET)


def test_default_log_dir_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FONTVERTX_LOG_DIR", str(tmp_path / "custom"))
    assert default_log_dir() == tmp_path / "custom"


def test_default_log_dir_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FONTVERTX_LOG_DIR", raising=False)
    path = default_log_dir()
    if sys.platform == "win32":
        assert path.name == "logs" and path.parent.name == "Fontvertx"
    elif sys.platform == "darwin":
        assert path == Path.home() / "Library" / "Logs" / "Fontvertx"
    else:
        assert path.name == "logs" and path.parent.name == "fontvertx"


def test_setup_logging_writes_records_to_file(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / LOG_FILE_NAME
    assert setup_logging(log_file=log_file) == log_file
    logging.getLogger("fontvertx.test").debug("debug message")
    content = log_file.read_text(encoding="utf-8")
    assert "debug message" in content
    assert "fontvertx.test" in content


def test_setup_logging_is_idempotent(tmp_path: Path, package_logger: logging.Logger) -> None:
    log_file = tmp_path / "logs" / LOG_FILE_NAME
    setup_logging(log_file=log_file)
    setup_logging(log_file=log_file, console_level="WARNING")
    assert len(package_logger.handlers) == 2
    logging.getLogger("fontvertx.test").info("once")
    assert log_file.read_text(encoding="utf-8").count("once") == 1


def test_setup_logging_console_handler_level(
    tmp_path: Path, package_logger: logging.Logger, capsys: pytest.CaptureFixture[str]
) -> None:
    setup_logging(log_file=tmp_path / LOG_FILE_NAME, console_level="WARNING")
    console = next(h for h in package_logger.handlers if type(h) is logging.StreamHandler)
    assert console.level == logging.WARNING
    logging.getLogger("fontvertx.test").info("hidden info")
    assert "hidden info" not in capsys.readouterr().err


def test_setup_logging_without_console(tmp_path: Path, package_logger: logging.Logger) -> None:
    setup_logging(log_file=tmp_path / LOG_FILE_NAME)
    assert all(type(handler) is not logging.StreamHandler for handler in package_logger.handlers)


def test_setup_logging_console_guard(tmp_path: Path, package_logger: logging.Logger) -> None:
    calls: list[bool] = []
    setup_logging(
        log_file=tmp_path / LOG_FILE_NAME,
        console_level="INFO",
        before_write=lambda: calls.append(True),
    )
    logging.getLogger("fontvertx.test").warning("guarded")
    assert calls == [True]


def test_setup_logging_unwritable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, package_logger: logging.Logger
) -> None:
    def raising(*args: object, **kwargs: object) -> None:
        raise OSError("denied")

    monkeypatch.setattr("fontvertx.logging_setup.RotatingFileHandler", raising)
    assert setup_logging(log_file=tmp_path / "logs" / LOG_FILE_NAME) is None
    # The logger still works (NullHandler) and does not raise.
    logging.getLogger("fontvertx.test").warning("no file")


def test_font_logger_prefixes_messages(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    log = font_logger(logging.getLogger("fontvertx.service"), "MyFont.ttf")
    with caplog.at_level(logging.INFO, logger="fontvertx.service"):
        log.info("Converting")
    assert "[MyFont.ttf] Converting" in caplog.text


def test_service_logs_with_font_context(ttf_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    from fontvertx.models import ConversionRequest, TtfToOtfOptions
    from fontvertx.service import ConverterService

    with caplog.at_level(logging.DEBUG, logger="fontvertx.service"):
        result = ConverterService().convert(ConversionRequest((ttf_path,), TtfToOtfOptions()))
    assert result.ok
    assert "[test.ttf] Converting" in caplog.text
    assert "[test.ttf] Converted in" in caplog.text
    assert "Finished ttf2otf conversion: 1 converted, 0 skipped, 0 failed" in caplog.text
