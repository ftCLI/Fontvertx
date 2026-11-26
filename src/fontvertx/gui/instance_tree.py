"""Per-font tree of the static instances to export from variable fonts."""

from functools import cache
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QFontMetrics,
    QHelpEvent,
    QIcon,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
    QResizeEvent,
    QShortcut,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from fontvertx.gui.column_widths import (
    FIRST_COLUMN_MIN_WIDTH,
    METRIC_EVENTS,
    FillColumnLayout,
    fixed_column_widths,
)
from fontvertx.gui.file_list import FontBadgeDelegate, FontRowDelegate, font_row_background
from fontvertx.gui.icons import material_icon
from fontvertx.gui.styles import RADIUS_SM, colors, radius_px, tabular_font, ui_font
from fontvertx.gui.tooltips import wrap_tip
from fontvertx.gui.widgets import (
    DecimalSpinBox,
    ScrollbarHeaderFiller,
    StepperField,
    accept_local_files,
    dropped_paths,
    set_drag_over,
)
from fontvertx.inspection import AxisInfo, FontInfo
from fontvertx.models import InstanceSpec
from fontvertx.service import instance_label, instance_stem

_SPEC_ROLE = Qt.ItemDataRole.UserRole
_CUSTOM_ROLE = Qt.ItemDataRole.UserRole + 1
_PATH_ROLE = Qt.ItemDataRole.UserRole + 2
_AXES_ROLE = Qt.ItemDataRole.UserRole + 3
_OUTLINES_ROLE = Qt.ItemDataRole.UserRole + 4
# Extra text the filter searches besides the cells: the font path, a skipped row's reason.
_SEARCH_ROLE = Qt.ItemDataRole.UserRole + 5
# Position of an instance among its font's rows, in the order they were added.
_ORDER_ROLE = Qt.ItemDataRole.UserRole + 6
_FORMAT_COLUMN = 1
_LOCATION_COLUMN = 4
# Chip in the Format cell of a custom instance row.
CUSTOM_CHIP_LABEL = "Custom"
_UPM_ALIGNMENT = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
# The list is edge to edge: nudge the branch chevron right, away from the card edge.
BRANCH_ICON_OFFSET = 5
# Fits the "+ Instance" row action next to "12 of 12 selected".
LOCATION_MIN_WIDTH = 230
LOCATION_MAX_WIDTH = 360

# "+ Instance": the inline action painted in the Location cell of a variable font row.
ADD_ACTION_LABEL = "Instance"
ADD_ACTION_TOOLTIP = "Add custom instance (Ins)"
# On every cell of a custom instance row (its "Custom" chip included), and nowhere else.
CUSTOM_INSTANCE_TOOLTIP = "Double-click or press Enter to edit. Delete to remove."
ADD_ACTION_HEIGHT = 22
ADD_ACTION_INSET = 6  # from the left edge of the cell
ADD_ACTION_PADDING_LEFT = 6
ADD_ACTION_PADDING_RIGHT = 8
ADD_ACTION_GLYPH = 12
ADD_ACTION_GLYPH_GAP = 4
ADD_ACTION_TEXT_GAP = 8  # between the button and the "N of N selected" text
ADD_ACTION_TEXT_MARGIN = 6  # right margin of that text
ADD_ACTION_GHOST_OPACITY = 0.55
ACTION_SOLID = "solid"
ACTION_GHOST = "ghost"

_Memory = tuple[set[InstanceSpec], list[InstanceSpec]]


def add_action_font() -> QFont:
    font = ui_font(QApplication.font())
    font.setPixelSize(12)
    font.setWeight(QFont.Weight.DemiBold)
    return font


@cache
def _add_action_icon() -> QIcon:
    return material_icon("add", "accent_text", ADD_ACTION_GLYPH)


def add_action_rect(cell: QRect) -> QRect:
    """Bounds of the "+ Instance" button in a Location cell: painted and hit-tested alike."""
    label_width = QFontMetrics(add_action_font()).horizontalAdvance(ADD_ACTION_LABEL)
    width = (
        2  # 1px border on each side
        + ADD_ACTION_PADDING_LEFT
        + ADD_ACTION_GLYPH
        + ADD_ACTION_GLYPH_GAP
        + label_width
        + ADD_ACTION_PADDING_RIGHT
    )
    height = min(ADD_ACTION_HEIGHT, cell.height())
    top = cell.top() + (cell.height() - height) // 2
    return QRect(cell.left() + ADD_ACTION_INSET, top, width, height)


def add_action_text_layout(
    cell: QRect, text: str, metrics: QFontMetrics, right: int | None = None
) -> tuple[QRect, str]:
    """Rect and elided text of the summary beside the button: the text gives way, not it.

    ``right`` is the right edge of the text in a cell without the button, so the summary
    does not move when the button appears.
    """
    button = add_action_rect(cell)
    left = button.right() + 1 + ADD_ACTION_TEXT_GAP
    if right is None:
        right = cell.right() - ADD_ACTION_TEXT_MARGIN
    rect = QRect(left, cell.top(), max(0, right - left + 1), cell.height())
    return rect, metrics.elidedText(text, Qt.TextElideMode.ElideRight, rect.width())


def paint_add_action(painter: QPainter, rect: QRect, *, ghost: bool, pressed: bool) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if ghost:
        painter.setOpacity(ADD_ACTION_GHOST_OPACITY)
    border = QColor(colors().accent_border_soft if ghost else colors().accent)
    painter.setPen(QPen(border, 1))
    painter.setBrush(QColor(colors().row_selection if pressed else colors().surface))
    radius = radius_px(RADIUS_SM)
    painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    glyph = QRect(
        rect.left() + 1 + ADD_ACTION_PADDING_LEFT,
        rect.top() + (rect.height() - ADD_ACTION_GLYPH) // 2,
        ADD_ACTION_GLYPH,
        ADD_ACTION_GLYPH,
    )
    _add_action_icon().paint(painter, glyph, Qt.AlignmentFlag.AlignCenter)
    painter.setFont(add_action_font())
    painter.setPen(QColor(colors().accent_text))
    label = QRect(glyph.right() + 1 + ADD_ACTION_GLYPH_GAP, rect.top(), rect.width(), rect.height())
    painter.drawText(
        label, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, ADD_ACTION_LABEL
    )
    painter.restore()


def _is_custom_instance(index: QModelIndex | QPersistentModelIndex) -> bool:
    if not index.isValid() or not index.parent().isValid():
        return False
    return bool(index.sibling(index.row(), 0).data(_CUSTOM_ROLE))


# Row types of the tree (see InstanceTree.row_kind).
ROW_FONT = "font"
ROW_CUSTOM = "custom"
ROW_INSTANCE = "instance"  # a named or default instance


class InstanceRowDelegate(FontRowDelegate):
    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        size = super().sizeHint(option, index)
        size.setHeight(30)
        return size

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        view = self.parent()
        state = (
            view.add_action_state(index)
            if isinstance(view, InstanceTree) and index.column() == _LOCATION_COLUMN
            else None
        )
        if not isinstance(view, InstanceTree) or state is None:
            super().paint(painter, option, index)
            return
        # Same background and selection drawing as the other cells, then the button on
        # the left and the summary right-aligned in the room that is left.
        display_option = QStyleOptionViewItem(option)
        self.initStyleOption(display_option, index)
        self.prepare_row(display_option, index)
        text = display_option.text
        widget = display_option.widget
        style = widget.style() if widget is not None else QApplication.style()
        # Where CE_ItemViewItem would end the text: its rect, less Qt's text margin.
        text_right = (
            style.subElementRect(
                QStyle.SubElement.SE_ItemViewItemText, display_option, widget
            ).right()
            - style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, widget)
            - 1
        )
        display_option.text = ""
        if display_option.backgroundBrush.style() != Qt.BrushStyle.NoBrush:
            painter.fillRect(display_option.rect, display_option.backgroundBrush)
        if display_option.widget is not None:
            display_option.widget.style().drawControl(
                QStyle.ControlElement.CE_ItemViewItem,
                display_option,
                painter,
                display_option.widget,
            )
        text_rect, visible = add_action_text_layout(
            option.rect, text, display_option.fontMetrics, text_right
        )
        painter.save()
        painter.setClipRect(option.rect)
        if visible:
            painter.setFont(display_option.font)
            painter.setPen(display_option.palette.color(QPalette.ColorRole.Text))
            painter.drawText(
                text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, visible
            )
        paint_add_action(
            painter,
            add_action_rect(option.rect),
            ghost=state == ACTION_GHOST,
            pressed=view.is_add_action_pressed(index),
        )
        painter.restore()


class InstanceBadgeDelegate(InstanceRowDelegate, FontBadgeDelegate):
    paint = FontBadgeDelegate.paint

    def initStyleOption(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        super().initStyleOption(option, index)
        # Painted only: the cell itself stays empty, so sorting and filtering ignore it.
        if index.column() == _FORMAT_COLUMN and _is_custom_instance(index):
            option.text = CUSTOM_CHIP_LABEL


def _number(value: float) -> str:
    return f"{value:g}"


def location_text(coordinates: tuple[tuple[str, float], ...]) -> str:
    if not coordinates:
        return "Default"
    return ", ".join(f"{tag}={_number(value)}" for tag, value in coordinates)


PREVIEW_MIN_LINES = 2  # the output file preview never takes less, so it does not jump
_ZERO_WIDTH_SPACE = "​"


def _wrappable(file_name: str) -> str:
    """Let a long file name wrap after "-" / "_" and before the extension, never elided."""
    for separator in ("-", "_"):
        file_name = file_name.replace(separator, separator + _ZERO_WIDTH_SPACE)
    stem, dot, suffix = file_name.rpartition(".")
    return f"{stem}{_ZERO_WIDTH_SPACE}{dot}{suffix}" if dot else file_name


class CustomInstanceDialog(QDialog):
    """Ask for one value per axis of a single variable font."""

    def __init__(
        self,
        axes: tuple[AxisInfo, ...],
        named_instances: tuple[InstanceSpec, ...],
        font_name: str,
        input_path: Path,
        parent: QWidget,
        coordinates: tuple[tuple[str, float], ...] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            "Edit custom instance" if coordinates is not None else "Custom instance"
        )
        self._axes = axes
        self._named_instances = named_instances
        self._input_path = input_path
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(9)
        intro = QLabel(f"Axis values for {font_name}")
        intro.setObjectName("hint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self._boxes: dict[str, DecimalSpinBox] = {}
        for row, axis in enumerate(axes):
            box = DecimalSpinBox()
            box.setProperty("mono", "true")
            box.setDecimals(2)
            box.setRange(axis.minimum, axis.maximum)
            box.setValue(dict(coordinates or ()).get(axis.tag, axis.default))
            self._boxes[axis.tag] = box
            field = StepperField(box)
            field.setFixedWidth(170)
            range_label = QLabel(f"{_number(axis.minimum)}–{_number(axis.maximum)}")
            range_label.setObjectName("hint")
            tag_label = QLabel(axis.tag)
            tag_label.setFont(tabular_font())
            range_label.setFont(tabular_font())
            grid.addWidget(tag_label, row, 0)
            grid.addWidget(field, row, 1)
            grid.addWidget(range_label, row, 2)
        layout.addLayout(grid)

        self.filename_preview = QLabel()
        self.filename_preview.setObjectName("filenamePreview")
        self.filename_preview.setWordWrap(True)
        self.filename_preview.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        # A word-wrapped label in a top-level dialog does not pass its height-for-width
        # on: the layout would squeeze the axis rows instead of growing the window. The
        # label reserves its height explicitly (see _reserve_preview_height).
        self.filename_preview.installEventFilter(self)
        layout.addWidget(self.filename_preview)
        for box in self._boxes.values():
            box.valueChanged.connect(self._update_filename_preview)
        self._update_filename_preview()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def coordinates(self) -> tuple[tuple[str, float], ...]:
        return tuple((tag, box.value()) for tag, box in self._boxes.items())

    def _update_filename_preview(self) -> None:
        coordinates = self.coordinates()
        label = instance_label(coordinates)
        coordinates_by_tag = dict(coordinates)
        named_instance = next(
            (
                spec
                for spec in self._named_instances
                if spec.name
                and len(spec.coordinates) == len(coordinates_by_tag)
                and all(
                    tag in coordinates_by_tag and abs(coordinates_by_tag[tag] - value) < 0.0000005
                    for tag, value in spec.coordinates
                )
            ),
            None,
        )
        stem = instance_stem(
            self._input_path,
            named_instance.name if named_instance is not None else None,
            label,
        )
        file_name = f"{stem}{self._input_path.suffix}"
        self.filename_preview.setText(f"Output file: {_wrappable(file_name)}")
        self._reserve_preview_height()

    def _reserve_preview_height(self) -> None:
        """At least two lines, more if the text needs them at the label's width."""
        label = self.filename_preview
        label.ensurePolished()
        margins = label.contentsMargins()
        height = (
            PREVIEW_MIN_LINES * label.fontMetrics().lineSpacing() + margins.top() + margins.bottom()
        )
        if label.isVisible() and label.width() > 0:
            height = max(height, label.heightForWidth(label.width()))
        if label.minimumHeight() != height:
            label.setMinimumHeight(height)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.filename_preview and event.type() == QEvent.Type.Resize:
            self._reserve_preview_height()
        return super().eventFilter(watched, event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._reserve_preview_height()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._reserve_preview_height()


class _InstanceItem(QTreeWidgetItem):
    """An instance row. Sorting the tree orders the fonts; under each font the named
    instances always come first, in the font's order. Custom instances follow: sorted by
    their location (in the sort direction) when the tree is sorted by Location, otherwise
    in the order they were added."""

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        if tree is None or self.data(0, _ORDER_ROLE) is None or other.data(0, _ORDER_ROLE) is None:
            return super().__lt__(other)
        header = tree.header()
        ascending = header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
        by_location = header.sortIndicatorSection() == _LOCATION_COLUMN
        # Qt puts self first when self < other (ascending) or other < self (descending):
        # answer with the order the rows should have on screen.
        if ascending:
            return self._shown_before(other, ascending, by_location)
        return _InstanceItem._shown_before(other, self, ascending, by_location)

    def _shown_before(self, other: QTreeWidgetItem, ascending: bool, by_location: bool) -> bool:
        custom, other_custom = bool(self.data(0, _CUSTOM_ROLE)), bool(other.data(0, _CUSTOM_ROLE))
        if custom != other_custom:
            return not custom  # named instances first
        if custom and by_location:
            mine = _location_key(self.data(0, _SPEC_ROLE))
            theirs = _location_key(other.data(0, _SPEC_ROLE))
            if mine != theirs:
                return mine < theirs if ascending else mine > theirs
        return self.data(0, _ORDER_ROLE) < other.data(0, _ORDER_ROLE)


def _location_key(spec: InstanceSpec) -> tuple[float, ...]:
    """Axis values in axis order: compared as numbers, so 150 sorts before 1000."""
    return tuple(value for _tag, value in spec.coordinates)


class InstanceTree(QTreeWidget):
    """Variable fonts as parents, their exportable instances as checkable children."""

    paths_dropped = Signal(list)
    checksChanged = Signal()
    actionsChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("instanceTree")
        # Slashed zeros and tabular figures for every cell and the header.
        self.setFont(tabular_font(self.font()))
        self.header().setFont(tabular_font(self.header().font()))
        self.setAcceptDrops(True)
        self.setProperty("dragOver", "false")
        self.setColumnCount(5)
        self.setHeaderLabels(["Font / instance", "Format", "Outlines", "UPM", "Location"])
        for column in (1, 2):
            self.headerItem().setTextAlignment(
                column, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
            )
        self.headerItem().setTextAlignment(self._UPM_COLUMN, _UPM_ALIGNMENT)
        self.headerItem().setToolTip(
            _LOCATION_COLUMN,
            "Axis coordinates. Drag the Font / instance column divider to resize.",
        )
        self.setRootIsDecorated(True)
        self.setMouseTracking(True)
        self.setAlternatingRowColors(False)
        self.setIndentation(24)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setItemDelegate(InstanceRowDelegate(self))
        self.setUniformRowHeights(True)
        self.setTabKeyNavigation(False)
        self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.setSortingEnabled(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header = self.header()
        header.setFixedHeight(30)
        self._scrollbar_header = ScrollbarHeaderFiller(self, header)
        for column in (1, 2):
            self.setItemDelegateForColumn(column, InstanceBadgeDelegate(self))
        self.update_column_widths()
        # Font / instance is dragged; Location fills the rest (see FillColumnLayout).
        self._column_layout = FillColumnLayout(
            self,
            header,
            fill=0,
            fixed=self.FIXED_COLUMNS.values(),
            minimums={0: FIRST_COLUMN_MIN_WIDTH, _LOCATION_COLUMN: LOCATION_MIN_WIDTH},
            default_minimum=LOCATION_MIN_WIDTH,
        )
        header.resizeSection(_LOCATION_COLUMN, LOCATION_MIN_WIDTH)
        self.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._filter_text = ""
        self._hide_incompatible = False
        self._memory: dict[Path, _Memory] = {}
        self._branch_icons = {
            (expanded, hovered): material_icon(
                "expand_more" if expanded else "chevron_right",
                "text" if hovered else "text_muted",
                18,
            )
            for expanded in (False, True)
            for hovered in (False, True)
        }
        self._hovered_font = QPersistentModelIndex()
        self._pressed_font = QPersistentModelIndex()
        self.model().dataChanged.connect(lambda *_: self.viewport().update())
        # The solid "+ Instance" follows the current row (or its font): repaint both ends.
        self.currentItemChanged.connect(lambda *_: self.viewport().update())
        self.itemChanged.connect(self._on_item_changed)
        self.currentItemChanged.connect(lambda *_: self.actionsChanged.emit())
        self.customContextMenuRequested.connect(self._show_menu)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._delete_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self)
        self._delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._delete_shortcut.activated.connect(self.remove_custom)
        self._menu_shortcut = QShortcut(QKeySequence("Shift+F10"), self)
        self._menu_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._menu_shortcut.activated.connect(self._show_current_menu)
        self._insert_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Insert), self)
        self._insert_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._insert_shortcut.activated.connect(self._add_from_keyboard)

    # -- "+ Instance" row action -------------------------------------------------------
    # Painted by InstanceRowDelegate, no per-row widgets. add_action_rect() gives the
    # bounds to both the painting and the hit-test below.

    def _font_row(self, index: QModelIndex | QPersistentModelIndex) -> QModelIndex:
        """Column-0 index of the variable font row of ``index``, or an invalid index."""
        if not index.isValid():
            return QModelIndex()
        first = self.model().index(index.row(), 0, index.parent())
        if first.parent().isValid() or first.data(_PATH_ROLE) is None:
            return QModelIndex()
        return first

    def add_action_state(self, index: QModelIndex | QPersistentModelIndex) -> str | None:
        """ACTION_SOLID, ACTION_GHOST or None for the row of ``index``."""
        font = self._font_row(index)
        if not font.isValid():
            return None
        current = self._current_font()
        if current is not None and self.indexFromItem(current) == font:
            return ACTION_SOLID
        if self._hovered_font.isValid() and self._hovered_font == font:
            return ACTION_GHOST
        return None

    def add_action_rect_for(self, index: QModelIndex | QPersistentModelIndex) -> QRect:
        cell = self.model().index(index.row(), _LOCATION_COLUMN, index.parent())
        return add_action_rect(self.visualRect(cell))

    def is_add_action_pressed(self, index: QModelIndex | QPersistentModelIndex) -> bool:
        if not self._pressed_font.isValid():
            return False
        return self._pressed_font == self._font_row(index)

    def _add_action_at(self, position: QPoint) -> QModelIndex:
        """Font row whose visible "+ Instance" button is under ``position``."""
        index = self.indexAt(position)
        if index.column() != _LOCATION_COLUMN or self.add_action_state(index) is None:
            return QModelIndex()
        if not self.add_action_rect_for(index).contains(position):
            return QModelIndex()
        return self._font_row(index)

    def _update_location_cell(self, index: QModelIndex | QPersistentModelIndex) -> None:
        if index.isValid():
            cell = self.model().index(index.row(), _LOCATION_COLUMN, index.parent())
            self.viewport().update(self.visualRect(cell))

    def _set_hovered_font(self, index: QModelIndex) -> None:
        font = self._font_row(index)
        previous = self._hovered_font
        if previous == font:
            return
        self._hovered_font = QPersistentModelIndex(font)
        self._update_location_cell(previous)
        self._update_location_cell(font)

    def _update_action_cursor(self, position: QPoint) -> None:
        if self._add_action_at(position).isValid():
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().unsetCursor()

    def _add_from_keyboard(self) -> None:
        if self.can_add():
            self.add_custom()

    def viewportEvent(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Leave:
            self._set_hovered_font(QModelIndex())
            self.viewport().unsetCursor()
        elif (
            event.type() == QEvent.Type.ToolTip
            and isinstance(event, QHelpEvent)
            and self._add_action_at(event.pos()).isValid()
        ):
            QToolTip.showText(event.globalPos(), ADD_ACTION_TOOLTIP, self.viewport())
            return True
        elif event.type() == QEvent.Type.ToolTip and isinstance(event, QHelpEvent):
            location = self.elided_location_at(event.pos())
            if location:
                QToolTip.showText(event.globalPos(), location, self.viewport())
                return True
        return super().viewportEvent(event)

    def elided_location_at(self, pos: QPoint) -> str:
        """The full location of the instance under ``pos`` when its cell truncates it."""
        index = self.indexAt(pos)
        if (
            not index.isValid()
            or index.column() != _LOCATION_COLUMN
            or not index.parent().isValid()
        ):
            return ""
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        option = QStyleOptionViewItem()
        self.initViewItemOption(option)
        option.rect = self.visualRect(index)
        delegate = self.itemDelegateForIndex(index)
        if isinstance(delegate, QStyledItemDelegate):
            delegate.initStyleOption(option, index)
        style = self.style()
        margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, self) + 1
        room = (
            style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, option, self).width()
            - 2 * margin
        )
        return text if option.fontMetrics.horizontalAdvance(text) > room else ""

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        position = event.position().toPoint()
        self._set_hovered_font(self.indexAt(position))
        self._update_action_cursor(position)
        if self._pressed_font.isValid():
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        font = (
            self._add_action_at(event.position().toPoint())
            if event.button() == Qt.MouseButton.LeftButton
            else QModelIndex()
        )
        if not font.isValid():
            super().mousePressEvent(event)
            return
        # A ghost button makes its row current first; the press then shows on it.
        item = self.itemFromIndex(font)
        if item is not None and self._current_font() is not item:
            self.setCurrentItem(item)
        self._pressed_font = QPersistentModelIndex(font)
        self._update_location_cell(font)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if not self._pressed_font.isValid():
            super().mouseReleaseEvent(event)
            return
        pressed = self._pressed_font
        self._pressed_font = QPersistentModelIndex()
        self._update_location_cell(pressed)
        event.accept()
        if event.button() == Qt.MouseButton.LeftButton and pressed == self._add_action_at(
            event.position().toPoint()
        ):
            self.add_custom()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        # The second click of a quick double click presses the button again; it must
        # not expand or collapse the row.
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._add_action_at(event.position().toPoint()).isValid()
        ):
            self.mousePressEvent(event)
            return
        super().mouseDoubleClickEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        helper = getattr(self, "_scrollbar_header", None)
        if helper is not None:
            helper.handle_event(watched, event)
        return super().eventFilter(watched, event)

    def drawRow(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        super().drawRow(painter, option, index)
        painter.save()
        painter.setPen(QColor(colors().row_separator))
        painter.drawLine(0, option.rect.bottom(), self.viewport().width(), option.rect.bottom())
        current = self.currentIndex()
        if self.hasFocus() and current.row() == index.row() and current.parent() == index.parent():
            painter.fillRect(0, option.rect.top(), 2, option.rect.height(), QColor(colors().accent))
        painter.restore()

    def drawBranches(
        self, painter: QPainter, rect: QRect, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        painter.fillRect(rect, QColor(font_row_background(self, index)))
        super().drawBranches(painter, rect, index)
        if not self.model().hasChildren(index):
            return
        icon_rect = QRect(
            rect.right() - self.indentation() + 1 + BRANCH_ICON_OFFSET,
            rect.top(),
            self.indentation(),
            rect.height(),
        )
        icon_hovered = icon_rect.contains(self.viewport().mapFromGlobal(QCursor.pos()))
        icon = self._branch_icons[(self.isExpanded(index), icon_hovered)]
        icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter)

    @property
    def _muted_color(self) -> QColor:
        return QColor(colors().text_disabled)

    def refresh_theme(self) -> None:
        """Re-apply the item colors set when the rows were added (after a theme switch)."""
        muted = self._muted_color
        location = QColor(colors().text_muted)
        was_blocked = self.blockSignals(True)
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if item is None:
                continue
            if item.data(0, _PATH_ROLE) is None:  # skipped font
                for column in range(self.columnCount()):
                    item.setForeground(column, muted)
            else:
                item.setForeground(_LOCATION_COLUMN, location)
        self.blockSignals(was_blocked)
        self.viewport().update()

    def add_skipped(self, path: Path, label: str, reason: str, info: FontInfo) -> None:
        """List a font that cannot be used, greyed out and with the reason."""
        item = QTreeWidgetItem(self._row_texts(label, info, reason))
        item.setFont(self._UPM_COLUMN, tabular_font())
        item.setTextAlignment(self._UPM_COLUMN, _UPM_ALIGNMENT)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        item.setToolTip(0, wrap_tip(f"{path}\n{reason}"))
        item.setData(0, _SEARCH_ROLE, f"{path} {reason}")
        for column in range(self.columnCount()):
            item.setForeground(column, self._muted_color)
        self.addTopLevelItem(item)
        self._apply_skipped_filter(item)
        self.viewport().update()
        self.checksChanged.emit()

    def add_font(
        self, path: Path, label: str, info: FontInfo, checked_by_default: bool = True
    ) -> None:
        remembered = self._memory.get(path)
        checked, custom = remembered if remembered else (None, [])
        was_blocked = self.blockSignals(True)
        parent = QTreeWidgetItem(self._row_texts(label, info, ""))
        parent.setFont(self._UPM_COLUMN, tabular_font())
        parent.setTextAlignment(self._UPM_COLUMN, _UPM_ALIGNMENT)
        parent.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsAutoTristate
        )
        parent.setToolTip(0, wrap_tip(str(path)))
        parent.setForeground(_LOCATION_COLUMN, QColor(colors().text_muted))
        # Right-aligned so the summary stays put when "+ Instance" appears beside it.
        parent.setTextAlignment(
            _LOCATION_COLUMN, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        parent.setData(0, _PATH_ROLE, path)
        parent.setData(0, _SEARCH_ROLE, str(path))
        parent.setData(0, _AXES_ROLE, info.axes)
        parent.setData(0, _OUTLINES_ROLE, info.outlines)
        self.addTopLevelItem(parent)
        named = [InstanceSpec(i.coordinates, i.name) for i in info.instances]
        for spec in named or [InstanceSpec(())]:
            self._add_child(
                parent,
                spec,
                custom=False,
                checked=checked_by_default if checked is None else spec in checked,
            )
        for spec in custom:
            self._add_child(parent, spec, custom=True, checked=checked is None or spec in checked)
        self._update_summary(parent)
        self._fit_location_column()
        self.blockSignals(was_blocked)
        self._apply_font_filter(parent)
        self.viewport().update()
        self.checksChanged.emit()

    def set_font_checked(self, path: Path, checked: bool) -> None:
        font = next((item for item in self._fonts() if item.data(0, _PATH_ROLE) == path), None)
        if font is None:
            return
        was_blocked = self.blockSignals(True)
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for child in self._children(font):
            child.setCheckState(0, state)
        self._update_summary(font)
        self._remember(font)
        self.blockSignals(was_blocked)
        self.checksChanged.emit()

    _UPM_COLUMN = 3
    # Logical indexes of the columns sized from their content (see column_widths).
    FIXED_COLUMNS = {"format": 1, "outlines": 2, "upm": _UPM_COLUMN}

    def update_column_widths(self) -> None:
        fixed_column_widths(self, self.header(), self.FIXED_COLUMNS)

    def event(self, event: QEvent) -> bool:
        # Format, Outlines and UPM widths depend on the font metrics.
        if event.type() in METRIC_EVENTS:
            QTimer.singleShot(0, self, self.update_column_widths)
        return super().event(event)

    def _fit_location_column(self) -> None:
        """Location fits its content within its bounds; Font / instance takes the rest."""
        width = max(self.sizeHintForColumn(_LOCATION_COLUMN), LOCATION_MIN_WIDTH)
        self.header().resizeSection(_LOCATION_COLUMN, min(width, LOCATION_MAX_WIDTH))

    @staticmethod
    def _row_texts(label: str, info: FontInfo, location: str) -> list[str]:
        upm = "Mixed" if info.upm is None else str(info.upm)
        return [label, info.format, info.outlines, upm, location]

    def _add_child(
        self, parent: QTreeWidgetItem, spec: InstanceSpec, custom: bool, checked: bool
    ) -> QTreeWidgetItem:
        name = spec.name or ("Default instance" if not spec.coordinates else "Custom instance")
        location = location_text(spec.coordinates)
        child = _InstanceItem([name, "", "", "", location])
        child.setData(
            0,
            _ORDER_ROLE,
            max((row.data(0, _ORDER_ROLE) for row in self._children(parent)), default=-1) + 1,
        )
        child.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        child.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        child.setData(0, _SPEC_ROLE, spec)
        child.setData(0, _CUSTOM_ROLE, custom)
        child.setFont(_LOCATION_COLUMN, tabular_font())
        if custom:
            for column in range(self.columnCount()):
                child.setToolTip(column, CUSTOM_INSTANCE_TOOLTIP)
        parent.addChild(child)
        return child

    def set_hide_incompatible(self, hide: bool) -> None:
        """Show or hide fonts that cannot be exported as variable instances."""
        self._hide_incompatible = hide
        self.set_filter(self._filter_text)

    def set_filter(self, text: str) -> None:
        """Filter fonts and instances while keeping a matching font's children visible."""
        self._filter_text = text.casefold().strip()
        for font in self._fonts():
            self._apply_font_filter(font)
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if item is not None and item.data(0, _PATH_ROLE) is None:
                self._apply_skipped_filter(item)

    def _apply_font_filter(self, font: QTreeWidgetItem) -> None:
        font_match = self._matches(font)
        child_match = False
        for child in self._children(font):
            matches = not self._filter_text or font_match or self._matches(child)
            child.setHidden(not matches)
            child_match = child_match or matches
        font.setHidden(bool(self._filter_text) and not font_match and not child_match)

    def _apply_skipped_filter(self, item: QTreeWidgetItem) -> None:
        item.setHidden(
            self._hide_incompatible or (bool(self._filter_text) and not self._matches(item))
        )

    def _matches(self, item: QTreeWidgetItem) -> bool:
        if not self._filter_text:
            return True
        texts = [item.text(column) for column in range(self.columnCount())]
        texts.append(item.data(0, _SEARCH_ROLE) or "")
        return self._filter_text in " ".join(texts).casefold()

    def _update_summary(self, parent: QTreeWidgetItem) -> None:
        total = parent.childCount()
        selected = sum(c.checkState(0) == Qt.CheckState.Checked for c in self._children(parent))
        parent.setText(_LOCATION_COLUMN, f"{selected} of {total} selected")

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        parent = item.parent() or item
        was_blocked = self.blockSignals(True)
        self._update_summary(parent)
        self.blockSignals(was_blocked)
        self._remember(parent)
        self.checksChanged.emit()

    def _fonts(self) -> list[QTreeWidgetItem]:
        items = (self.topLevelItem(i) for i in range(self.topLevelItemCount()))
        return [item for item in items if item and item.data(0, _PATH_ROLE) is not None]

    @staticmethod
    def _children(font: QTreeWidgetItem) -> list[QTreeWidgetItem]:
        return [item for i in range(font.childCount()) if (item := font.child(i))]

    def _remember(self, font: QTreeWidgetItem) -> None:
        path = font.data(0, _PATH_ROLE)
        if path is None:
            return
        children = self._children(font)
        self._memory[path] = (
            {c.data(0, _SPEC_ROLE) for c in children if c.checkState(0) == Qt.CheckState.Checked},
            [c.data(0, _SPEC_ROLE) for c in children if c.data(0, _CUSTOM_ROLE)],
        )

    def clear_fonts(self) -> None:
        """Drop the rows for a rescan while keeping the user's choices."""
        was_blocked = self.blockSignals(True)
        self.clear()
        self.blockSignals(was_blocked)
        self.viewport().update()
        self.checksChanged.emit()

    def forget(self) -> None:
        self._memory.clear()

    def selection(self) -> tuple[tuple[Path, tuple[InstanceSpec, ...]], ...]:
        result = []
        for font in self._fonts():
            specs = tuple(
                c.data(0, _SPEC_ROLE)
                for c in self._children(font)
                if c.checkState(0) == Qt.CheckState.Checked
            )
            if specs:
                result.append((font.data(0, _PATH_ROLE), specs))
        return tuple(result)

    def selected_paths(self) -> list[Path]:
        return [path for path, _ in self.selection()]

    def instance_count(self) -> int:
        return sum(len(specs) for _, specs in self.selection())

    def font_count(self) -> int:
        return len(self._fonts())

    def skipped_count(self) -> int:
        return self.topLevelItemCount() - len(self._fonts())

    def list_status_counts(self) -> tuple[int, int]:
        shown = 0
        hidden = 0
        for index in range(self.topLevelItemCount()):
            item = self.topLevelItem(index)
            if item is None:
                continue
            if not item.isHidden():
                shown += 1
            elif (
                self._hide_incompatible and item.data(0, _PATH_ROLE) is None and self._matches(item)
            ):
                hidden += 1
        return shown, hidden

    def selected_outlines(self) -> set[str]:
        """Outline kinds ("TrueType"/"PostScript") of the fonts with selected instances."""
        return {
            font.data(0, _OUTLINES_ROLE)
            for font in self._fonts()
            if any(c.checkState(0) == Qt.CheckState.Checked for c in self._children(font))
        }

    def auto_expand(self) -> None:
        """Show the instances right away when there is a single variable font."""
        fonts = self._fonts()
        if len(fonts) == 1:
            fonts[0].setExpanded(True)

    def _set_all_expanded(self, expanded: bool) -> None:
        anchor = self.indexAt(QPoint(self.viewport().width() // 2, 0))
        if not expanded and anchor.parent().isValid():
            anchor = anchor.parent()
        persistent = QPersistentModelIndex(anchor)
        if expanded:
            super().expandAll()
        else:
            super().collapseAll()
        if persistent.isValid():
            self.scrollTo(persistent, QAbstractItemView.ScrollHint.PositionAtTop)

    def expandAll(self) -> None:
        self._set_all_expanded(True)

    def collapseAll(self) -> None:
        self._set_all_expanded(False)

    def check_state(self) -> Qt.CheckState | None:
        states = {c.checkState(0) for font in self._fonts() for c in self._children(font)}
        if not states:
            return None
        if len(states) > 1:
            return Qt.CheckState.PartiallyChecked
        return states.pop()

    def set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        was_blocked = self.blockSignals(True)
        for font in self._fonts():
            for child in self._children(font):
                child.setCheckState(0, state)
            self._update_summary(font)
            self._remember(font)
        self.blockSignals(was_blocked)
        self.checksChanged.emit()

    def _current_font(self) -> QTreeWidgetItem | None:
        item = self.currentItem()
        if item is None:
            return None
        font = item.parent() or item
        return font if font.data(0, _PATH_ROLE) is not None else None

    def can_add(self) -> bool:
        return self._current_font() is not None

    def can_remove(self) -> bool:
        item = self.currentItem()
        return item is not None and bool(item.data(0, _CUSTOM_ROLE))

    def add_custom(self) -> None:
        self._edit_or_add_custom()

    def edit_custom(self) -> None:
        item = self.currentItem()
        if item is not None and item.data(0, _CUSTOM_ROLE):
            self._edit_or_add_custom(item)

    def _edit_or_add_custom(self, editing: QTreeWidgetItem | None = None) -> None:
        font = self._current_font()
        if font is None:
            return
        axes: tuple[AxisInfo, ...] = font.data(0, _AXES_ROLE)
        if not axes:
            return
        named_instances = tuple(
            child.data(0, _SPEC_ROLE)
            for child in self._children(font)
            if not child.data(0, _CUSTOM_ROLE) and child.data(0, _SPEC_ROLE).name is not None
        )
        input_path: Path = font.data(0, _PATH_ROLE)
        dialog = CustomInstanceDialog(
            axes,
            named_instances,
            font.text(0),
            input_path,
            self.window(),
            editing.data(0, _SPEC_ROLE).coordinates if editing is not None else None,
        )
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            spec = InstanceSpec(dialog.coordinates())
        finally:
            # A child of the window: without this, every closed dialog stays alive
            # (hidden) until the window is destroyed.
            dialog.deleteLater()
        existing = next(
            (
                c
                for c in self._children(font)
                if c is not editing and c.data(0, _SPEC_ROLE).coordinates == spec.coordinates
            ),
            None,
        )
        if existing is not None and editing is not None:
            QMessageBox.information(
                self.window(),
                "Instance already exists",
                f'These values match the existing instance "{existing.text(0)}".',
            )
            return
        was_blocked = self.blockSignals(True)
        if existing is not None:
            existing.setCheckState(0, Qt.CheckState.Checked)
            target = existing
            existing_spec: InstanceSpec = existing.data(0, _SPEC_ROLE)
            if existing_spec.name is not None:
                QMessageBox.information(
                    self.window(),
                    "Named instance already exists",
                    f'These values match the named instance "{existing.text(0)}". '
                    "The existing instance has been selected.",
                )
        elif editing is not None:
            was_checked = editing.checkState(0) == Qt.CheckState.Checked
            editing.setText(0, "Custom instance")
            editing.setText(_LOCATION_COLUMN, location_text(spec.coordinates))
            editing.setData(0, _SPEC_ROLE, spec)
            editing.setCheckState(
                0, Qt.CheckState.Checked if was_checked else Qt.CheckState.Unchecked
            )
            target = editing
        else:
            target = self._add_child(font, spec, custom=True, checked=True)
        font.setExpanded(True)
        self._update_summary(font)
        self.blockSignals(was_blocked)
        self._remember(font)
        self.setCurrentItem(target)
        self.set_filter(self._filter_text)
        self.checksChanged.emit()

    @staticmethod
    def row_kind(item: QTreeWidgetItem | None) -> str | None:
        """ROW_FONT, ROW_CUSTOM, ROW_INSTANCE, or None for a skipped font (or no row)."""
        if item is None:
            return None
        if item.parent() is None:
            return ROW_FONT if item.data(0, _PATH_ROLE) is not None else None
        return ROW_CUSTOM if item.data(0, _CUSTOM_ROLE) else ROW_INSTANCE

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        # A font row expands or collapses (QTreeView's expandsOnDoubleClick).
        if self.row_kind(item) == ROW_CUSTOM:
            self.setCurrentItem(item)
            self.edit_custom()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        ):
            self._activate_current()
            event.accept()
            return
        super().keyPressEvent(event)

    def _activate_current(self) -> None:
        """Enter: a font expands or collapses, a custom instance opens Edit, others nothing."""
        item = self.currentItem()
        kind = self.row_kind(item)
        if item is None:
            return
        if kind == ROW_FONT:
            item.setExpanded(not item.isExpanded())
        elif kind == ROW_CUSTOM:
            self.edit_custom()

    def remove_custom(self) -> None:
        item = self.currentItem()
        parent = item.parent() if item is not None else None
        if item is None or parent is None or not item.data(0, _CUSTOM_ROLE):
            return
        was_blocked = self.blockSignals(True)
        parent.removeChild(item)
        self._update_summary(parent)
        self.blockSignals(was_blocked)
        self._remember(parent)
        self.actionsChanged.emit()
        self.checksChanged.emit()

    def _show_menu(self, position: QPoint) -> None:
        item = self.itemAt(position)
        if item is None:
            return
        self.setCurrentItem(item)
        # Only the actions that apply to the row; named and default instances have none.
        kind = self.row_kind(item)
        if kind == ROW_FONT:
            entries = [("Add custom instance…", self.add_custom)]
        elif kind == ROW_CUSTOM:
            entries = [
                ("Edit custom instance…", self.edit_custom),
                ("Remove instance", self.remove_custom),
            ]
        else:
            return
        menu = QMenu(self)
        actions = [(menu.addAction(label), handler) for label, handler in entries]
        chosen = menu.exec(self.viewport().mapToGlobal(position))
        for action, handler in actions:
            if chosen is action:
                handler()
                break

    def _show_current_menu(self) -> None:
        item = self.currentItem()
        if item is not None:
            self.scrollToItem(item)
            self._show_menu(self.visualItemRect(item).center())

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        accept_local_files(event)
        set_drag_over(self, event.isAccepted())

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        accept_local_files(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        set_drag_over(self, False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        set_drag_over(self, False)
        paths = dropped_paths(event)
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()
