"""Builds the "Conversion profile" card: profile selector and per-profile options."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QGroupBox, QSizePolicy, QVBoxLayout

from fontvertx.gui.layout_manager import CARD_PADDING
from fontvertx.gui.profile_options import ProfileOptionsPanel
from fontvertx.gui.profiles import CONVERSION_GROUP_HEADINGS, CONVERSIONS
from fontvertx.gui.widgets import ConversionSelector, card_heading

if TYPE_CHECKING:
    from fontvertx.gui.window import ConverterWindow


def build_conversion_card(window: ConverterWindow) -> QGroupBox:
    window.conversion = ConversionSelector(
        CONVERSIONS, select_first=False, group_headings=CONVERSION_GROUP_HEADINGS
    )
    conversion_layout = QVBoxLayout()
    conversion_layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
    conversion_layout.addWidget(card_heading("Choose conversion", 2))
    conversion_layout.addSpacing(5)
    conversion_layout.addWidget(window.conversion)
    conversion_group = QGroupBox()
    conversion_group.setObjectName("card")
    conversion_group.setLayout(conversion_layout)
    conversion_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    window.profile_options = ProfileOptionsPanel()
    window.profile_options.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    window.conversion.currentIndexChanged.connect(window._apply_compatibility)
    window.conversion.currentIndexChanged.connect(lambda _index: window._on_conversion_changed())
    window.conversion.currentIndexChanged.connect(window._update_buttons)
    window.profile_options.compatibilityChanged.connect(window._apply_compatibility)
    window.profile_options.validityChanged.connect(window._update_buttons)
    window.profile_options.reset_button.clicked.connect(window._reset_active_profile_options)
    return conversion_group
