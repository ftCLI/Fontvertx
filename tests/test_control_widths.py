"""Checkboxes and radio buttons are only as wide as their indicator and text.

A control stretched across its card would show its tooltip over the empty space to
the right of the text, where clicks do nothing.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QCheckBox,
    QLabel,
    QRadioButton,
    QSizePolicy,
    QWidget,
)

from fontvertx.gui import window as window_module
from fontvertx.gui.layout_manager import BUTTON_PADDING_WIDE, LayoutManager
from fontvertx.gui.organization_dialog import OrganizationDialog
from fontvertx.gui.profiles import CONVERSIONS
from fontvertx.gui.window import ConverterWindow

Wait = Callable[[Callable[[], bool], float], None]

# Rounding of style metrics and text advances.
SLACK = 2
# Labels may also be a little wider than their text (word-wrap heuristics, margins).
LABEL_SLACK = 6


def _settle(qapp: QApplication) -> None:
    for _ in range(5):
        qapp.processEvents()


def _controls(root: QWidget) -> Iterator[QAbstractButton]:
    for cls in (QCheckBox, QRadioButton):
        for widget in root.findChildren(cls):
            if widget.isVisibleTo(root) and widget.toolTip():
                yield widget


def _too_wide(root: QWidget) -> list[str]:
    problems = [
        f"{widget.text()!r}: {widget.width()} > {widget.sizeHint().width()}"
        for widget in _controls(root)
        if widget.width() > widget.sizeHint().width() + SLACK
    ]
    problems += [
        f"label {label.text()!r}: {label.width()} > {label.sizeHint().width()}"
        for label in root.findChildren(QLabel)
        if label.isVisibleTo(root)
        and label.toolTip()
        # Labels that fill their row on purpose and elide (the example path) are exempt.
        and label.sizePolicy().horizontalPolicy() != QSizePolicy.Policy.Ignored
        and label.width() > label.sizeHint().width() + LABEL_SLACK
    ]
    return problems


@pytest.fixture
def win(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConverterWindow:
    ini = tmp_path / "settings.ini"
    monkeypatch.setattr(
        window_module,
        "QSettings",
        lambda: QSettings(str(ini), QSettings.Format.IniFormat),
    )
    return ConverterWindow()


@pytest.fixture
def scanned_win(
    win: ConverterWindow, tmp_path: Path, fonts_dir: Path, qtbot_wait: Wait
) -> ConverterWindow:
    # With fonts listed, the input toolbar (Select all, Hide incompatible) is shown.
    folder = tmp_path / "in"
    folder.mkdir()
    shutil.copy(fonts_dir / "IBMPlexSans-Regular.ttf", folder / "a.ttf")
    win._add_paths([str(folder / "a.ttf")])
    qtbot_wait(lambda: not win.file_list.scanning, 30.0)
    return win


@pytest.mark.parametrize("width", [1200, 900])
def test_controls_are_only_as_wide_as_their_text(
    app_font: None, scanned_win: ConverterWindow, qapp: QApplication, width: int
) -> None:
    win = scanned_win
    win.show()
    seen: set[str] = set()
    for conversion in CONVERSIONS:
        win.conversion.setCurrentIndex(win.conversion.findData(conversion))
        win.resize(width, 900)
        _settle(qapp)
        seen.update(widget.text() for widget in _controls(win))
        assert _too_wide(win) == [], conversion
    # The walk really reached the options card and the input toolbar.
    assert {"Recalculate bounding boxes", "Subroutinize", "Select all"} <= seen


def test_wrapped_controls_are_as_wide_as_their_longest_line(
    app_font: None, scanned_win: ConverterWindow, qapp: QApplication
) -> None:
    win = scanned_win
    win.show()
    # Web fonts has the most checkboxes, several with long labels.
    win.conversion.setCurrentIndex(win.conversion.findData("ft2wf"))
    win.resize(900, 900)
    _settle(qapp)
    controls = list(_controls(win))
    for widget in controls:
        LayoutManager.wrap_button_text(widget, widget.text(), 40, BUTTON_PADDING_WIDE)
    _settle(qapp)
    wrapped = [widget for widget in controls if "\n" in widget.text()]
    assert len(wrapped) >= 5
    for widget in wrapped:
        longest = max(
            widget.text().splitlines(),
            key=lambda line: widget.fontMetrics().horizontalAdvance(line),
        )
        # Same class, object name and parent, so the same stylesheet rules apply.
        reference = type(widget)(longest, widget.parentWidget())
        reference.setObjectName(widget.objectName())
        reference.ensurePolished()
        assert widget.width() <= reference.sizeHint().width() + SLACK, widget.text()
        reference.deleteLater()


def test_organization_dialog_controls_are_only_as_wide_as_their_text(
    app_font: None, qapp: QApplication
) -> None:
    dialog = OrganizationDialog(
        "ttf2otf", (("family",), ("format",)), {"family": "Family", "format": "OTF"}, ".otf"
    )
    dialog.show()
    _settle(qapp)
    assert _too_wide(dialog) == []
