from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import QThread, Signal

from fontvertx.finder import iter_files
from fontvertx.inspection import inspect_font


class Source(NamedTuple):
    """A file or folder to list; folders are scanned into subfolders only if ``recursive``."""

    path: Path
    recursive: bool = False


class ScanWorker(QThread):
    """Lists the candidate files of the sources and reads their font metadata."""

    # (done, total); total is 0 while the files are still being listed.
    progress = Signal(int, int)
    font_found = Signal(object, object)
    failed = Signal(str)

    def __init__(self, sources: list[Source]) -> None:
        super().__init__()
        self.sources = sources

    def run(self) -> None:
        try:
            self._scan()
        except Exception as error:
            self.failed.emit(f"{type(error).__name__}: {error}")

    def _scan(self) -> None:
        self.progress.emit(0, 0)
        files: dict[Path, None] = {}
        for source in self.sources:
            for path in iter_files((source.path,), source.recursive):
                if self.isInterruptionRequested():
                    return
                files[path] = None
        total = len(files)
        self.progress.emit(0, total)
        for done, path in enumerate(files, start=1):
            if self.isInterruptionRequested():
                return
            info = inspect_font(path)
            if info is not None:
                self.font_found.emit(path, info)
            if done % 20 == 0 or done == total:
                self.progress.emit(done, total)
