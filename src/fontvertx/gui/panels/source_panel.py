"""Builds the "Select fonts" card: import controls, file table, instance tree, scan bar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QEnterEvent,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from fontvertx.gui.file_list import FontFileList
from fontvertx.gui.icons import material_icon
from fontvertx.gui.instance_tree import InstanceTree
from fontvertx.gui.layout_manager import CARD_GAP, CARD_PADDING
from fontvertx.gui.settings_store import OPTIONAL_FONT_COLUMNS
from fontvertx.gui.styles import (
    BUTTON_HEIGHT,
    FIELD_HEIGHT,
    LIGHT,
    SCAN_LABEL_PIXEL_SIZE,
    mono_font,
)
from fontvertx.gui.tooltips import wrap_tip
from fontvertx.gui.widgets import (
    IMPORT_BUTTON_HEIGHT,
    DropZone,
    ElidedLabel,
    FileTable,
    FolderSplitButton,
    KeyboardPushButton,
    card_heading,
)

if TYPE_CHECKING:
    from fontvertx.gui.window import ConverterWindow

FONT_FILTER_PLACEHOLDER = "Filter fonts…"
CARD_INSET = CARD_PADDING  # side margin of everything in the source card except the list
HEADER_PADDING_V = 14  # above and below the header row (title + add actions)
HEADER_ACTION_GAP = 8  # between "Add files…" and "Add folder…"
TOOLBAR_SPACING = 8  # between the controls of the filter row
INSTANCE_VIEW_BUTTON_SIZE = BUTTON_HEIGHT  # expand / collapse all: square, as tall as "Clear list"


def list_status_text(total: int, shown: int, hidden_incompatible: int, *, filtered: bool) -> str:
    if not total:
        return ""
    text = f"{shown} of {total} shown" if filtered else f"{total} font{'s' if total != 1 else ''}"
    if hidden_incompatible:
        text += f" · {hidden_incompatible} incompatible hidden"
    return text


class ScanProgress(QProgressBar):
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = self.height() / 2
        track = QPainterPath()
        track.addRoundedRect(QRectF(self.rect()), radius, radius)
        painter.fillPath(track, QColor(LIGHT.progress_track))
        painter.setClipPath(track)
        span = self.maximum() - self.minimum()
        fraction = max(0.0, min(1.0, (self.value() - self.minimum()) / span)) if span else 0
        width = self.width() * fraction
        fill = QPainterPath()
        fill.addRoundedRect(QRectF(0, 0, width, self.height()), min(radius, width / 2), radius)
        painter.fillPath(fill, QColor(LIGHT.accent))


class ListStatusLabel(ElidedLabel):
    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        hint.setWidth(0)
        return hint

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint


def scan_label_width(label: QLabel) -> int:
    """Width of the widest scan status text, so the bar does not move as digits grow."""
    font = mono_font()
    font.setPixelSize(SCAN_LABEL_PIXEL_SIZE)
    font.setWeight(QFont.Weight.Medium)
    metrics = QFontMetrics(font)
    widest = ("Scanning fonts… 99999 / 99999", "Scan stopped at 99999 / 99999")
    return max(metrics.horizontalAdvance(text) for text in widest) + 4


class GhostIconButton(KeyboardPushButton):
    """Icon-only ghost button: muted glyph, full text color while hovered or pressed."""

    def __init__(self, icon: str) -> None:
        super().__init__()
        self._rest = material_icon(icon, LIGHT.text_muted, 16, disabled_color=LIGHT.text_disabled)
        self._active = material_icon(icon, LIGHT.text, 16, disabled_color=LIGHT.text_disabled)
        self.setIcon(self._rest)

    def enterEvent(self, event: QEnterEvent) -> None:
        self.setIcon(self._active)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.setIcon(self._rest)
        super().leaveEvent(event)


def instance_view_button(icon: str, name: str) -> GhostIconButton:
    """Icon-only button of the filter row, as tall as "Clear list"."""
    button = GhostIconButton(icon)
    button.setObjectName("quietIconButton")
    button.setIconSize(QSize(16, 16))
    button.setFixedSize(INSTANCE_VIEW_BUTTON_SIZE, INSTANCE_VIEW_BUTTON_SIZE)
    button.setToolTip(name)
    button.setAccessibleName(name)
    return button


def build_source_card(window: ConverterWindow) -> QGroupBox:
    w = window
    w.drop_zone = DropZone()
    # The add actions live in the card header, list populated or not (text only).
    w.add_button = KeyboardPushButton("Add files…")
    w.add_button.setObjectName("importButton")
    w.add_button.setFixedHeight(IMPORT_BUTTON_HEIGHT)
    w.add_button.setAccessibleName("Add files…")
    w.folder_split = FolderSplitButton()
    w.add_folder_button = w.folder_split.main_button
    w.add_folder_button.setAccessibleName("Add folder…")
    w.folder_split.folder_requested.connect(w._choose_folder)
    w.clear_button = KeyboardPushButton("Clear list")
    w.clear_button.setObjectName("ghostButton")
    w.clear_button.setAccessibleName("Clear list")

    files_group = QGroupBox()
    files_group.setObjectName("card")
    # The header line and the list run edge to edge, so the card itself has no side or
    # top margins: every other row sits in a sub-layout that restores the inset. The
    # header's own padding and the bottom padding (>= the card radius) keep square
    # corners off the card's rounded ones.
    files_layout = QVBoxLayout(files_group)
    files_layout.setContentsMargins(0, 0, 0, CARD_PADDING)
    files_layout.setSpacing(9)
    w.files_header = QWidget()
    w.files_header.setObjectName("cardHeader")
    header_layout = QHBoxLayout(w.files_header)
    header_layout.setContentsMargins(CARD_INSET, HEADER_PADDING_V, CARD_INSET, HEADER_PADDING_V)
    header_layout.setSpacing(HEADER_ACTION_GAP)
    header_layout.addWidget(
        card_heading("Add Fonts", 1, bottom_margin=0), 1, Qt.AlignmentFlag.AlignVCenter
    )
    header_layout.addWidget(w.add_button, 0, Qt.AlignmentFlag.AlignVCenter)
    header_layout.addWidget(w.folder_split, 0, Qt.AlignmentFlag.AlignVCenter)
    # A real 1px widget across the whole card width (inside its border), not a QSS margin.
    w.files_header_line = QFrame()
    w.files_header_line.setObjectName("cardHeaderLine")
    w.files_header_line.setFixedHeight(1)
    header_block = QWidget()
    header_block_layout = QVBoxLayout(header_block)
    header_block_layout.setContentsMargins(0, 0, 0, 0)
    header_block_layout.setSpacing(0)
    header_block_layout.addWidget(w.files_header)
    header_block_layout.addWidget(w.files_header_line)
    files_layout.addWidget(header_block)
    inset = QVBoxLayout()
    # 9px layout spacing + 3px: the filter row sits 12px under the header line.
    inset.setContentsMargins(CARD_INSET, 3, CARD_INSET, 0)
    inset.setSpacing(9)
    files_layout.addLayout(inset)
    w.select_all_checkbox = QCheckBox("Select all")
    w.select_all_checkbox.setTristate(True)
    w.select_all_checkbox.setToolTip("Select or clear all visible compatible fonts.")
    w.select_all_checkbox.clicked.connect(w._toggle_visible_checks)
    w.hide_incompatible = QCheckBox("Hide incompatible")
    w.hide_incompatible.setToolTip("Hide fonts that cannot be used with the selected profile.")
    w.hide_incompatible.toggled.connect(w._apply_compatibility)
    w.hide_incompatible.toggled.connect(w._update_buttons)
    w.font_filter = QLineEdit()
    w.font_filter.setPlaceholderText(FONT_FILTER_PLACEHOLDER)
    w.font_filter.setClearButtonEnabled(True)
    # Replace the style's raster clear glyph with the vector one (sharp at any scale).
    clear_action = w.font_filter.findChild(QAction, "_q_qlineeditclearaction")
    if clear_action is not None:
        clear_action.setIcon(material_icon("close", LIGHT.text_muted, 16))
    w.font_filter.setToolTip("Filter fonts by name, family, style, format, outlines, or UPM.")
    w.font_filter.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    w.file_options_row = QBoxLayout(QBoxLayout.Direction.LeftToRight)
    w.file_options_row.setSpacing(TOOLBAR_SPACING)
    w.file_options_row.addWidget(w.select_all_checkbox, 0, Qt.AlignmentFlag.AlignLeft)
    w.file_options_row.addWidget(w.font_filter, 1)
    w.file_options_row.addWidget(w.hide_incompatible, 0, Qt.AlignmentFlag.AlignLeft)
    w.file_options_row.addWidget(w.clear_button, 0, Qt.AlignmentFlag.AlignLeft)
    w.expand_instances_button = instance_view_button("unfold_more", "Expand all")
    w.collapse_instances_button = instance_view_button("unfold_less", "Collapse all")
    w.file_options_row.addWidget(w.expand_instances_button, 0, Qt.AlignmentFlag.AlignLeft)
    w.file_options_row.addWidget(w.collapse_instances_button, 0, Qt.AlignmentFlag.AlignLeft)
    inset.addLayout(w.file_options_row)

    w.files = FileTable()
    w.file_list = FontFileList(w.files, w._compatibility_profile)
    w.column_menu = QMenu(w.files)
    table_header = w.files.horizontalHeader()
    table_header.setToolTip(
        "Click to sort; right-click or use the button on the right to choose columns."
    )
    table_header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    table_header.customContextMenuRequested.connect(w._show_column_menu)
    w.files.column_button.attach_menu(w.column_menu, w.files)
    # Every column is listed: the fixed ones checked and disabled, then the optional ones.
    for column, name in enumerate(w.file_list.model.HEADERS):
        if column in OPTIONAL_FONT_COLUMNS:
            continue
        action = w.column_menu.addAction(name)
        action.setData(column)
        action.setCheckable(True)
        action.setChecked(True)
        action.setEnabled(False)
    w.column_menu.addSeparator()
    for column, (name, key) in OPTIONAL_FONT_COLUMNS.items():
        visible = w.store.get_bool(key)
        w.files.setColumnHidden(column, not visible)
        action = w.column_menu.addAction(name)
        action.setData(column)
        action.setCheckable(True)
        action.setChecked(visible)
        action.toggled.connect(w._set_column_visible)
    w.file_list.progress.connect(w._on_scan_progress)
    w.file_list.font_found.connect(w._on_font_found)
    w.file_list.scan_finished.connect(w._on_scan_finished)
    w.file_list.scan_failed.connect(w._on_scan_failed)
    w.files.setMinimumHeight(150)
    w.files.setToolTip("Check the fonts to convert. Click a column header to sort.")
    w.file_list.model.dataChanged.connect(w._on_file_item_changed)
    w.instance_tree = InstanceTree()
    w.font_filter.textChanged.connect(w.instance_tree.set_filter)
    w.font_filter.textChanged.connect(w.file_list.proxy.setFilterFixedString)
    w.font_filter.textChanged.connect(w._update_buttons)
    w.instance_tree.setMinimumHeight(150)
    w.instance_tree.setToolTip(
        wrap_tip(
            "Check instances to export. Double-click a custom instance to edit it; "
            "right-click it or press Shift+F10 for actions, or Delete to remove it."
        )
    )
    w.instance_tree.checksChanged.connect(w._update_buttons)
    w.expand_instances_button.clicked.connect(w.instance_tree.expandAll)
    w.collapse_instances_button.clicked.connect(w.instance_tree.collapseAll)
    w.files_stack = QStackedWidget()
    w.files_stack.addWidget(w.files)
    w.files_stack.addWidget(w.instance_tree)
    files_layout.addWidget(w.files_stack, 1)
    w.scan_widget = QWidget()
    scan_layout = QHBoxLayout(w.scan_widget)
    scan_layout.setContentsMargins(CARD_INSET, 0, CARD_INSET, 0)
    scan_layout.setSpacing(10)
    w.scan_label = ListStatusLabel()
    w.scan_label.setObjectName("stepHint")
    w.scan_label.setProperty("mono", True)
    w.scan_label.setWordWrap(False)
    w.scan_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    w.scan_progress = ScanProgress()
    w.scan_progress.setTextVisible(False)
    w.scan_progress.setFixedHeight(6)
    scan_layout.addWidget(w.scan_label)
    scan_layout.addWidget(w.scan_progress, 1)
    w.scan_stop_button = KeyboardPushButton("Stop")
    w.scan_stop_button.setObjectName("importButton")
    w.scan_stop_button.setToolTip("Stop the scan and keep the fonts found so far.")
    w.scan_stop_button.clicked.connect(w._cancel_scan)
    scan_layout.addWidget(w.scan_stop_button)
    files_layout.addWidget(w.scan_widget)
    w.files_group = files_group
    w.files_group_layout = files_layout
    w.files_column = QWidget()
    w.files_column.setObjectName("page")
    w.files_column_layout = QVBoxLayout(w.files_column)
    w.files_column_layout.setContentsMargins(0, 0, 0, 0)
    w.files_column_layout.setSpacing(CARD_GAP)
    w.files_column_layout.addWidget(files_group, 1)
    # A widget, not a nested layout: hiding it drops the slot from the card in the same
    # layout pass, while a hidden widget inside a nested layout settles one pass late
    # and makes the list jump in height.
    w.drop_slot = QWidget()
    drop_slot_layout = QHBoxLayout(w.drop_slot)
    drop_slot_layout.setContentsMargins(CARD_INSET, 0, CARD_INSET, 0)
    drop_slot_layout.addWidget(w.drop_zone)
    files_layout.insertWidget(files_layout.indexOf(w.scan_widget), w.drop_slot)
    return files_group


def place_drop_zone(window: ConverterWindow, populated: bool) -> None:
    """Show the drop zone while the list is empty (the add actions stay in the header).

    With an empty list "Add files…" is the emphasized entry point (tinted, weight 600).
    """
    w = window
    sync_drop_zone_height(w)
    w.drop_zone.setVisible(not populated)
    w.drop_slot.setVisible(not populated)
    set_add_files_emphasis(w.add_button, not populated)


def sync_drop_zone_height(window: ConverterWindow) -> None:
    """The empty zone also takes the room of the rows hidden with the list.

    Those are the filter row and, unless a scan shows it, the count row (each with its
    layout gap). The zone then ends one card padding above the bottom, and the card keeps
    its height when the first fonts arrive or a scan starts.
    """
    w = window
    gap = w.files_group_layout.spacing()
    height = w.files.minimumHeight() + FIELD_HEIGHT + gap
    if w.scan_widget.isHidden():
        height += w.scan_widget.maximumHeight() + gap
    w.drop_zone.setMinimumHeight(height)


def set_add_files_emphasis(button: QPushButton, emphasized: bool) -> None:
    """Toggle the tinted style; the width fits the bolder label, so nothing shifts."""
    widths = []
    for value in ("true", "false"):
        button.setProperty("emphasis", value)
        button.style().unpolish(button)
        button.style().polish(button)
        widths.append(button.sizeHint().width())
    button.setProperty("emphasis", "true" if emphasized else "false")
    button.style().unpolish(button)
    button.style().polish(button)
    button.setFixedWidth(max(widths))
    button.update()
