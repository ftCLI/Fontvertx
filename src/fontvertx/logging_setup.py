"""Centralized logging configuration for the fontvertx package.

Library modules only create loggers and emit records; this module is the
single place that attaches handlers. Both entry points (GUI and CLI) call
:func:`setup_logging` at startup:

- a rotating file handler in the per-user log directory captures everything
  down to DEBUG, so real-world conversion failures are diagnosable;
- an optional console handler on stderr shows records at the level chosen
  by the user (used by the CLI ``--log-level`` option).
"""

import logging
import os
import sys
from collections.abc import Callable, MutableMapping
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

PACKAGE_LOGGER_NAME = "fontvertx"
LOG_FILE_NAME = "fontvertx.log"
_LOG_FILE_MAX_BYTES = 1_000_000
_LOG_FILE_BACKUP_COUNT = 3
_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
# Marks handlers installed by setup_logging, so repeated calls replace them
# instead of stacking duplicates (and tests can reconfigure cleanly).
_MANAGED_ATTR = "_fontvertx_managed"


def default_log_dir() -> Path:
    """Return the per-user log directory for the current platform.

    The ``FONTVERTX_LOG_DIR`` environment variable overrides the location.
    """
    override = os.environ.get("FONTVERTX_LOG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
        return root / "Fontvertx" / "logs"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "Fontvertx"
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base) if base else Path.home() / ".local" / "state"
    return root / "fontvertx" / "logs"


class _GuardedStreamHandler(logging.StreamHandler):
    """Stream handler that runs a hook (e.g. closing a progress line) before writing."""

    def __init__(self, before_write: Callable[[], None]) -> None:
        super().__init__()
        self._before_write = before_write

    def emit(self, record: logging.LogRecord) -> None:
        self._before_write()
        super().emit(record)


def setup_logging(
    console_level: int | str | None = None,
    log_file: Path | None = None,
    file_level: int | str = logging.DEBUG,
    before_write: Callable[[], None] | None = None,
) -> Path | None:
    """Configure the package logger; return the log file path, or None if unusable.

    The logger itself captures everything (DEBUG); each handler applies its
    own level. Passing ``console_level`` adds a stderr handler at that level;
    ``before_write`` is a hook the console handler runs before each record
    (the CLI uses it to terminate the in-place progress line first).
    Existing managed handlers are replaced, so the function is idempotent.
    """
    logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    logger.setLevel(logging.DEBUG)
    # propagate stays True: records reach handlers attached higher up (e.g. the
    # GUI _LogBridge on the package logger, or pytest's caplog on the root
    # logger). No duplicates: handlers exist here, so the last-resort handler
    # is never used, and the application does not configure the root logger.

    for handler in list(logger.handlers):
        if getattr(handler, _MANAGED_ATTR, False):
            logger.removeHandler(handler)
            handler.close()

    formatter = logging.Formatter(_LOG_FORMAT)

    path = log_file if log_file is not None else default_log_dir() / LOG_FILE_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler: logging.Handler = RotatingFileHandler(
            path,
            maxBytes=_LOG_FILE_MAX_BYTES,
            backupCount=_LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        file_handler = logging.NullHandler()
    file_handler.setLevel(file_level)
    file_handler.setFormatter(formatter)
    setattr(file_handler, _MANAGED_ATTR, True)
    logger.addHandler(file_handler)
    installed_path = path if not isinstance(file_handler, logging.NullHandler) else None

    if console_level is not None:
        console_handler: logging.Handler = (
            _GuardedStreamHandler(before_write)
            if before_write is not None
            else logging.StreamHandler()
        )
        console_handler.setLevel(console_level)
        console_handler.setFormatter(formatter)
        setattr(console_handler, _MANAGED_ATTR, True)
        logger.addHandler(console_handler)

    return installed_path


class FontAdapter(logging.LoggerAdapter):
    """Logger adapter that prefixes messages with the current font name."""

    def process(
        self, msg: str, kwargs: MutableMapping[str, Any]
    ) -> tuple[str, MutableMapping[str, Any]]:
        font = self.extra["font"] if self.extra else "?"
        return f"[{font}] {msg}", kwargs


def font_logger(logger: logging.Logger, font_name: str) -> FontAdapter:
    """Return a logger that tags every record with the given font name."""
    return FontAdapter(logger, {"font": font_name})
