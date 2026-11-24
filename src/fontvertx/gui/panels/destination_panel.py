"""Builds the "Output" card: destination, overwrite, organization and save options."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from fontvertx.gui.layout_manager import CARD_PADDING
from fontvertx.gui.settings_store import OPTION_DEFAULTS
from fontvertx.gui.widgets import (
    ExamplePathLabel,
    KeyboardPushButton,
    card_heading,
    section_heading,
)

if TYPE_CHECKING:
    from fontvertx.gui.window import ConverterWindow


def build_destination_card(window: ConverterWindow) -> QGroupBox:
    w = window
    w.overwrite = QCheckBox("Overwrite existing files")
    w.overwrite.setObjectName("warnCheckbox")
    w.overwrite.setChecked(OPTION_DEFAULTS["overwrite"])
    w.overwrite.toggled.connect(w._update_buttons)
    for name in ("recalc_bboxes", "recalc_timestamp", "reorder_tables"):
        setattr(w, name, getattr(w.profile_options, name))
    w.organization_button = KeyboardPushButton("Organize output…")
    w.organization_button.setToolTip("Choose how converted fonts are grouped into folders.")
    w.organization_button.clicked.connect(w._show_organization_dialog)
    w.organization_button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    destination_group = QGroupBox()
    destination_group.setObjectName("card")
    destination_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    destination_layout = QVBoxLayout(destination_group)
    destination_layout.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
    destination_layout.setSpacing(9)
    destination_layout.addWidget(card_heading("Choose Output", 4))
    w.destination_source_radio = QRadioButton("Same as source")
    w.destination_folder_radio = QRadioButton("Folder")
    w.destination_source_radio.setChecked(True)
    w.destination_mode_group = QButtonGroup(w)
    w.destination_mode_group.addButton(w.destination_source_radio)
    w.destination_mode_group.addButton(w.destination_folder_radio)
    w.destination_edit = QLineEdit()
    w.destination_edit.setObjectName("destinationEdit")
    w.destination_edit.setReadOnly(True)
    w.destination_edit.setEnabled(False)
    w.destination_button = KeyboardPushButton("…")
    w.destination_button.setObjectName("stepperButton")
    w.destination_button.setToolTip("Choose output folder")
    w.destination_button.setEnabled(False)
    destination = QHBoxLayout()
    destination.setSpacing(8)
    destination.addWidget(w.destination_folder_radio)
    destination.addWidget(w.destination_edit, 1)
    destination.addWidget(w.destination_button)
    destination_layout.addWidget(w.destination_source_radio, 0, Qt.AlignmentFlag.AlignLeft)
    destination_layout.addLayout(destination)
    overwrite_panel = QFrame()
    w.overwrite_panel = overwrite_panel
    overwrite_panel.setObjectName("overwritePanel")
    overwrite_layout = QVBoxLayout(overwrite_panel)
    overwrite_layout.setContentsMargins(8, 6, 8, 6)
    overwrite_layout.setSpacing(3)
    overwrite_layout.addWidget(w.overwrite, 0, Qt.AlignmentFlag.AlignLeft)
    overwrite_hint = QLabel("Replaces files already in the output folder.")
    overwrite_hint.setObjectName("overwriteHint")
    overwrite_hint.setWordWrap(True)
    overwrite_hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    overwrite_hint.setFixedHeight(overwrite_hint.fontMetrics().lineSpacing() * 2)
    overwrite_layout.addWidget(overwrite_hint)
    destination_layout.addWidget(overwrite_panel)
    options_row = QHBoxLayout()
    options_row.setSpacing(9)
    options_row.addWidget(w.organization_button, 1)
    destination_layout.addLayout(options_row)
    w.organization_example = QWidget()
    example_layout = QVBoxLayout(w.organization_example)
    example_layout.setContentsMargins(0, 5, 0, 0)
    example_layout.setSpacing(6)
    example_layout.addWidget(section_heading("Example", "organizationSection"))
    w.organization_preview = ExamplePathLabel()
    example_layout.addWidget(w.organization_preview)
    w.organization_example.hide()
    destination_layout.addWidget(w.organization_example)
    for checkbox in (
        w.profile_options.use_target_upm,
        w.profile_options.format_woff,
        w.profile_options.format_woff2,
    ):
        checkbox.toggled.connect(w._update_organization_button)
    for spinbox in (
        w.profile_options.target_upm,
        w.profile_options.tolerance,
        w.profile_options.simplify,
    ):
        spinbox.valueChanged.connect(w._update_organization_button)
    return destination_group
