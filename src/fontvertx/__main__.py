import ctypes
import logging
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QStyleFactory

from fontvertx.gui.app_style import AppStyle
from fontvertx.gui.styles import MONO_FONT_FAMILY, UI_FONT_FAMILY, set_mono_family, ui_font
from fontvertx.gui.tooltips import install_tooltip_theme
from fontvertx.gui.window import ConverterWindow
from fontvertx.logging_setup import setup_logging

# Window icon sizes; 16 and 24 px are rendered from the small design
# (fontvertx-small.svg), 32 px and up from the large one (fontvertx.svg).
APP_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _app_icon() -> QIcon:
    assets = Path(__file__).parent / "assets"
    icon = QIcon()
    for size in APP_ICON_SIZES:
        png = assets / f"fontvertx-{size}.png"
        if png.is_file():
            icon.addFile(str(png), QSize(size, size))
    if icon.isNull():
        ico = assets / "fontvertx.ico"
        if ico.is_file():
            return QIcon(str(ico))
        logging.getLogger(__name__).warning("Application icon not found in %s", assets)
    return icon


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Fontvertx.Fontvertx")
    except (AttributeError, OSError) as error:
        logging.getLogger(__name__).warning("Could not set Windows application ID: %s", error)


def _app_font() -> QFont:
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    fonts = Path(__file__).parent / "assets" / "fonts" / "inter"
    for style in ("Regular", "Medium", "SemiBold", "Bold"):
        path = fonts / f"Inter-{style}.ttf"
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0 or UI_FONT_FAMILY not in QFontDatabase.applicationFontFamilies(font_id):
            logging.getLogger(__name__).warning(
                "Could not load UI font %s; using the system font", path
            )
            return font
    font = ui_font(font)  # UI family and features (styles.ui_font)
    font.setWeight(QFont.Weight.Medium)
    return font


def _mono_family() -> str:
    fallback = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    fonts = Path(__file__).parent / "assets" / "fonts" / "jetbrains_mono"
    for style in ("Regular", "Medium"):
        path = fonts / f"JetBrainsMono-{style}.ttf"
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0 or MONO_FONT_FAMILY not in QFontDatabase.applicationFontFamilies(font_id):
            logging.getLogger(__name__).warning(
                "Could not load monospaced font %s; using the system fixed font", path
            )
            return fallback
    return MONO_FONT_FAMILY


def main() -> int:
    log_file = setup_logging()
    logging.getLogger(__name__).info(
        "Starting Fontvertx (log file: %s)", log_file if log_file is not None else "unavailable"
    )
    _set_windows_app_id()
    app = QApplication(sys.argv)
    # Combo roll-out animation paints an opaque copy of the rounded popup: black corners on Windows.
    app.setEffectEnabled(Qt.UIEffect.UI_AnimateCombo, False)
    # Neutral cross-platform base style; the application stylesheet sits on top.
    app.setStyle(AppStyle(QStyleFactory.create("Fusion")))
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    app.setOrganizationName("Fontvertx")
    app.setApplicationName("Fontvertx")
    app.setWindowIcon(_app_icon())
    app.setFont(_app_font())
    set_mono_family(_mono_family())
    install_tooltip_theme(app)
    window = ConverterWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
