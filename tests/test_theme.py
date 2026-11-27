from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPalette
from PySide6.QtWidgets import QApplication, QToolTip

from fontvertx.gui import theme
from fontvertx.gui import window as window_module
from fontvertx.gui.icons import material_icon
from fontvertx.gui.status_pill import StatusState
from fontvertx.gui.styles import DARK, LIGHT, colors, resolve_color, stylesheet
from fontvertx.gui.window import ConverterWindow


@pytest.fixture
def window(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[ConverterWindow]:
    ini = tmp_path / "s.ini"
    monkeypatch.setattr(
        window_module, "QSettings", lambda: QSettings(str(ini), QSettings.Format.IniFormat)
    )
    # Closed and deleted by the autouse cleanup in conftest.py.
    window = ConverterWindow()
    try:
        yield window
    finally:
        theme.apply_palette(LIGHT, window)


def _glyph_color(icon_pixmap_image: QImage) -> str:
    for y in range(icon_pixmap_image.height()):
        for x in range(icon_pixmap_image.width()):
            color = icon_pixmap_image.pixelColor(x, y)
            if color.alpha() == 255:
                return color.name()
    raise AssertionError("no opaque pixel in the icon")


def test_palette_follows_the_system_scheme() -> None:
    assert theme.palette_for(Qt.ColorScheme.Dark) is DARK
    assert theme.palette_for(Qt.ColorScheme.Light) is LIGHT
    assert theme.palette_for(Qt.ColorScheme.Unknown) is LIGHT


def test_applying_the_current_palette_does_nothing(window: ConverterWindow) -> None:
    sheet = window.styleSheet()
    assert theme.apply_palette(LIGHT, window) is False
    assert window.styleSheet() == sheet


def test_switch_restyles_the_window_and_tooltips(window: ConverterWindow) -> None:
    assert theme.apply_palette(DARK, window) is True
    assert colors() is DARK
    assert window.styleSheet() == stylesheet()
    assert DARK.page in window.styleSheet()
    assert LIGHT.page not in window.styleSheet()
    tip = QToolTip.palette()
    assert tip.color(QPalette.ColorRole.ToolTipBase).name() == DARK.tooltip_bg
    assert tip.color(QPalette.ColorRole.ToolTipText).name() == DARK.tooltip_text

    assert theme.apply_palette(LIGHT, window) is True
    assert window.styleSheet() == stylesheet()
    assert LIGHT.page in window.styleSheet()


def test_existing_icons_take_the_new_color(window: ConverterWindow) -> None:
    icon = material_icon("check", "text", disabled_color="text_disabled")
    size = QSize(24, 24)
    assert _glyph_color(icon.pixmap(size).toImage()) == LIGHT.text
    assert _glyph_color(icon.pixmap(size, QIcon.Mode.Disabled).toImage()) == LIGHT.text_disabled
    theme.apply_palette(DARK, window)
    assert _glyph_color(icon.pixmap(size).toImage()) == DARK.text
    assert _glyph_color(icon.pixmap(size, QIcon.Mode.Disabled).toImage()) == DARK.text_disabled


def test_icon_tokens_are_checked_when_created() -> None:
    with pytest.raises(ValueError, match="not_a_token"):
        material_icon("check", "not_a_token")
    assert resolve_color("#123456") == "#123456"


def test_example_path_is_rendered_again(window: ConverterWindow) -> None:
    label = window.organization_preview
    label.resize(400, 40)
    label.set_path("Family/Style/Font.otf")
    assert LIGHT.header_group in label.text()
    theme.apply_palette(DARK, window)
    assert DARK.header_group in label.text()
    assert LIGHT.header_group not in label.text()


def test_fixed_colors_are_refreshed(window: ConverterWindow) -> None:
    theme.apply_palette(DARK, window)
    placeholder = window.conversion.combo.palette().color(QPalette.ColorRole.PlaceholderText)
    assert placeholder.name() == DARK.placeholder
    assert DARK.warn_accent in window.profile_options.upm_warning_label.text()
    assert window.files.muted_color.name() == DARK.text_disabled


def test_paused_bar_switches_to_the_dark_amber(window: ConverterWindow) -> None:
    window.resize(1200, 600)
    window.show()
    window.converter.outcome.total = 4
    window.converter.progress_done = 2
    window.progress.setRange(0, 4)
    window.progress.setValue(2)
    window._set_run_status(StatusState.PAUSED)
    QApplication.processEvents()
    theme.apply_palette(DARK, window)
    QApplication.processEvents()
    bar = window.status_pill.progress
    image = bar.grab().toImage()
    fill = image.pixelColor(bar.width() // 8, 3).name()
    track = image.pixelColor(bar.width() * 7 // 8, 3).name()
    assert (fill, track) == (DARK.warn_border, DARK.warn_fill)


def test_scheme_change_signal_switches_the_theme(
    qapp: QApplication, window: ConverterWindow
) -> None:
    slot = theme.follow_system_color_scheme(qapp, window)
    hints = qapp.styleHints()
    try:
        hints.colorSchemeChanged.emit(Qt.ColorScheme.Dark)
        assert colors() is DARK
        assert DARK.page in window.styleSheet()
        hints.colorSchemeChanged.emit(Qt.ColorScheme.Unknown)
        assert colors() is LIGHT
    finally:
        hints.colorSchemeChanged.disconnect(slot)
