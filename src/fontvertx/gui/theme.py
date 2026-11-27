"""Light and dark theme: the app follows the system color scheme, also while it runs.

The palette is chosen before the window is built (``palette_for``), then
``follow_system_color_scheme`` applies a new one whenever the system scheme changes.
Most colors are read at paint time from ``colors()``, and icons hold palette tokens
resolved when drawn, so a switch only needs a new style sheet plus ``refresh_theme()``
on the widgets that fixed a color when they were created.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from fontvertx.gui import icons
from fontvertx.gui.styles import (
    DARK,
    LIGHT,
    Palette,
    clear_stylesheet_cache,
    set_palette,
    stylesheet,
)
from fontvertx.gui.tooltips import install_tooltip_theme


def palette_for(scheme: Qt.ColorScheme) -> Palette:
    """DARK for a dark system scheme; LIGHT otherwise (Unknown counts as light)."""
    return DARK if scheme == Qt.ColorScheme.Dark else LIGHT


def apply_palette(palette: Palette, window: QWidget | None) -> bool:
    """Switch the whole app to ``palette``; return whether anything changed.

    Order matters: the palette first (everything below reads it), then the caches built
    from the old one, the window's style sheet (its dialogs and the log window inherit
    it), the tooltip theme, and last the widgets that fixed a color at creation.
    """
    if not set_palette(palette):
        return False
    clear_stylesheet_cache()
    icons.clear_cache()
    if isinstance(window, QWidget) and isValid(window):
        window.setStyleSheet(stylesheet())
    app = QApplication.instance()
    if isinstance(app, QApplication):
        install_tooltip_theme(app)
        for widget in app.allWidgets():
            refresh = getattr(widget, "refresh_theme", None)
            if callable(refresh):
                refresh()
            widget.update()
    return True


def follow_system_color_scheme(
    app: QApplication, window: QWidget
) -> Callable[[Qt.ColorScheme], None]:
    """Apply the palette of the system scheme to ``window`` each time the scheme changes.

    Returns the connected slot (tests disconnect it).
    """

    def on_change(scheme: Qt.ColorScheme) -> None:
        if isinstance(window, QWidget) and isValid(window):
            apply_palette(palette_for(scheme), window)

    app.styleHints().colorSchemeChanged.connect(on_change)
    return on_change
