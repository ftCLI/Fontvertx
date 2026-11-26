"""Model-backed font table, filtering and scan coordination."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QRectF,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPalette,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QTreeView,
)

from fontvertx.gui.scanner import ScanWorker, Source
from fontvertx.gui.styles import LIGHT, chip_font, tabular_font
from fontvertx.gui.tooltips import wrap_tip
from fontvertx.gui.widgets import FileTable
from fontvertx.inspection import FontInfo, incompatibility

_PATH_ROLE = Qt.ItemDataRole.UserRole
_REASON_ROLE = Qt.ItemDataRole.UserRole + 1
_INFO_ROLE = Qt.ItemDataRole.UserRole + 2
_ROOT_INDEX = QModelIndex()


@dataclass
class FontRow:
    path: Path
    label: str
    format: str
    outlines: str
    upm: str
    info: FontInfo
    checked: bool
    reason: str | None = None


class FontTableModel(QAbstractTableModel):
    HEADERS = ("Name", "Format", "Outlines", "UPM", "Family", "Style")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.rows: list[FontRow] = []

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = 0):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        if role == Qt.ItemDataRole.TextAlignmentRole and orientation == Qt.Orientation.Horizontal:
            if section in (0, 4, 5):
                return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            if section == 3:
                return Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        return None

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = 0):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return (row.label, row.format, row.outlines, row.upm, row.info.family, row.info.style)[
                column
            ]
        if role == Qt.ItemDataRole.TextAlignmentRole and column == 3:
            return Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.FontRole and column == 3:
            return tabular_font()
        if role == Qt.ItemDataRole.CheckStateRole and column == 0:
            checked = row.checked and row.reason is None
            return Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        if role == _PATH_ROLE:
            return str(row.path)
        if role == _REASON_ROLE:
            return row.reason
        if role == _INFO_ROLE:
            return row.info
        if role == Qt.ItemDataRole.ToolTipRole:
            if column != 0:
                return None
            # The name is already in the cell: only the path, and why the row is unusable.
            text = str(row.path)
            return wrap_tip(f"{text}\n{row.reason}" if row.reason else text)
        if role == Qt.ItemDataRole.ForegroundRole and row.reason:
            view = self.parent()
            muted = view.muted_color if isinstance(view, FileTable) else QColor(LIGHT.text_disabled)
            return QBrush(muted)
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        row = self.rows[index.row()]
        if index.column() == 0 and row.reason is None:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index: QModelIndex | QPersistentModelIndex, value, role: int = 0) -> bool:
        if (
            not index.isValid()
            or index.column() != 0
            or role != Qt.ItemDataRole.CheckStateRole
            or self.rows[index.row()].reason is not None
        ):
            return False
        checked = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
        row = self.rows[index.row()]
        if row.checked == checked:
            return True
        row.checked = checked
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        return True

    def add_font(
        self,
        path: Path,
        label: str,
        info: FontInfo,
        checked: bool,
        profile: tuple[str | None, bool],
    ) -> None:
        conversion, _ = profile
        reason = incompatibility(info, conversion) if conversion is not None else None
        row = FontRow(
            path,
            label,
            f"TTC ({info.num_fonts})" if info.collection else info.format,
            info.outlines,
            "Mixed" if info.upm is None else str(info.upm),
            info,
            checked,
            reason,
        )
        position = len(self.rows)
        self.beginInsertRows(QModelIndex(), position, position)
        self.rows.append(row)
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self.rows.clear()
        self.endResetModel()

    def set_checks(self, source_rows: list[int], checked: bool) -> None:
        changed_rows = []
        for source_row in source_rows:
            row = self.rows[source_row]
            if row.reason is None and row.checked != checked:
                row.checked = checked
                changed_rows.append(source_row)
        if changed_rows:
            self.dataChanged.emit(
                self.index(min(changed_rows), 0),
                self.index(max(changed_rows), 0),
                [Qt.ItemDataRole.CheckStateRole],
            )

    def update_compatibility(self, profile: tuple[str | None, bool]) -> None:
        conversion, _ = profile
        for row in self.rows:
            row.reason = incompatibility(row.info, conversion) if conversion is not None else None
        if self.rows:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self.rows) - 1, self.columnCount() - 1),
                [
                    Qt.ItemDataRole.DisplayRole,
                    Qt.ItemDataRole.ToolTipRole,
                    Qt.ItemDataRole.ForegroundRole,
                    Qt.ItemDataRole.CheckStateRole,
                ],
            )


def is_group_row(view: QAbstractItemView, index: QModelIndex | QPersistentModelIndex) -> bool:
    first = index.sibling(index.row(), 0)
    return (
        isinstance(view, QTreeView)
        and not first.parent().isValid()
        and view.model().hasChildren(first)
    )


def font_row_background(view: QAbstractItemView, index: QModelIndex | QPersistentModelIndex) -> str:
    if view.property("dragOver") == "true":
        return LIGHT.row_selected_a
    selection = view.selectionModel()
    if selection is not None and selection.isRowSelected(index.row(), index.parent()):
        return (
            LIGHT.row_selection if view.window().isActiveWindow() else LIGHT.row_selection_inactive
        )
    point = view.viewport().mapFromGlobal(QCursor.pos())
    if view.viewport().rect().contains(point):
        hovered = view.indexAt(point)
        if not hovered.isValid():
            hovered = view.indexAt(QPoint(view.viewport().width() // 2, point.y()))
        if (
            hovered.isValid()
            and hovered.row() == index.row()
            and hovered.parent() == index.parent()
        ):
            return LIGHT.table_header if is_group_row(view, index) else LIGHT.row_hover
    return LIGHT.list_alt if is_group_row(view, index) else LIGHT.surface


class FontRowDelegate(QStyledItemDelegate):
    def paint_table_row_edges(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        """Row separator and keyboard-focus bar of a table row, drawn cell by cell.

        QTableView has no ``drawRow`` hook; the tree draws the same decorations there.
        """
        view = self.parent()
        if not isinstance(view, QTableView):
            return
        rect = option.rect
        painter.save()
        painter.setPen(QColor(LIGHT.row_separator))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        if (
            index.column() == 0
            and view.hasFocus()
            and view.currentIndex().isValid()
            and view.currentIndex().row() == index.row()
        ):
            painter.fillRect(rect.left(), rect.top(), 2, rect.height(), QColor(LIGHT.accent))
        painter.restore()

    def paint_row_tail(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        """The part of a table row past its last column, painted like an empty cell.

        ``option`` is the view's item option for the strip (rect and state) and ``index``
        the row's last cell: the background goes through the same path as the cells
        (hover, drag tint, stylesheet selection colors), without any content.
        """
        display_option = QStyleOptionViewItem(option)
        self.initStyleOption(display_option, index)
        self.prepare_row(display_option, index)
        display_option.text = ""
        display_option.icon = QIcon()
        display_option.features &= ~(
            QStyleOptionViewItem.ViewItemFeature.HasDisplay
            | QStyleOptionViewItem.ViewItemFeature.HasDecoration
            | QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        )
        if display_option.backgroundBrush.style() != Qt.BrushStyle.NoBrush:
            painter.fillRect(display_option.rect, display_option.backgroundBrush)
        if display_option.widget is not None:
            display_option.widget.style().drawControl(
                QStyle.ControlElement.CE_ItemViewItem,
                display_option,
                painter,
                display_option.widget,
            )
        rect = option.rect
        painter.save()
        painter.setPen(QColor(LIGHT.row_separator))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        painter.restore()

    def prepare_row(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        view = self.parent()
        if not isinstance(view, QAbstractItemView):
            return
        option.backgroundBrush = QBrush(QColor(font_row_background(view, index)))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        group = is_group_row(view, index)
        if group and index.column() == 0:
            option.font.setWeight(QFont.Weight.DemiBold)
        state = index.sibling(index.row(), 0).data(Qt.ItemDataRole.CheckStateRole)
        text_column = index.column() == 0 or (
            index.column() == 4 if isinstance(view, QTreeView) else index.column() in (4, 5)
        )
        if selected or (group and index.column() == 0):
            option.palette.setColor(QPalette.ColorRole.Text, QColor(LIGHT.text))
            option.palette.setColor(QPalette.ColorRole.HighlightedText, QColor(LIGHT.text))
        elif (
            text_column
            and not group
            and state in (Qt.CheckState.Unchecked, 0)
            and (isinstance(view, QTreeView) or not index.data(_REASON_ROLE))
        ):
            option.palette.setColor(QPalette.ColorRole.Text, QColor(LIGHT.text_dim))

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        display_option = QStyleOptionViewItem(option)
        self.initStyleOption(display_option, index)
        self.prepare_row(display_option, index)
        if display_option.backgroundBrush.style() != Qt.BrushStyle.NoBrush:
            painter.fillRect(display_option.rect, display_option.backgroundBrush)
        if display_option.widget is not None:
            display_option.widget.style().drawControl(
                QStyle.ControlElement.CE_ItemViewItem,
                display_option,
                painter,
                display_option.widget,
            )
        self.paint_table_row_edges(painter, option, index)


class FontNameDelegate(FontRowDelegate):
    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        reason = index.data(_REASON_ROLE)
        display_option = QStyleOptionViewItem(option)
        if reason:
            display_option.state &= ~QStyle.StateFlag.State_Enabled
        super().paint(painter, display_option, index)
        if not isinstance(reason, str) or not reason:
            return
        self.initStyleOption(display_option, index)
        view = self.parent()
        if not isinstance(view, FileTable):
            return
        rect = view.style().subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, display_option, view
        )
        metrics = display_option.fontMetrics
        name_width = metrics.horizontalAdvance(str(index.data(Qt.ItemDataRole.DisplayRole) or ""))
        rect.setLeft(rect.left() + name_width + 12)
        rect.adjust(0, 0, -4, 0)
        if rect.width() < 60:
            return
        text = metrics.elidedText(reason, Qt.TextElideMode.ElideRight, rect.width())
        painter.save()
        painter.setClipRect(option.rect)
        painter.setFont(display_option.font)
        painter.setPen(QColor(LIGHT.text_muted))
        painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()


class FontBadgeDelegate(FontRowDelegate):
    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        display_option = QStyleOptionViewItem(option)
        self.initStyleOption(display_option, index)
        self.prepare_row(display_option, index)
        text = display_option.text
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
        self.paint_table_row_edges(painter, option, index)
        if not text:
            return

        # Format chips: monospaced, pill-shaped, accent on tint.
        background = QColor(LIGHT.accent_tint)
        foreground = QColor(LIGHT.accent)
        font = chip_font()
        metrics = QFontMetrics(font)
        max_text_width = max(0, option.rect.width() - 20)
        visible_text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, max_text_width)
        badge_width = min(
            metrics.horizontalAdvance(visible_text) + 12, max(0, option.rect.width() - 8)
        )
        badge_height = min(19, max(0, option.rect.height() - 4))
        badge = QRect(
            option.rect.center().x() - badge_width // 2,
            option.rect.center().y() - badge_height // 2,
            badge_width,
            badge_height,
        )

        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        radius = badge.height() / 2
        painter.drawRoundedRect(QRectF(badge), radius, radius)
        painter.setFont(font)
        painter.setPen(foreground)
        painter.drawText(
            badge.adjusted(6, 0, -6, 0),
            Qt.AlignmentFlag.AlignCenter,
            visible_text,
        )
        painter.restore()


class FontFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.hide_incompatible = False
        self.setFilterKeyColumn(-1)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def filterAcceptsRow(
        self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex
    ) -> bool:
        if not super().filterAcceptsRow(source_row, source_parent):
            return False
        if not self.hide_incompatible:
            return True
        model = self.sourceModel()
        index = model.index(source_row, 0, source_parent) if model is not None else QModelIndex()
        return not index.isValid() or index.data(_REASON_ROLE) is None

    def hidden_incompatible_count(self) -> int:
        if not self.hide_incompatible:
            return 0
        model = self.sourceModel()
        if model is None:
            return 0
        parent = QModelIndex()
        return sum(
            1
            for row in range(model.rowCount(parent))
            if super(FontFilterProxyModel, self).filterAcceptsRow(row, parent)
            and model.index(row, 0, parent).data(_REASON_ROLE) is not None
        )

    def lessThan(
        self,
        left: QModelIndex | QPersistentModelIndex,
        right: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        left_value = str(left.data(Qt.ItemDataRole.DisplayRole) or "")
        right_value = str(right.data(Qt.ItemDataRole.DisplayRole) or "")
        if left.column() == 3:
            try:
                return int(left_value) < int(right_value)
            except ValueError:
                pass
        return left_value.casefold() < right_value.casefold()


class FontFileList(QObject):
    """Own the model-backed font table and its asynchronous scan."""

    progress = Signal(int, int)
    font_found = Signal(object, object)
    scan_finished = Signal()
    scan_failed = Signal(str)

    def __init__(
        self,
        view: FileTable,
        profile: Callable[[], tuple[str | None, bool]],
    ) -> None:
        super().__init__(view)
        self.view = view
        self.profile = profile
        self.model = FontTableModel(view)
        self.proxy = FontFilterProxyModel(view)
        self.proxy.setSourceModel(self.model)
        self.view.setModel(self.proxy)
        self.proxy.dataChanged.connect(lambda *_: self.view.viewport().update())
        self.view.setItemDelegate(FontRowDelegate(self.view))
        self.view.setItemDelegateForColumn(0, FontNameDelegate(self.view))
        for column in (1, 2):
            self.view.setItemDelegateForColumn(column, FontBadgeDelegate(self.view))
        self.view.configure_columns()
        self.view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._worker: ScanWorker | None = None
        self._retired_workers: list[ScanWorker] = []
        self._seen: set[Path] = set()

    @property
    def scanning(self) -> bool:
        return self._worker is not None

    @property
    def row_count(self) -> int:
        return len(self.model.rows)

    def start(self, sources: list[Source]) -> None:
        self.stop()
        self._seen.clear()
        worker = ScanWorker(sources)
        self._worker = worker
        # Lambdas have no receiver thread affinity: force queued delivery to the GUI thread.
        queued = Qt.ConnectionType.QueuedConnection
        worker.progress.connect(
            lambda done, total, w=worker: self._on_progress(w, done, total), queued
        )
        worker.font_found.connect(
            lambda path, info, w=worker: self._on_font_found(w, path, info), queued
        )
        worker.failed.connect(lambda message, w=worker: self._on_failed(w, message), queued)
        worker.finished.connect(lambda w=worker: self._on_finished(w), queued)
        worker.start()

    def stop(self) -> None:
        worker = self._worker
        if worker is None:
            return
        self._worker = None
        worker.requestInterruption()
        # Retire the worker even when it has been started but isRunning() is still False,
        # otherwise shutdown() would not wait for it and the QThread could be destroyed
        # while its thread is starting up.
        if not worker.isFinished():
            self._retired_workers.append(worker)

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.requestInterruption()

    def shutdown(self) -> None:
        self.stop()
        for worker in self._retired_workers:
            worker.wait()
        self._retired_workers.clear()

    def clear(self) -> None:
        self.model.clear()

    def add_font(self, path: Path, label: str, info: FontInfo, checked: bool) -> None:
        self.model.add_font(path, label, info, checked, self.profile())

    def apply_compatibility(self, *_: object) -> None:
        profile = self.profile()
        self.model.update_compatibility(profile)
        # Qt docs: change the filter parameters after beginFilterChange().
        if hasattr(self.proxy, "beginFilterChange"):
            self.proxy.beginFilterChange()
            self.proxy.hide_incompatible = profile[1]
            self.proxy.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.proxy.hide_incompatible = profile[1]
            self.proxy.invalidateFilter()

    def rows(self) -> Iterator[FontRow]:
        return iter(self.model.rows)

    def path_for_index(self, index: QModelIndex) -> Path:
        source = self.proxy.mapToSource(index)
        if not source.isValid():
            raise ValueError("The index does not map to a font row.")
        return self.model.rows[source.row()].path

    def index_for_path(self, path: Path) -> QModelIndex:
        for source_row, row in enumerate(self.model.rows):
            if row.path == path:
                return self.proxy.mapFromSource(self.model.index(source_row, 0))
        return QModelIndex()

    def is_visible(self, path: Path) -> bool:
        return self.index_for_path(path).isValid()

    def selected_paths(self) -> list[Path]:
        return [
            row.path
            for proxy_row in range(self.proxy.rowCount())
            if (
                (source := self.proxy.mapToSource(self.proxy.index(proxy_row, 0))).isValid()
                and (row := self.model.rows[source.row()]).checked
                and row.reason is None
            )
        ]

    def remember_checks(self) -> dict[Path, bool]:
        return {row.path: row.checked for row in self.model.rows}

    def set_visible_checks(self, checked: bool) -> None:
        source_rows = []
        for proxy_row in range(self.proxy.rowCount()):
            proxy_index = self.proxy.index(proxy_row, 0)
            source_rows.append(self.proxy.mapToSource(proxy_index).row())
        self.model.set_checks(source_rows, checked)

    def compatible_count(self) -> int:
        return sum(1 for row in self.model.rows if row.reason is None)

    def visible_check_state(self) -> Qt.CheckState | None:
        compatible = 0
        checked = 0
        for proxy_row in range(self.proxy.rowCount()):
            source = self.proxy.mapToSource(self.proxy.index(proxy_row, 0))
            if not source.isValid():
                continue
            row = self.model.rows[source.row()]
            if row.reason is None:
                compatible += 1
                checked += row.checked
        if compatible == 0:
            return None
        if checked == 0:
            return Qt.CheckState.Unchecked
        if checked == compatible:
            return Qt.CheckState.Checked
        return Qt.CheckState.PartiallyChecked

    def _on_progress(self, worker: ScanWorker, done: int, total: int) -> None:
        if worker is self._worker:
            self.progress.emit(done, total)

    def _on_font_found(self, worker: ScanWorker, path: Path, info: FontInfo) -> None:
        if worker is self._worker and path not in self._seen:
            self._seen.add(path)
            self.font_found.emit(path, info)

    def _on_failed(self, worker: ScanWorker, message: str) -> None:
        if worker is self._worker:
            self.scan_failed.emit(message)

    def _on_finished(self, worker: ScanWorker) -> None:
        worker.wait()
        for signal in (worker.progress, worker.font_found, worker.failed, worker.finished):
            signal.disconnect()
        if worker in self._retired_workers:
            self._retired_workers.remove(worker)
            return
        if worker is not self._worker:
            return
        self._worker = None
        self.scan_finished.emit()
