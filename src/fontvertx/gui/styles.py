"""Colors and Qt style sheet for the Fontvertx window ("Morbido" light theme)."""

import logging
import os
import tempfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from string import Template

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QFont

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Palette:
    page: str
    surface: str
    field: str
    field_hover: str
    list_bg: str
    list_alt: str
    button: str
    button_hover: str
    button_pressed: str
    disabled_bg: str
    border: str
    border_strong: str
    border_hover: str
    indicator_border: str
    accent: str
    accent_tint: str
    accent_tint_hover: str
    accent_hover: str
    control_border_off: str
    control_border_hover: str
    text: str
    text_title: str
    text_secondary: str
    text_muted: str
    text_disabled: str
    primary: str
    primary_hover: str
    on_primary: str
    primary_disabled: str
    primary_disabled_text: str
    footer_disabled_bg: str
    accent_text: str
    selection_bg: str
    selection_text: str
    text_selection_bg: str
    tree_selection_bg: str
    progress_track: str
    danger: str
    warning: str
    success: str
    primary_tint_bg: str
    primary_tint_fg: str
    running_track: str
    example_selection: str
    success_bg: str
    success_fg: str
    success_border: str
    success_btn_border: str
    success_icon: str
    step_check: str
    warn_bg: str
    warn_fill: str
    warn_border: str
    warn_fg: str
    warn_accent: str
    badge_bg: str
    badge_muted: str
    table_header: str
    danger_bg: str
    danger_border: str
    zebra: str
    row_hover: str
    row_selected_a: str
    row_separator: str
    row_selection: str
    row_selection_inactive: str
    accent_border_soft: str
    control_border_strong: str
    accent_pressed: str
    import_disabled_bg: str
    import_disabled_border: str
    import_disabled_text: str
    import_disabled_icon: str
    placeholder: str
    text_dim: str
    fill_dim: str
    border_dim: str
    checkbox_disabled_border: str
    border_faint: str
    badge_idle_border: str
    convert_disabled_text: str
    warn_panel_bg: str
    warn_panel_border: str
    popup_border: str
    header_group: str
    slate: str
    ghost_hover: str
    ghost_pressed: str
    icon_disabled: str
    path_text: str
    scroll_handle: str
    scroll_handle_hover: str
    scroll_handle_pressed: str
    tooltip_bg: str
    tooltip_text: str
    dropzone_bg: str
    dropzone_bg_active: str
    dropzone_glyph: str
    dropzone_glyph_active: str


# "Morbido": white cards with a hairline border on a cool grey page, borderless
# rounded fields, plum accent.
LIGHT = Palette(
    page="#edf1f6",
    surface="#ffffff",
    field="#edf1f6",
    field_hover="#e5eaf1",
    list_bg="#ffffff",
    list_alt="#f6f8fb",
    button="#eff2f7",
    button_hover="#e5eaf1",
    button_pressed="#dce2ec",
    disabled_bg="#f2f4f8",
    border="#e1e6ee",
    border_strong="#d0d8e4",
    border_hover="#b3bccb",
    indicator_border="#8a8fa6",
    accent="#2f5da8",
    accent_tint="#e6ecf5",
    accent_tint_hover="#dae2ef",
    accent_hover="#4870b2",
    control_border_off="#8a8fa6",
    control_border_hover="#626678",
    text="#1e2030",
    text_title="#1e2030",
    text_secondary="#1e2030",
    text_muted="#626678",
    text_disabled="#a3a7ba",
    primary="#2f5da8",
    primary_hover="#4870b2",
    on_primary="#ffffff",
    primary_disabled="#b9c8e2",
    primary_disabled_text="#ffffff",
    footer_disabled_bg="#e2e8f3",
    accent_text="#2f5da8",
    selection_bg="#e6ecf5",
    selection_text="#1e2030",
    text_selection_bg="#cbd6e9",
    tree_selection_bg="#e6ecf5",
    progress_track="#e1e6ee",
    danger="#8f1d24",
    warning="#6b4200",
    success="#14633a",
    primary_tint_bg="#e6ecf5",
    primary_tint_fg="#2f5da8",
    running_track="#cbd6e9",
    example_selection="#cbd6e9",
    success_bg="#e3f4ea",
    success_fg="#14633a",
    success_border="#bfe3ce",
    success_btn_border="#8cc9a6",
    success_icon="#1f7a4d",
    step_check="#1f7a4d",  # completed-step badge check
    warn_bg="#fff3dc",
    warn_fill="#fbe3b5",
    warn_border="#d9962e",
    warn_fg="#7a4b00",
    warn_accent="#b45309",
    badge_bg="#e5eaf1",
    badge_muted="#f2f4f8",
    table_header="#eff2f7",
    danger_bg="#fce8e6",
    danger_border="#d7827e",
    zebra="#f2f4f8",
    row_hover="#f4f6fa",
    row_selected_a="#e6ecf5",
    row_separator="#e1e6ee",
    row_selection="#e6ecf5",
    row_selection_inactive="#eff2f7",
    accent_border_soft="#b9c8e2",
    control_border_strong="#a3a7ba",
    accent_pressed="#264a86",
    import_disabled_bg="#f2f4f8",
    import_disabled_border="#f2f4f8",
    import_disabled_text="#a3a7ba",
    import_disabled_icon="#a3a7ba",
    placeholder="#626678",
    text_dim="#626678",
    fill_dim="#e1e6ee",
    border_dim="#b3bccb",
    checkbox_disabled_border="#c8cfdb",
    border_faint="#e1e6ee",
    badge_idle_border="#e1e6ee",
    convert_disabled_text="#6d8ec2",
    warn_panel_bg="#fff7e6",  # active "Overwrite existing files" card
    warn_panel_border="#ebcb8b",
    popup_border="#d0d8e4",
    header_group="#626678",
    slate="#1e2030",
    ghost_hover="#eff2f7",
    ghost_pressed="#e5eaf1",
    icon_disabled="#a3a7ba",
    path_text="#1e2030",
    scroll_handle="#c8cfdb",
    scroll_handle_hover="#aab4c4",
    scroll_handle_pressed="#95a1b5",
    tooltip_bg="#1e2030",
    tooltip_text="#ffffff",
    dropzone_bg="#fafbfd",  # empty drop zone
    dropzone_bg_active="#e6ecf5",  # while files are dragged over it
    dropzone_glyph="#d5dce7",  # its decorative "Aa"
    dropzone_glyph_active="#b7c6dd",
)

# Corner radius scale: the radius grows with the size of the element.
RADIUS_SM = "5px"  # checkboxes, table badges, row actions, small indicators
RADIUS_MD = "10px"  # buttons, fields, closed combos, popup items, tooltips
RADIUS_LG = "10px"  # inner containers: Overwrite box, dashed boxes
RADIUS_XL = "14px"  # cards, dropdown popup, dialog cards
RADIUS_FOOTER = "16px"  # footer card
# Round elements: FULL is half the element's height, so it is given per element.
RADIUS_FULL_RADIO = "8px"  # 16px indicator
RADIUS_FULL_BADGE = "12px"  # 24px step badge
# Chips are ~19px tall (11px mono + 2px padding). Qt ignores a radius larger than half
# the element instead of clamping it, so the pill radius is explicit.
RADIUS_FULL_CHIP = "9px"
RADIUS_FULL_BAR = "3px"  # 6px scan progress bar
RADIUS_PILL = "22px"  # 44px Convert button
RADIUS_ROUND = "19px"  # 38px Pause / Cancel and round icon buttons
RADIUS_STATUS_CHIP = "12px"  # 24px outcome chip
SCAN_LABEL_PIXEL_SIZE = 12
# The focus ring is the element radius + 2px.
RADIUS_SM_FOCUS = "7px"
ITEM_PADDING_LEFT = 16  # left padding of table / tree cells
# Qt insets cell text by a further text margin (focus-frame margin + 1) that header
# labels do not get: a header aligned with cell text adds it to its padding.
ITEM_TEXT_MARGIN = 3

# Fixed control heights (pixels, border included).
FIELD_HEIGHT = 36  # line edits, spin boxes, combos, path field, stepper buttons
BUTTON_HEIGHT = 32  # secondary buttons
FOOTER_HEIGHT = 44  # footer blocks: status pill and Convert pill
CONVERT_HEIGHT = FOOTER_HEIGHT
FIELD_BORDER = 2  # transparent until focused, so focusing never shifts the text
FOOTER_GAP = 20  # window background beside and below the footer card
FOOTER_CARD_HEIGHT = 68  # footer card, border included
FOOTER_CARD_BORDER = 1
FOOTER_PAD_LEFT = 20  # inner padding of the footer card (border included)
FOOTER_PAD_RIGHT = 12  # same as top and bottom: the pill is evenly inset
FOOTER_PAD_V = 12  # (68 - 44) / 2: Convert is vertically centered
CONVERT_PADDING_H = 24  # Convert's horizontal padding around icon + label
CONVERT_WEIGHT = 600  # Convert's label (independent of the footer status text)
FOOTER_STATUS_WEIGHT = 500  # footer status text on the left
FOOTER_STATUS_SIZE = "10.125pt"  # 13.5px: Qt keeps pixel sizes whole
INDICATOR_SIZE = 16  # checkbox / radio indicator, border included
INDICATOR_BORDER = 1.5

_ASSETS = Path(__file__).parent.parent / "assets"
_INDICATOR_DIR = _ASSETS / "indicators"  # white marks drawn on accent fills
_MATERIAL_DIR = _ASSETS / "icons"


def radius_px(value: str) -> int:
    """Radius token as an int, for painter code."""
    return int(value.removesuffix("px"))


# Inter is the UI font; JetBrains Mono for paths, the conversion log, counters, step
# badges and chips.
UI_FONT_FAMILY = "Inter"
MONO_FONT_FAMILY = "JetBrains Mono"
_mono_family = MONO_FONT_FAMILY
MONO_POINT_SIZE = 9.0
CHIP_PIXEL_SIZE = 11


def set_mono_family(family: str) -> None:
    """Override the monospaced family (system fallback when the bundled one fails to load)."""
    global _mono_family
    _mono_family = family
    stylesheet.cache_clear()


def mono_family() -> str:
    return _mono_family


def mono_font() -> QFont:
    font = QFont(_mono_family)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSizeF(MONO_POINT_SIZE)
    return font


def chip_font() -> QFont:
    """Monospaced font of counters, step badges and chips."""
    font = mono_font()
    font.setPixelSize(CHIP_PIXEL_SIZE)
    font.setWeight(QFont.Weight.Medium)
    return font


# OpenType features of every UI font: ss02 is Inter's disambiguation set (slashed zero,
# distinct I / l); tnum (tabular figures) is added where digits must line up.
UI_FONT_FEATURES = {"ss02": 1}
TABULAR_FONT_FEATURES = {"tnum": 1}


def ui_font(base: QFont | None = None, *, tabular: bool = False) -> QFont:
    """The UI font: a copy of ``base`` (default: the application font) in the UI family,
    with the UI features, plus tabular figures when ``tabular``.

    The single place UI fonts get their features: copies made in delegates or resolved
    from the stylesheet keep them only if they start from here.
    """
    font = QFont(base) if base is not None else QFont()
    font.setFamily(UI_FONT_FAMILY)
    features = {**UI_FONT_FEATURES, **(TABULAR_FONT_FEATURES if tabular else {})}
    for tag, value in features.items():
        font.setFeature(QFont.Tag.fromString(tag), value)
    return font


def tabular_font(base: QFont | None = None) -> QFont:
    """UI font with tabular figures (numbers, counts, axis values)."""
    return ui_font(base, tabular=True)


_TEMPLATE = Template("""
QMainWindow, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget, QDialog {
    background: $page;
    color: $text;
    font-family: "$ui_font_family";
    font-size: 10pt;
}
QDialog, QMessageBox {
    background: $surface;
}
QMessageBox QLabel {
    color: $text;
    background: transparent;
}
QLabel, QRadioButton, QCheckBox {
    color: $text_secondary;
}
QLabel#hint {
    color: $text_muted;
}
QLabel#dropZoneTitle {
    color: $text;
    font-size: 22px;
    font-weight: 600;
}
QLabel#dropZoneGlyph {
    color: $dropzone_glyph;
}
QFrame#dropZone[dragOver="true"] QLabel#dropZoneGlyph {
    color: $dropzone_glyph_active;
}
QFrame#dropZone QLabel#formatChip {
    font-size: 10px;
    padding: 3px 8px;  /* 19px tall: the 9px pill radius still fits (half height) */
}
QLabel#formatChip {
    color: $accent;
    background: $accent_tint;
    border: none;
    border-radius: $radius_full_chip;
    padding: 2px 8px;
    font-family: "$mono_family", monospace;
    font-size: ${chip_px}px;
    font-weight: 500;
}
QLabel#conversionGroupHeading {
    color: $accent_text;
    font-size: 9pt;
    font-weight: 400;
}
QPushButton#iconButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: $radius_md;
}
QLabel#warningHint {
    color: $warning;
}
QLabel#stepLabel {
    color: $text_secondary;
    font-weight: 600;
}
QLabel#stepHint, QLabel#statusLabel {
    color: $text_muted;
}
QLabel#statusLabel {
    font-weight: 600;
}
QLabel#stepHint[mono="true"] {
    color: $text_muted;
    font-family: "$mono_family", monospace;
    font-size: ${scan_label_px}px;
    font-weight: 500;
}
QLabel#statusLabel[state="warning"] {
    color: $warning;
}
QLabel#statusLabel[state="success"] {
    color: $success;
}
QLabel#statusLabel[state="error"] {
    color: $danger;
}
QLabel#statusLabel[footerStatus="true"] {
    background: transparent;
    border: none;
    padding: 0;
    font-size: $footer_status_size;
    font-weight: $footer_status_weight;
}
QLabel#statusLabel[footerStatus="true"][state="success"] {
    color: $success_icon;
}
QLabel#statusLabel[footerStatus="true"][state="warning"] {
    color: $warn_fg;
}
QLabel#statusLabel[footerStatus="true"][state="error"] {
    color: $danger;
}
QLabel#statusLabel[footerStatus="true"][state="running"] {
    color: $primary_tint_fg;
}
QLabel#runTitle {
    color: $text;
    font-size: $footer_status_size;
    font-weight: 600;
}
QLabel#runTitle[state="warning"] {
    color: $warn_fg;
}
QLabel#runCounter {
    color: $text;
    font-family: "$mono_family", monospace;
    font-size: 13px;
    font-weight: 500;
}
QLabel#runFile {
    color: $text_muted;
    font-family: "$mono_family", monospace;
    font-size: 12px;
}
QWidget#resultCounts {
    color: $text;
    font-size: $footer_status_size;
    font-weight: $footer_status_weight;
}
QFrame#statusChip {
    background: $slate;
    border: none;
    border-radius: $radius_status_chip;
}
QFrame#statusChip[tone="success"] { background: $success_icon; }
QFrame#statusChip[tone="error"] { background: $danger; }
QFrame#statusChip[tone="warning"] { background: $warn_accent; }
QFrame#statusChip[tone="running"] { background: $accent; }
QLabel#statusChipText {
    color: $on_primary;
    background: transparent;
    font-size: 12px;
    font-weight: 600;
}
QLabel#logWindowTitle {
    color: $text_title;
    font-size: 15px;
    font-weight: 600;
}
QWidget#logWindowSummary {
    color: $text_muted;
    font-size: 13px;
}
QPushButton[runAction="true"] {
    background: $surface;
    border: 1px solid $border_strong;
    border-radius: $radius_round;
    color: $text;
    min-height: 36px;
    max-height: 36px;
    padding: 0 14px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton[runAction="true"]:hover:enabled {
    background: $button_hover;
}
QPushButton[runAction="true"]:pressed:enabled {
    background: $button_pressed;
}
QPushButton[runAction="true"]:focus {
    border-color: $accent;
}
QPushButton[runAction="true"]:disabled {
    background: $disabled_bg;
    border-color: $border;
    color: $text_disabled;
}
QPushButton[runAction="true"][runPrimary="true"] {
    background: $primary;
    border-color: $primary;
    color: $on_primary;
}
QPushButton[runAction="true"][runPrimary="true"]:hover:enabled {
    background: $primary_hover;
    border-color: $primary_hover;
}
QPushButton[runAction="true"][runPrimary="true"]:pressed:enabled {
    background: $accent_pressed;
    border-color: $accent_pressed;
}
QPushButton[runAction="true"][runPrimary="true"]:focus {
    border-color: $accent_pressed;
}
QPushButton[conversionButton="true"] {
    min-height: ${button_content}px;
    padding: 0 11px;
    font-size: 13px;
    font-weight: 500;
    border-radius: $radius_md;
}
QPushButton[conversionButton="true"]:focus,
QPushButton[conversionButton="true"]:focus:hover {
    border-color: transparent;
}
QPushButton[conversionButton="true"][keyboardFocus="true"]:focus,
QPushButton[conversionButton="true"][keyboardFocus="true"]:focus:hover {
    border-color: $accent;
}
QPushButton[conversionButton="true"]:disabled {
    background: $zebra;
    border-color: transparent;
    color: $text_disabled;
}
QLabel#statusLabel[footerStatus="true"][state="neutral"] {
    color: $slate;
}
QWidget#resultPanel QPushButton[resultAction="true"] {
    background: $surface;
    border: 1px solid $success_btn_border;
    border-radius: $radius_md;
    color: $success_icon;
    min-height: 30px;
    max-height: 30px;
    padding: 0 12px;
    font-size: 13px;
    font-weight: 600;
}
QWidget#resultPanel QPushButton[resultAction="true"]:hover:enabled {
    background: $success_bg;
}
QWidget#resultPanel QPushButton[resultAction="true"]:pressed:enabled {
    background: $badge_bg;
}
QWidget#resultPanel[state="warning"] QPushButton[resultAction="true"] {
    border-color: $warn_border;
    color: $warn_fg;
}
QWidget#resultPanel[state="warning"] QPushButton[resultAction="true"]:hover:enabled {
    background: $warn_bg;
}
QWidget#resultPanel[state="error"] QPushButton[resultAction="true"],
QWidget#resultPanel[state="running"] QPushButton[resultAction="true"],
QWidget#resultPanel[state="neutral"] QPushButton[resultAction="true"] {
    border-color: $control_border_strong;
    color: $slate;
}
QWidget#resultPanel[state="error"] QPushButton[resultAction="true"]:hover:enabled,
QWidget#resultPanel[state="running"] QPushButton[resultAction="true"]:hover:enabled,
QWidget#resultPanel[state="neutral"] QPushButton[resultAction="true"]:hover:enabled {
    background: $button_hover;
}
QWidget#resultPanel QPushButton[resultAction="true"][danger="true"] {
    border-color: $danger;
    color: $danger;
}
QWidget#resultPanel QPushButton[resultAction="true"][danger="true"]:hover:enabled {
    background: $danger_bg;
}
QWidget#resultPanel QPushButton[resultAction="true"][iconOnly="true"] {
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
    padding: 0;
    border-radius: $radius_round;
}
QWidget#resultPanel QPushButton[resultAction="true"]:disabled {
    border-color: $border;
    color: $text_disabled;
}
QWidget#resultPanel QPushButton[pillClose="true"] {
    background: transparent;
    border: none;
    padding: 0;
}
QFrame#footerCard {
    background: $surface;
    border: ${footer_border}px solid $border;
    border-radius: $radius_footer;
}
QFrame#footerCard[tone="running"] {
    background: $accent_tint;
    border-color: $running_track;
}
QFrame#footerCard[tone="success"] {
    background: $success_bg;
    border-color: $success_border;
}
QFrame#footerCard[tone="warning"] {
    background: $warn_bg;
    border-color: $warn_border;
}
QFrame#footerCard[tone="error"] {
    background: $danger_bg;
    border-color: $danger_border;
}
QFrame#footerCard[tone="neutral"] {
    background: $ghost_hover;
}
QLabel#footerSummary {
    color: $text_muted;
    font-size: $footer_status_size;
    font-weight: $footer_status_weight;
}
QPushButton#footerHistory {
    color: $accent;
    background: transparent;
    border: none;
    padding: 0;
    font-size: 13px;
    font-weight: 500;
}
QPushButton#footerHistory:hover {
    text-decoration: underline;
}
QLabel#pathLabel {
    color: $text;
    background: $field;
    border: none;
    border-radius: $radius_md;
    padding: 0 12px;
    min-height: ${field_height}px;
    max-height: ${field_height}px;
    font-family: "$mono_family", monospace;
    font-size: 9pt;
    font-weight: 400;
}
QLabel#filenamePreview {
    color: $text_muted;
    font-family: "$mono_family", monospace;
    font-size: 9pt;
}
QLineEdit#destinationEdit {
    font-family: "$mono_family", monospace;
    font-size: 9pt;
}
QListWidget#conversionLog {
    background: $surface;
    border: 1px solid $border;
    border-radius: 0;
    padding: 0;
    font-family: "$mono_family", monospace;
    font-size: 12px;
}
QListWidget#conversionLog::item {
    padding: 0;
    border: none;
    border-radius: 0;
}
QWidget#conversionLogCorner {
    background: $surface;
}
QLabel#organizationIntro {
    color: $text_secondary;
    font-size: 10.5pt;
}
QLabel#organizationSection {
    color: $header_group;
    font-size: 11px;
    font-weight: 600;
}
QLabel#exampleHint {
    color: $header_group;
    font-size: 12.5px;
}
QLabel#examplePath {
    color: $text;
    background: $primary_tint_bg;
    border: none;
    border-radius: $radius_lg;
    padding: 9px 12px;
    selection-background-color: $example_selection;
    selection-color: $text;
}
QLabel#examplePath[previewContext="dialog"] {
    background: $field;
    selection-background-color: $text_selection_bg;
}
QLabel#organizationLevelNumber,
QLabel#cardNumber {
    color: $accent;
    background: $accent_tint;
    border: none;
    border-radius: $radius_full_badge;
    min-width: 24px;
    max-width: 24px;
    min-height: 24px;
    max-height: 24px;
    padding: 0;
    qproperty-alignment: AlignCenter;
    font-family: "$mono_family", monospace;
    font-size: ${chip_px}px;
    font-weight: 500;
}
QLabel#cardNumber[state="invalid"] {
    color: $warn_fg;
    background: $warn_bg;
    font-weight: 700;
}
QLabel#cardNumber[state="valid"] {
    color: $success_icon;
    background: $success_bg;
    font-weight: 700;
}
QLabel#cardNumber[state="muted"] {
    color: $text_muted;
    background: $badge_muted;
}
QLabel#modifiedChip {
    color: $accent;
    background: $accent_tint;
    border: none;
    border-radius: $radius_full_chip;
    padding: 2px 8px;
    font-family: "$mono_family", monospace;
    font-size: ${chip_px}px;
    font-weight: 500;
}
QWidget#overwritePanel {
    background: $surface;
    border: 1px solid $border_faint;
    border-radius: $radius_lg;
    padding: 7px 9px;
}
QWidget#overwritePanel[active="true"] {
    background: $warn_panel_bg;
    border-color: $warn_panel_border;
}
QWidget#overwritePanel QCheckBox {
    color: $text;
}
QWidget#overwritePanel[active="true"] QCheckBox {
    color: $warning;
}
QLabel#overwriteHint {
    color: $text_muted;
    font-size: 9pt;
}
QWidget#overwritePanel[active="true"] QLabel#overwriteHint {
    color: $warn_fg;
}
QLabel#optionsEmptyTitle {
    color: $text;
    font-size: 10.125pt;  /* 13.5px: Qt keeps pixel sizes whole */
    font-weight: 600;
}
QLabel#optionsEmptyBody {
    color: $text_muted;
    font-size: 12px;
}
QGroupBox#card[optionsState="empty"] {
    border-color: $border;
}
QGroupBox#card[optionsState="empty"] QLabel#cardHeading {
    color: $text_dim;
}
QGroupBox#card[optionsState="empty"] QLabel#cardNumber {
    color: $text_muted;
    background: $badge_muted;
}
QLabel#upmWarning {
    color: $warn_fg;
    font-size: 12px;
    font-weight: 500;
}
QLabel#statusLabel[reason="true"] {
    color: $text_muted;
    font-size: 14px;
    font-weight: 500;
}
QFrame#organizationLevel {
    background: $surface;
    border: 1px solid $border;
    border-radius: $radius_xl;
}
QPushButton#organizationIconButton,
QPushButton#organizationRemoveCriterionButton,
QPushButton#organizationRemoveButton,
QPushButton#organizationAddCriterionButton {
    color: $slate;
    background: transparent;
    border: none;
    border-radius: $radius_md;
    padding: 0;
    font-weight: 500;
}
QPushButton#organizationRemoveButton,
QPushButton#organizationAddCriterionButton {
    min-height: 30px;
    max-height: 30px;
    padding: 0 8px;
}
QPushButton#organizationIconButton:hover:enabled,
QPushButton#organizationRemoveCriterionButton:hover:enabled,
QPushButton#organizationRemoveButton:hover:enabled,
QPushButton#organizationAddCriterionButton:hover:enabled {
    background: $ghost_hover;
}
QPushButton#organizationIconButton:pressed:enabled,
QPushButton#organizationRemoveCriterionButton:pressed:enabled,
QPushButton#organizationRemoveButton:pressed:enabled,
QPushButton#organizationAddCriterionButton:pressed:enabled {
    background: $ghost_pressed;
}
QPushButton#organizationIconButton:disabled,
QPushButton#organizationRemoveCriterionButton:disabled,
QPushButton#organizationRemoveButton:disabled,
QPushButton#organizationAddCriterionButton:disabled {
    color: $icon_disabled;
    background: transparent;
}
QPushButton#organizationAddButton,
QDialogButtonBox#organizationButtons QPushButton {
    color: $text;
    background: $button;
    border: 2px solid transparent;
    border-radius: $radius_md;
    min-height: ${button_content}px;
    max-height: ${button_content}px;
    padding: 0 13px;
    font-weight: 500;
}
QPushButton#organizationAddButton:hover:enabled,
QDialogButtonBox#organizationButtons QPushButton:hover:enabled {
    background: $button_hover;
}
QPushButton#organizationAddButton:pressed:enabled,
QDialogButtonBox#organizationButtons QPushButton:pressed:enabled {
    background: $button_pressed;
}
QPushButton#organizationAddButton:focus,
QDialogButtonBox#organizationButtons QPushButton:focus {
    border-color: $accent;
}
QPushButton#organizationAddButton:disabled,
QDialogButtonBox#organizationButtons QPushButton:disabled {
    color: $import_disabled_text;
    background: $import_disabled_bg;
    border-color: transparent;
}
QDialogButtonBox#organizationButtons QPushButton#primaryButton {
    color: $on_primary;
    background: $primary;
    font-weight: 600;
}
QDialogButtonBox#organizationButtons QPushButton#primaryButton:hover:enabled {
    background: $primary_hover;
}
QDialogButtonBox#organizationButtons QPushButton#primaryButton:pressed:enabled {
    background: $accent_pressed;
}
QDialogButtonBox#organizationButtons QPushButton#primaryButton:focus {
    border-color: $accent_pressed;
}
QPushButton#ghostButton {
    color: $text;
    background: transparent;
    padding: 0 9px;
}
QPushButton#ghostButton:hover:enabled, QPushButton#quietIconButton:hover:enabled {
    background: $ghost_hover;
}
QPushButton#ghostButton:pressed:enabled, QPushButton#quietIconButton:pressed:enabled {
    background: $ghost_pressed;
}
QPushButton#ghostButton:disabled, QPushButton#quietIconButton:disabled {
    color: $text_disabled;
    background: transparent;
}
QPushButton#quietIconButton {
    background: transparent;
    border: 2px solid transparent;
    border-radius: $radius_md;
    padding: 0;
}
QPushButton#quietIconButton:focus, QPushButton#quietIconButton:focus:hover {
    border-color: $accent;
}
QGroupBox#card {
    background: $surface;
    border: 1px solid $border;
    border-radius: $radius_xl;
    color: $text;
}
QLabel#cardHeading {
    color: $text;
    font-size: 15px;
    font-weight: 600;
}
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
    background: $field;
    color: $text;
    border: ${field_border}px solid transparent;
    border-radius: $radius_md;
    padding: 0 10px;
    min-height: ${field_content}px;
    max-height: ${field_content}px;
    selection-background-color: $text_selection_bg;
    selection-color: $selection_text;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    border: none;
    width: 30px;
}
QComboBox::down-arrow {
    image: $combo_down_icon;
    width: 17px;
    height: 17px;
}
QComboBox {
    combobox-popup: 0;
    combobox-maxVisibleItems: 12;
    font-weight: 500;
}
QComboBox:hover:enabled, QSpinBox:hover:enabled, QDoubleSpinBox:hover:enabled,
QLineEdit:hover:enabled {
    background: $field_hover;
}
QComboBox:on {
    border-color: $accent;
}
QComboBox::down-arrow:on {
    image: $combo_up_icon;
}
QComboBox:disabled {
    background: $import_disabled_bg;
    color: $import_disabled_text;
}
QComboBoxPrivateContainer {
    background: transparent;
    border: none;
}
QComboBox QAbstractItemView {
    background: $surface;
    color: $text;
    border: 1px solid $popup_border;
    border-radius: $radius_xl;
    padding: 4px;
    outline: 0;
    selection-background-color: $accent_tint;
    selection-color: $text;
}
QMenu {
    background: $surface;
    color: $text;
    border: 1px solid $popup_border;
    padding: 4px;
}
QMenu::item {
    padding: 5px 24px 5px 28px;
}
QMenu::item:selected {
    background: $selection_bg;
    color: $selection_text;
}
QMenu::item:disabled {
    color: $text_disabled;
}
QMenu::separator {
    height: 1px;
    background: $border;
    margin: 4px 8px;
}
QMenu::indicator {
    width: 14px;
    height: 14px;
}
QComboBox QAbstractItemView::item:disabled {
    color: $text_disabled;
    background: $disabled_bg;
}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    width: 0px;
    border: none;
}
QLineEdit:disabled,
QSpinBox:disabled,
QDoubleSpinBox:disabled {
    background: $disabled_bg;
    color: $text_disabled;
}
QPushButton {
    background: $button;
    color: $text;
    border: 2px solid transparent;
    border-radius: $radius_md;
    padding: 0 12px;
    min-height: ${button_content}px;
    font-weight: 500;
}
QPushButton:hover {
    background: $button_hover;
}
QPushButton:pressed {
    background: $button_pressed;
}
QPushButton:disabled {
    color: $text_disabled;
    background: $disabled_bg;
}
QPushButton:focus, QPushButton:focus:hover {
    border-color: $accent;
}
QPushButton#importButton {
    background: $button;
    color: $text;
    border: 2px solid transparent;
    border-radius: $radius_md;
    padding: 0 9px;
    font-weight: 500;
}
QPushButton#importButton::menu-indicator {
    width: 0;
    height: 0;
}
QPushButton#importButton:hover:enabled {
    background: $button_hover;
}
QPushButton#importButton:pressed:enabled, QPushButton#importButton:open {
    background: $button_pressed;
}
QPushButton#importButton[emphasis="true"] {
    background: $accent_tint;
    color: $accent;
    font-weight: 600;
}
QPushButton#importButton[emphasis="true"]:hover:enabled {
    background: $accent_tint_hover;
}
QPushButton#importButton[emphasis="true"]:pressed:enabled {
    background: $text_selection_bg;
}
QPushButton#importButton:focus, QPushButton#importButton:focus:hover {
    border-color: $accent;
}
QFrame#cardHeaderLine {
    background: $border;
    border: none;
}
QPushButton#importButton:disabled {
    background: $import_disabled_bg;
    color: $import_disabled_text;
}
QFrame#folderSplitButton {
    background: $button;
    border: 2px solid transparent;
    border-radius: $radius_md;
}
QFrame#folderSplitButton[focusWithin="true"] {
    border-color: $accent;
}
QFrame#folderSplitButton:disabled {
    background: $import_disabled_bg;
}
QFrame#folderSplitDivider {
    background: $border_strong;
    border: none;
}
QFrame#folderSplitDivider:disabled {
    background: $border;
}
QFrame#folderSplitButton QPushButton#importButton {
    background: transparent;
    border: none;
}
QFrame#folderSplitButton QPushButton#importButton[split="main"] {
    border-radius: 0;
    border-top-left-radius: 8px;
    border-bottom-left-radius: 8px;
    padding: 0 9px;
}
QFrame#folderSplitButton QPushButton#importButton[split="arrow"] {
    border-radius: 0;
    border-top-right-radius: 8px;
    border-bottom-right-radius: 8px;
    padding: 0;
}
QFrame#folderSplitButton QPushButton#importButton:disabled {
    background: transparent;
}
QFrame#folderSplitButton QPushButton#importButton:hover:enabled {
    background: $button_hover;
}
QFrame#folderSplitButton QPushButton#importButton:pressed:enabled,
QFrame#folderSplitButton QPushButton#importButton[split="arrow"][menuOpen="true"] {
    background: $button_pressed;
}
QPushButton#primaryButton {
    background: $button;
    color: $text;
}
QPushButton#primaryButton[footerPrimary="true"] {
    background: $primary;
    color: $on_primary;
    border: 2px solid $primary;
    min-height: ${convert_content}px;
    max-height: ${convert_content}px;
    padding: 0 ${convert_padding}px;
    border-radius: $radius_pill;
    font-size: 16px;
    font-weight: $convert_weight;
}
QPushButton#primaryButton[footerPrimary="true"]:hover {
    background: $primary_hover;
    border-color: $primary_hover;
}
QPushButton#primaryButton[footerPrimary="true"]:pressed {
    background: $accent_pressed;
    border-color: $accent_pressed;
}
QPushButton#primaryButton[footerPrimary="true"]:focus {
    border-color: $accent_pressed;
}
QPushButton#primaryButton[footerPrimary="true"]:disabled {
    background: $footer_disabled_bg;
    border-color: $footer_disabled_bg;
    color: $convert_disabled_text;
}
QPushButton#stepperButton {
    min-width: 16px;
    max-width: 16px;
    min-height: ${field_content}px;
    max-height: ${field_content}px;
    padding: 0 8px;
    font-size: 12pt;
}
QCheckBox, QRadioButton {
    spacing: 8px;
    border: 2px solid transparent;
    border-radius: $radius_sm_focus;
    padding: 2px;
}
QCheckBox:focus, QRadioButton:focus {
    border-color: $accent;
}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
    background: $field;
    border-color: $accent;
}
QCheckBox::indicator, QTableView::indicator, QTreeWidget#instanceTree::indicator {
    width: ${indicator_content}px;
    height: ${indicator_content}px;
    border: ${indicator_border}px solid $control_border_off;
    border-radius: $radius_sm;
    background: $surface;
}
QCheckBox::indicator:unchecked:hover, QTableView::indicator:unchecked:hover,
QTreeWidget#instanceTree::indicator:unchecked:hover, QRadioButton::indicator:unchecked:hover {
    border-color: $control_border_hover;
}
QCheckBox::indicator:checked, QTableView::indicator:checked,
QTreeWidget#instanceTree::indicator:checked {
    background: $accent;
    border-color: $accent;
    image: $check_icon;
}
QCheckBox::indicator:indeterminate, QTableView::indicator:indeterminate,
QTreeWidget#instanceTree::indicator:indeterminate {
    background: $accent;
    border-color: $accent;
    image: $dash_icon;
}
QCheckBox#warnCheckbox::indicator:checked {
    background: $warn_accent;
    border-color: $warn_accent;
    image: $check_icon;
}
QTableView::indicator:disabled {
    background: $disabled_bg;
    border-color: $checkbox_disabled_border;
}
QTableView::indicator:checked:disabled {
    background: $primary_disabled;
    border-color: $primary_disabled;
}
QCheckBox:disabled {
    color: $import_disabled_text;
}
QCheckBox::indicator:disabled {
    background: $import_disabled_bg;
    border-color: $checkbox_disabled_border;
}
QCheckBox::indicator:checked:disabled {
    background: $primary_disabled;
    border-color: $primary_disabled;
    image: $check_icon;
}
QCheckBox::indicator:indeterminate:disabled {
    background: $primary_disabled;
    border-color: $primary_disabled;
    image: $dash_icon;
}
QRadioButton::indicator {
    width: ${indicator_content}px;
    height: ${indicator_content}px;
    border: ${indicator_border}px solid $control_border_off;
    border-radius: $radius_full_radio;
    background: $surface;
}
QRadioButton::indicator:checked {
    border-color: $accent;
    background: $accent;
    image: $radio_dot_icon;
}
QRadioButton::indicator:disabled {
    background: $import_disabled_bg;
    border-color: $checkbox_disabled_border;
}
QListWidget {
    background: $list_bg;
    color: $text;
    border: 1px solid $border;
    border-radius: $radius_lg;
    padding: 6px;
    outline: none;
}
QListWidget::item {
    padding: 8px;
    border-radius: $radius_sm;
}
QTableView, QTreeWidget#instanceTree {
    font-weight: 400;
    background: $list_bg;
    alternate-background-color: $surface;
    color: $text;
    border: none;
    border-top: 1px solid $border;
    border-bottom: 1px solid $border;
    border-radius: 0;
    selection-background-color: $row_selection;
    selection-color: $selection_text;
    outline: none;
}
QTableView:focus, QTreeWidget#instanceTree:focus {
    border-top-color: $border_hover;
    border-bottom-color: $border_hover;
}
QTableView::item, QTreeWidget#instanceTree::item {
    border: none;
    padding: 0 12px 0 $item_padding_left;
}
QTableView::item:selected:active, QTreeWidget#instanceTree::item:selected:active {
    background: $row_selection;
    color: $text;
}
QTableView::item:selected:!active, QTreeWidget#instanceTree::item:selected:!active {
    background: $row_selection_inactive;
    color: $text;
}
QTreeWidget#instanceTree::branch:closed:has-children {
    image: none;
}
QTreeWidget#instanceTree::branch:open:has-children {
    image: none;
}
QTableView#fontFileTable {
    font-weight: 400;
    alternate-background-color: $surface;
}
QTableView#fontFileTable QHeaderView, QTreeWidget#instanceTree QHeaderView {
    font-weight: 600;
}
QTableView[dragOver="true"], QTreeWidget#instanceTree[dragOver="true"] {
    background: $row_selected_a;
    border-top-color: $accent;
    border-bottom-color: $accent;
}
QListWidget::item:selected {
    background: $selection_bg;
    color: $selection_text;
}
QHeaderView {
    background: $table_header;
    border: none;
}
QHeaderView::section, QTableCornerButton::section {
    background: $table_header;
    color: $text_muted;
    border: none;
    border-bottom: 1px solid $border;
    padding: 3px;
}
QTableView#fontFileTable QHeaderView::section, QTreeWidget#instanceTree QHeaderView::section {
    border-bottom-color: $border;
    /* Column separator: the 1px border takes the place of 1px of right padding, so the
       label rect (and the size from contents) is the same as without it. */
    border-right: 1px solid $border_strong;
    padding-right: 2px;
}
QTableView#fontFileTable QHeaderView::section:last,
QTableView#fontFileTable QHeaderView::section:only-one,
QTreeWidget#instanceTree QHeaderView::section:last,
QTreeWidget#instanceTree QHeaderView::section:only-one {
    border-right: none;
    padding-right: 3px;
}
QHeaderView::section:first {
    padding-left: 16px;
}
QTreeWidget#instanceTree QHeaderView::section:last {
    padding-left: $header_text_inset;
}
QWidget#tableScrollbarHeader {
    background: $table_header;
    border-bottom: 1px solid $border;
}
QHeaderView::up-arrow {
    image: $sort_up_icon;
    width: 17px;
    height: 17px;
}
QHeaderView::down-arrow {
    image: $sort_down_icon;
    width: 17px;
    height: 17px;
}
QScrollBar:vertical {
    background: transparent;
    border: none;
    width: 12px;
    margin: 2px 0;
}
QScrollBar:horizontal {
    background: transparent;
    border: none;
    height: 12px;
    margin: 0 2px;
}
QScrollBar::handle:vertical {
    background: $scroll_handle;
    border-radius: $radius_full_bar;
    min-height: 32px;
    margin: 0 3px;
}
QScrollBar::handle:horizontal {
    background: $scroll_handle;
    border-radius: $radius_full_bar;
    min-width: 32px;
    margin: 3px 0;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background: $scroll_handle_hover;
}
QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed {
    background: $scroll_handle_pressed;
}
QScrollBar::handle:vertical:disabled, QScrollBar::handle:horizontal:disabled {
    background: transparent;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0px;
    height: 0px;
    border: none;
    background: none;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: none;
}
QAbstractScrollArea::corner {
    background: $list_bg;
    border: none;
}
QProgressBar {
    background: $progress_track;
    border: none;
    border-radius: $radius_full_bar;
    min-height: 6px;
    max-height: 6px;
}
QProgressBar::chunk {
    background: $accent;
    border-radius: $radius_full_bar;
}
QProgressBar[stopped="true"]::chunk {
    background: $control_border_strong;
}
QProgressBar#conversionProgress {
    min-height: 6px;
    max-height: 6px;
    background: transparent;
    border: none;
}
QToolTip {
    background: $tooltip_bg;
    color: $tooltip_text;
    border: 1px solid $tooltip_bg;
    border-radius: 0;
    padding: 6px 10px;
    font-family: "$ui_font_family";
    font-size: 12px;
    font-weight: 500;
}
""")


def _icon_directory() -> Path:
    location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    base = Path(location) if location else Path(tempfile.gettempdir()) / "fontvertx"
    return base / "icons"


def _tinted_svg(name: str, color: str) -> str:
    """Stylesheet image value for Material Symbol ``name`` in ``color``.

    QSS cannot recolor an image, so a tinted copy of the bundled SVG is written to the
    cache directory (the glyph stays vector: Qt renders it at the screen's scale).
    Returns 'none' if it cannot be written.
    """
    source = _MATERIAL_DIR / f"{name}.svg"
    try:
        svg = source.read_text(encoding="utf-8")
        tinted = svg.replace("<svg ", f'<svg fill="{color}" ', 1)
        directory = _icon_directory()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}_{color[1:]}.svg"
        if not path.is_file() or path.read_text(encoding="utf-8") != tinted:
            # Write to a sibling file first so concurrent instances never read a partial file.
            partial = path.with_name(f"{os.getpid()}_{path.name}")
            partial.write_text(tinted, encoding="utf-8")
            os.replace(partial, path)
    except OSError as error:
        logger.warning("Could not create the %s stylesheet icon: %s", name, error)
        return "none"
    return f"url({path.as_posix()})"


def _indicator_svg(name: str) -> str:
    """Bundled white indicator mark (check, dash, dot) as a stylesheet image value."""
    path = _INDICATOR_DIR / f"{name}.svg"
    if not path.is_file():
        logger.warning("Indicator mark not found: %s", path)
        return "none"
    return f"url({path.as_posix()})"


def build_stylesheet(palette: Palette) -> str:
    return _TEMPLATE.substitute(
        vars(palette),
        radius_sm=RADIUS_SM,
        radius_md=RADIUS_MD,
        radius_lg=RADIUS_LG,
        radius_xl=RADIUS_XL,
        radius_full_radio=RADIUS_FULL_RADIO,
        radius_full_badge=RADIUS_FULL_BADGE,
        radius_full_chip=RADIUS_FULL_CHIP,
        radius_full_bar=RADIUS_FULL_BAR,
        radius_pill=RADIUS_PILL,
        radius_round=RADIUS_ROUND,
        radius_status_chip=RADIUS_STATUS_CHIP,
        item_padding_left=f"{ITEM_PADDING_LEFT}px",
        header_text_inset=f"{ITEM_PADDING_LEFT + ITEM_TEXT_MARGIN}px",
        radius_footer=RADIUS_FOOTER,
        footer_border=FOOTER_CARD_BORDER,
        convert_padding=CONVERT_PADDING_H,
        convert_weight=CONVERT_WEIGHT,
        footer_status_weight=FOOTER_STATUS_WEIGHT,
        footer_status_size=FOOTER_STATUS_SIZE,
        scan_label_px=SCAN_LABEL_PIXEL_SIZE,
        chip_px=CHIP_PIXEL_SIZE,
        radius_sm_focus=RADIUS_SM_FOCUS,
        field_height=FIELD_HEIGHT,
        field_border=FIELD_BORDER,
        field_content=FIELD_HEIGHT - 2 * FIELD_BORDER,
        button_content=BUTTON_HEIGHT - 2 * FIELD_BORDER,
        convert_content=CONVERT_HEIGHT - 2 * FIELD_BORDER,
        indicator_content=f"{INDICATOR_SIZE - 2 * INDICATOR_BORDER:g}",
        indicator_border=f"{INDICATOR_BORDER:g}",
        ui_font_family=UI_FONT_FAMILY,
        mono_family=_mono_family,
        check_icon=_indicator_svg("check"),
        radio_dot_icon=_indicator_svg("dot"),
        dash_icon=_indicator_svg("dash"),
        combo_down_icon=_tinted_svg("expand_more", palette.text_muted),
        combo_up_icon=_tinted_svg("expand_less", palette.text_muted),
        sort_up_icon=_tinted_svg("arrow_upward", palette.text_muted),
        sort_down_icon=_tinted_svg("arrow_downward", palette.text_muted),
    )


@cache
def stylesheet() -> str:
    """Return the application style sheet, building it on first use."""
    return build_stylesheet(LIGHT)
