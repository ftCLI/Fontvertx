"""Incremental, selectable conversion log with level-aware rendering."""

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QKeyEvent, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QWidget,
)

from fontvertx.gui.logs import LogEntry
from fontvertx.gui.styles import colors, mono_font

ENTRY_ROLE = Qt.ItemDataRole.UserRole


class LogDelegate(QStyledItemDelegate):
    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        parent = self.parent()
        if isinstance(parent, ConversionLog):
            return QSize(parent.max_line_width, 20)
        return QSize(option.fontMetrics.horizontalAdvance(str(index.data())) + 1, 20)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        entry = index.data(ENTRY_ROLE)
        if not isinstance(entry, LogEntry):
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setClipRect(option.rect)
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(colors().selection_bg))
        painter.setFont(option.font)
        metrics = QFontMetrics(option.font)
        x = option.rect.x()
        baseline = option.rect.y() + (20 - metrics.height()) // 2 + metrics.ascent()
        level_color = {
            "INFO": colors().placeholder,
            "WARNING": colors().warn_fg,
            "ERROR": colors().danger,
        }[entry.level]
        filename = entry.context.get("input")
        for text, color in (
            (f"{entry.timestamp} ", colors().placeholder),
            (entry.level, level_color),
            (f" [{entry.event}]", colors().placeholder),
            (f" [{filename}]" if isinstance(filename, str) else "", colors().text),
            (f" {entry.message}", colors().text if entry.level == "INFO" else level_color),
        ):
            painter.setPen(QColor(color))
            painter.drawText(x, baseline, text)
            x += metrics.horizontalAdvance(text)
        painter.restore()


class ConversionLog(QListWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("conversionLog")
        font = mono_font()
        font.setPixelSize(12)
        self.setFont(font)
        self.setItemDelegate(LogDelegate(self))
        self.setUniformItemSizes(True)
        self.max_line_width = 1
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setViewportMargins(14, 12, 14, 12)
        corner = QWidget()
        corner.setObjectName("conversionLogCorner")
        self.setCornerWidget(corner)

    def append_entry(self, entry: LogEntry) -> None:
        text = entry.display_text()
        width = self.fontMetrics().horizontalAdvance(text) + 1
        wider = width > self.max_line_width
        if wider:
            self.max_line_width = width
        item = QListWidgetItem(text)
        item.setData(ENTRY_ROLE, entry)
        self.addItem(item)
        if wider:
            self.doItemsLayout()
        self.scrollToBottom()

    def clear(self) -> None:
        super().clear()
        self.max_line_width = 1

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            selected = sorted(self.selectedIndexes(), key=lambda index: index.row())
            QApplication.clipboard().setText("\n".join(str(index.data()) for index in selected))
            event.accept()
            return
        super().keyPressEvent(event)
