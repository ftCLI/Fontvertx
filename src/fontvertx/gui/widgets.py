"""Reusable widgets for the Fontvertx window."""

from html import escape
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QLocale,
    QObject,
    QPointF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QContextMenuEvent,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QEnterEvent,
    QFont,
    QFontMetrics,
    QHelpEvent,
    QIcon,
    QKeyEvent,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QPixmap,
    QResizeEvent,
    QStandardItem,
    QStandardItemModel,
    QValidator,
)
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListView,
    QMenu,
    QPushButton,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionComboBox,
    QStylePainter,
    QTableView,
    QToolTip,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from fontvertx.constants import MAX_UPM, MIN_UPM
from fontvertx.gui.drop_zone_frame import paint_zone_frame
from fontvertx.gui.icons import material_icon
from fontvertx.gui.styles import (
    BUTTON_HEIGHT,
    LIGHT,
    RADIUS_MD,
    RADIUS_PILL,
    mono_font,
    radius_px,
    tabular_font,
    ui_font,
)


class ScrollOverflowFade(QWidget):
    """Non-interactive hint at the bottom of a scroll area's viewport."""

    def __init__(self, area: QScrollArea) -> None:
        super().__init__(area.viewport())
        self._area = area
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        area.viewport().installEventFilter(self)
        area.verticalScrollBar().valueChanged.connect(self._sync)
        area.verticalScrollBar().rangeChanged.connect(self._sync)
        self._sync()

    def _sync(self, *_: int) -> None:
        viewport = self._area.viewport()
        self.setGeometry(0, max(0, viewport.height() - 16), viewport.width(), 16)
        scrollbar = self._area.verticalScrollBar()
        self.setVisible(scrollbar.value() < scrollbar.maximum())
        self.raise_()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._area.viewport() and event.type() == QEvent.Type.Resize:
            self._sync()
        return super().eventFilter(watched, event)

    def paintEvent(self, event: QPaintEvent) -> None:
        gradient = QLinearGradient(0, 0, 0, self.height())
        transparent = QColor(LIGHT.page)
        transparent.setAlpha(0)
        gradient.setColorAt(0, transparent)
        gradient.setColorAt(1, QColor(LIGHT.page))
        painter = QPainter(self)
        painter.fillRect(self.rect(), gradient)


class OverlayScrollBar(QScrollBar):
    """Thin vertical scrollbar floating in the gutter beside a scroll area.

    The area's own scrollbar is turned off so it never reserves space; this
    bar mirrors it from the area's parent, just outside the viewport so it
    never covers the content. It shows while the pointer is over the area or
    it scrolls, and hides again shortly after.
    """

    HIDE_DELAY_MS = 800

    def __init__(self, area: QScrollArea) -> None:
        super().__init__(Qt.Orientation.Vertical, area.viewport())
        self._area: QScrollArea | None = area
        # Compared by identity in eventFilter, so no call reaches a half-destroyed area.
        self._viewport: QWidget | None = area.viewport()
        self._native = area.verticalScrollBar()
        self._hovered = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.HIDE_DELAY_MS)
        self._timer.timeout.connect(self._update_visibility)
        # QScrollArea sets the range before the page step, and a page step change
        # emits nothing: copy the steps again once the area has finished updating.
        self._steps_timer = QTimer(self)
        self._steps_timer.setSingleShot(True)
        self._steps_timer.setInterval(0)
        self._steps_timer.timeout.connect(self._sync_range)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.viewport().installEventFilter(self)
        area.installEventFilter(self)
        self._native.rangeChanged.connect(self._sync_range)
        self._native.valueChanged.connect(self._sync_value)
        self.valueChanged.connect(self._native.setValue)
        # Once reparented beside the area, the bar outlives it: drop every reference
        # as soon as the area goes away and delete the bar with it.
        area.destroyed.connect(self._detach)
        self._sync_range()
        self.hide()

    def _live_area(self) -> QScrollArea | None:
        area = self._area
        if area is None or not isValid(area):
            return None
        return area

    def _detach(self, *_: object) -> None:
        self._area = None
        self._viewport = None
        self._timer.stop()
        self._steps_timer.stop()
        if isValid(self):
            self.deleteLater()

    def _sync_range(self, *_: int) -> None:
        if self._live_area() is None:
            return
        self.blockSignals(True)
        self.setRange(self._native.minimum(), self._native.maximum())
        self.setPageStep(self._native.pageStep())
        self.setSingleStep(self._native.singleStep())
        self.setValue(self._native.value())
        self.blockSignals(False)
        if self.sender() is not self._steps_timer:
            self._steps_timer.start()
        self._place()
        self._update_visibility()

    def _sync_value(self, value: int) -> None:
        if value != self.value():
            self.blockSignals(True)
            self.setValue(value)
            self.blockSignals(False)
        self._reveal()

    def _place(self) -> None:
        area = self._live_area()
        if area is None:
            return
        host = area.parentWidget()
        if host is None:
            return
        if self.parentWidget() is not host:
            self.setParent(host)
        frame = area.geometry()
        self.setGeometry(frame.right() + 1, frame.top(), self.sizeHint().width(), frame.height())
        self.raise_()

    def _reveal(self) -> None:
        if self.maximum() > 0:
            self._place()
            self.show()
            self._timer.start()

    def _update_visibility(self) -> None:
        if self._live_area() is None:
            return
        keep = self._hovered or self.isSliderDown()
        if self.maximum() <= 0 or (not keep and not self._timer.isActive()):
            self.hide()
        elif keep:
            self._reveal()

    def enterEvent(self, event: QEnterEvent) -> None:
        self._hovered = True
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hovered = False
        self._timer.start()
        super().leaveEvent(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if self._area is None:
            return False
        if watched is self._area:
            if event.type() in (
                QEvent.Type.Resize,
                QEvent.Type.Move,
                QEvent.Type.ParentChange,
            ):
                self._place()
        elif watched is self._viewport:
            kind = event.type()
            if kind == QEvent.Type.Resize:
                self._sync_range()
            elif kind == QEvent.Type.Enter:
                self._hovered = True
                self._reveal()
            elif kind == QEvent.Type.Leave:
                self._hovered = self.underMouse()
                self._timer.start()
        return super().eventFilter(watched, event)


class ScrollbarHeaderFiller:
    """Keep the header band continuous above an item view's vertical scrollbar."""

    def __init__(self, view: QAbstractScrollArea, header: QHeaderView) -> None:
        self._header = header
        self.cap = QWidget()
        self.cap.setObjectName("tableScrollbarHeader")
        view.addScrollBarWidget(self.cap, Qt.AlignmentFlag.AlignTop)
        header.installEventFilter(view)
        self.cap.setFixedHeight(header.height())

    def handle_event(self, watched: QObject, event: QEvent) -> None:
        if watched is self._header and event.type() == QEvent.Type.Resize:
            self.cap.setFixedHeight(self._header.height())


def uppercase_font(base: QFont) -> QFont:
    font = QFont(base)
    font.setCapitalization(QFont.Capitalization.AllUppercase)
    for tag, value in (("cpsp", 1), ("case", 1), ("ss02", 0)):
        font.setFeature(QFont.Tag.fromString(tag), value)
    return font


def section_heading(text: str, object_name: str) -> QLabel:
    """Small uppercase section label; pass ``text`` in normal case."""
    heading = QLabel(text)
    heading.setObjectName(object_name)
    font = uppercase_font(heading.font())
    heading.setFont(font)
    return heading


class ExamplePathLabel(QLabel):
    """Selectable path with slash-only line breaks and clean clipboard text."""

    def __init__(self) -> None:
        super().__init__()
        self._path = ""
        self._rendered_width = -1
        self.setObjectName("examplePath")
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setContentsMargins(0, 0, 0, 0)
        self.setMargin(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        font = mono_font()
        font.setPixelSize(12)
        self.setFont(font)

    def set_path(self, path: str) -> None:
        self._path = path
        self.setToolTip(path)
        self._rendered_width = -1
        self._render_path()

    def plain_path(self) -> str:
        return self._path

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.matches(QKeySequence.StandardKey.Copy):
            self._copy_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        menu = QMenu(self)
        copy = menu.addAction("Copy")
        copy.setEnabled(self.hasSelectedText())
        if menu.exec(event.globalPos()) is copy:
            self._copy_selection()

    def _copy_selection(self) -> None:
        QApplication.clipboard().setText(
            self.selectedText()
            .replace("\u200b", "")
            .replace("\u2029", "")
            .replace("\u2028", "")
            .replace("\n", "")
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._render_path()

    def _render_path(self) -> None:
        width = self.width()
        if width == self._rendered_width:
            return
        self._rendered_width = width
        metrics = self.fontMetrics()
        available = max(1, width - 24)
        lines: list[list[tuple[str, bool]]] = [[]]
        line_width = 0
        parts = self._path.split("/")
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            segment = part if last else part + "/"
            segment_width = metrics.horizontalAdvance(segment)
            if lines[-1] and line_width + segment_width > available:
                lines.append([])
                line_width = 0
            lines[-1].append((segment, last))
            line_width += segment_width
        paragraphs = []
        for line in lines:
            spans = []
            for segment, last in line:
                text = escape(segment)
                if last:
                    spans.append(text)
                else:
                    spans.append(
                        f'{text[:-1]}<span style="color:{LIGHT.header_group}">/</span>&#8203;'
                    )
            paragraphs.append(f'<div style="margin:0; white-space:pre">{"".join(spans)}</div>')
        self.setText("".join(paragraphs))
        first = metrics.tightBoundingRect("".join(segment for segment, _ in lines[0]))
        last_bounds = metrics.tightBoundingRect("".join(segment for segment, _ in lines[-1]))
        top_bearing = metrics.ascent() + first.top()
        bottom_bearing = metrics.descent() - last_bounds.bottom() - 1
        # Center the visible ink as well as the line boxes; font bearings differ
        # between the first and last line even with equal stylesheet padding.
        adjustment = int((bottom_bearing - top_bearing) / 2)
        self.ensurePolished()
        self.setContentsMargins(12, 9 + adjustment, 12, 9 - adjustment)
        extra_height = int(top_bearing >= bottom_bearing)
        self.setFixedHeight(len(lines) * metrics.lineSpacing() + 18 + extra_height)


STEP_ICON_SIZE = 14  # check mark inside the 24px step badge


def centered_icon_pixels(box: int, icon: int, ratio: float) -> tuple[int, int]:
    """Device-pixel size and offset of an ``icon``-sized glyph centered in a ``box``.

    The glyph's pixel size is adjusted by one pixel when needed so that the space left
    around it is even: the glyph then starts on a whole pixel at any scale.
    """
    box_px = round(box * ratio)
    icon_px = round(icon * ratio)
    if (box_px - icon_px) % 2:
        icon_px += 1
    return icon_px, (box_px - icon_px) // 2


class StepBadge(QLabel):
    """Numbered step badge; a completed step shows a vector check instead of the number.

    The check is painted from its SVG icon at the current device pixel ratio (a text
    glyph fell back to a symbol font and rendered jagged at 150%).
    """

    def __init__(self, number: int) -> None:
        super().__init__(str(number))
        self.setObjectName("cardNumber")
        self._number = number
        self._done = False
        # Weight 600: at 14px the weight-400 stroke is ~1px and antialiases to a
        # lighter green than step_check at 100%.
        self._check = material_icon("check_wght600", LIGHT.step_check, STEP_ICON_SIZE)

    def is_done(self) -> bool:
        return self._done

    def set_done(self, done: bool) -> None:
        self._done = done
        self.setText("" if done else str(self._number))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)  # stylesheet circle (and the number, if any)
        if not self._done:
            return
        # Work in device pixels: the glyph's pixel size is chosen so the space left in
        # the badge is even, so the glyph sits on whole pixels at 100/150/200% alike.
        painter = QPainter(self)
        ratio = painter.device().devicePixelRatioF()
        icon_px, offset_px = centered_icon_pixels(self.width(), STEP_ICON_SIZE, ratio)
        pixmap = QPixmap(self._check.pixmap(QSize(icon_px, icon_px), 1.0))
        pixmap.setDevicePixelRatio(ratio)
        painter.drawPixmap(QPointF(offset_px / ratio, offset_px / ratio), pixmap)


def card_heading(
    text: str,
    number: int | None = None,
    bottom_margin: int = 6,
    *,
    modified_chip: bool = False,
) -> QWidget:
    heading = QLabel(text)
    heading.setObjectName("cardHeading")
    if number is None:
        heading.setContentsMargins(0, 0, 0, bottom_margin)
        return heading
    badge = StepBadge(number)
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, bottom_margin)
    layout.setSpacing(8)
    layout.addWidget(badge)
    layout.addWidget(heading)
    if modified_chip:
        chip = QLabel("Modified")
        chip.setObjectName("modifiedChip")
        chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        policy = chip.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        chip.setSizePolicy(policy)
        chip.setVisible(False)
        layout.addWidget(chip)
    layout.addStretch(1)
    return container


class ElidedLabel(QLabel):
    """Single-line label that elides its text and shows it in full as a tooltip when cut.

    An explicit tooltip (``setToolTip``), such as an error detail, always takes precedence.
    """

    def tooltip_text(self) -> str:
        """The tooltip a hover would show now: the explicit one, else the text if elided."""
        if self.toolTip():
            return self.toolTip()
        return self.text() if self.display_text() != self.text() else ""

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ToolTip and isinstance(event, QHelpEvent):
            if self.toolTip():
                return super().event(event)
            text = self.tooltip_text()
            if text:
                QToolTip.showText(event.globalPos(), text, self)
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().event(event)

    def display_text(self) -> str:
        return self.fontMetrics().elidedText(
            self.text(), Qt.TextElideMode.ElideRight, self.contentsRect().width()
        )

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = self.contentsRect()
        self.style().drawItemText(
            painter,
            rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.palette(),
            self.isEnabled(),
            self.display_text(),
            self.foregroundRole(),
        )


UPM_STEP_VALUES = (
    16,
    32,
    64,
    128,
    256,
    512,
    1000,
    1024,
    2000,
    2048,
    4000,
    4096,
    8000,
    8192,
    16000,
    16384,
)


class KeyboardPushButton(QPushButton):
    """Push button that activates on Return/Enter as well as Space."""

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.isAutoRepeat():
                self.click()
            event.accept()
            return
        super().keyPressEvent(event)


class HoverIconButton(KeyboardPushButton):
    """Flat icon-only button: hovering swaps the icon tint instead of the background."""

    def __init__(self, icon: QIcon, hover_icon: QIcon, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._normal_icon = icon
        self._hover_icon = hover_icon
        self.setIcon(icon)

    def enterEvent(self, event: QEnterEvent) -> None:
        self.setIcon(self._hover_icon)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.setIcon(self._normal_icon)
        super().leaveEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        # Native styles can draw a focus rectangle over the icon.
        option.state &= ~QStyle.StateFlag.State_HasFocus
        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        if self.hasFocus():
            radius = RADIUS_PILL if self.objectName() == "primaryButton" else RADIUS_MD
            painter.setPen(QPen(QColor(LIGHT.accent), 2))
            painter.drawRoundedRect(
                self.rect().adjusted(1, 1, -1, -1), radius_px(radius), radius_px(radius)
            )


class DecimalSpinBox(QDoubleSpinBox):
    """Double spin box that accepts both '.' and ',' as decimal separator."""

    def __init__(self) -> None:
        super().__init__()
        self.setLocale(QLocale.c())

    def validate(self, text: str, pos: int) -> tuple[QValidator.State, str, int]:
        return super().validate(text.replace(",", "."), pos)

    def valueFromText(self, text: str) -> float:
        return super().valueFromText(text.replace(",", "."))


class UpmSpinBox(QSpinBox):
    """Spin box whose steps jump between supported units-per-em values.

    A disabled field shows an empty text: its value applies only while the
    "Set target UPM" checkbox governing it is checked.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setRange(MIN_UPM, MAX_UPM)
        self.setValue(1000)

    def textFromValue(self, value: int) -> str:
        return super().textFromValue(value) if self.isEnabled() else ""

    def stepBy(self, steps: int) -> None:
        value = self.value()
        for _ in range(abs(steps)):
            if steps > 0:
                value = next((v for v in UPM_STEP_VALUES if v > value), self.maximum())
            else:
                value = next((v for v in reversed(UPM_STEP_VALUES) if v < value), self.minimum())
        self.setValue(value)


class StepperField(QWidget):
    """Spin box flanked by app-styled − / + buttons instead of native arrows."""

    def __init__(self, spin_box: QAbstractSpinBox, *, tab_buttons: bool = False) -> None:
        super().__init__()
        self.spin_box = spin_box
        spin_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.decrement_button = KeyboardPushButton("−")
        self.increment_button = KeyboardPushButton("+")
        for button, direction in ((self.decrement_button, -1), (self.increment_button, 1)):
            button.setObjectName("stepperButton")
            button.setAutoRepeat(True)
            if not tab_buttons:
                button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _=False, step=direction: self._step(step))
        layout.addWidget(self.decrement_button)
        layout.addWidget(spin_box, 1)
        layout.addWidget(self.increment_button)

    def _step(self, steps: int) -> None:
        self.spin_box.stepBy(steps)
        self.spin_box.lineEdit().deselect()


class PopupComboBox(QComboBox):
    """Combo whose popup container is frameless and transparent, so only the list is drawn.

    The closed combo elides its current text with "…" when it does not fit; the full text
    then goes to the tooltip. The popup keeps full item texts.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setView(QListView(self))
        popup = self.view().window()
        popup.setWindowFlags(
            popup.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.view().setFrameShape(QFrame.Shape.NoFrame)
        self.currentIndexChanged.connect(lambda _index: self._sync_elided_tooltip())

    def _edit_rect_width(self) -> int:
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            option,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        )
        return rect.width()

    def elided_text(self) -> str:
        return self.fontMetrics().elidedText(
            self.currentText(), Qt.TextElideMode.ElideRight, self._edit_rect_width()
        )

    def _sync_elided_tooltip(self) -> None:
        text = self.currentText()
        self.setToolTip(text if text and self.elided_text() != text else "")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_elided_tooltip()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        if self.currentIndex() >= 0:
            option.currentText = self.elided_text()
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)


class ComboItemDelegate(QStyledItemDelegate):
    """Popup rows: tinted current item with a check, light hover, group headings."""

    def __init__(self, combo: QComboBox, item_height: int = 34) -> None:
        super().__init__(combo)
        self._combo = combo
        self._item_height = item_height

    @staticmethod
    def _is_heading(index) -> bool:
        return not index.flags() & Qt.ItemFlag.ItemIsEnabled

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect
        if self._is_heading(index):
            self._paint_heading(painter, rect, index)
            painter.restore()
            return
        is_current = index.row() == self._combo.currentIndex()
        hovered = bool(
            option.state & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected)
        )
        fill = None
        if is_current:
            fill = LIGHT.accent_tint
        elif hovered:
            fill = LIGHT.row_hover
        if fill:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(fill))
            painter.drawRoundedRect(rect, radius_px(RADIUS_MD), radius_px(RADIUS_MD))
        font = ui_font(option.font)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)
        painter.setPen(QColor(LIGHT.text))
        text_rect = rect.adjusted(12, 0, -36 if is_current else -12, 0)
        metrics = painter.fontMetrics()
        text = metrics.elidedText(
            str(index.data() or ""), Qt.TextElideMode.ElideRight, text_rect.width()
        )
        painter.drawText(
            text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text
        )
        if is_current:
            cx, cy = rect.right() - 20, rect.center().y()
            pen = QPen(QColor(LIGHT.accent), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolyline(
                [QPointF(cx - 5, cy), QPointF(cx - 1.5, cy + 3.5), QPointF(cx + 5, cy - 3.5)]
            )
        painter.restore()

    def _paint_heading(self, painter: QPainter, rect, index) -> None:
        if index.row() > 0:
            painter.setPen(QPen(QColor(LIGHT.row_separator), 1))
            painter.drawLine(rect.left(), rect.top() + 3, rect.right(), rect.top() + 3)
        font = uppercase_font(ui_font(self._combo.font()))
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(LIGHT.header_group))
        painter.drawText(
            rect.adjusted(12, 6 if index.row() > 0 else 0, -12, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            str(index.data() or ""),
        )

    def sizeHint(self, option, index) -> QSize:
        size = super().sizeHint(option, index)
        if self._is_heading(index):
            size.setHeight(self._item_height - 4 + (6 if index.row() > 0 else 0))
        else:
            size.setHeight(self._item_height)
        return size


class ConversionSelector(QWidget):
    currentIndexChanged = Signal(int)

    def __init__(
        self,
        conversions: dict[str, str],
        *,
        select_first: bool = True,
        group_headings: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._keys = list(conversions)
        self._index = -1
        self.combo = PopupComboBox()
        self.combo.setPlaceholderText("Choose a conversion…")
        palette = self.combo.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(LIGHT.placeholder))
        self.combo.setPalette(palette)
        self.combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.combo.setMinimumContentsLength(20)
        model = QStandardItemModel(self.combo)
        self._rows: list[int] = []
        for key, label in conversions.items():
            if group_headings is not None and key in group_headings:
                heading = QStandardItem(group_headings[key])
                heading.setFlags(Qt.ItemFlag.NoItemFlags)
                model.appendRow(heading)
            item = QStandardItem(label)
            self._rows.append(model.rowCount())
            model.appendRow(item)
        self.combo.setModel(model)
        self.combo.view().setItemDelegate(ComboItemDelegate(self.combo))
        self.combo.setCurrentIndex(-1)
        self.combo.view().setMinimumWidth(self.combo.view().sizeHintForColumn(0) + 40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo)
        if select_first:
            self._index = 0
            self.combo.setCurrentIndex(self._rows[0])
        self.combo.activated.connect(self._on_activated)

    def _on_activated(self, row: int) -> None:
        if row in self._rows:
            self.setCurrentIndex(self._rows.index(row))

    def currentIndex(self) -> int:
        return self._index

    def currentData(self) -> str | None:
        return self._keys[self._index] if self._index >= 0 else None

    def findData(self, key: str) -> int:
        return self._keys.index(key) if key in self._keys else -1

    def setCurrentIndex(self, index: int) -> None:
        if 0 <= index < len(self._keys) and index != self._index:
            self._index = index
            self.combo.setCurrentIndex(self._rows[index])
            self.currentIndexChanged.emit(index)


def accept_local_files(event: QDragEnterEvent | QDragMoveEvent) -> None:
    if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
        event.acceptProposedAction()
    else:
        event.ignore()


def dropped_paths(event: QDropEvent) -> list[str]:
    return [
        url.toLocalFile()
        for url in event.mimeData().urls()
        if url.isLocalFile()
        and (Path(url.toLocalFile()).is_file() or Path(url.toLocalFile()).is_dir())
    ]


def set_drag_over(widget: QWidget, enabled: bool) -> None:
    value = "true" if enabled else "false"
    if widget.property("dragOver") == value:
        return
    widget.setProperty("dragOver", value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
    if isinstance(widget, QAbstractScrollArea):
        widget.viewport().update()


DROP_ICON_SIZE = 18


IMPORT_BUTTON_HEIGHT = BUTTON_HEIGHT


def _import_icon(name: str) -> QIcon:
    return material_icon(name, LIGHT.accent, DROP_ICON_SIZE, LIGHT.import_disabled_icon)


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class FolderSplitButton(QFrame):
    """ "Add folder…" button joined to an arrow that offers the recursive variant."""

    folder_requested = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("folderSplitButton")
        self.setProperty("focusWithin", False)
        self.setProperty("menuOpen", False)
        self.main_button = KeyboardPushButton("Add folder…")
        self.main_button.setObjectName("importButton")
        self.main_button.setProperty("split", "main")
        self.main_button.setToolTip("Add a folder. Only the fonts directly inside it are listed.")
        self.main_button.clicked.connect(lambda: self.folder_requested.emit(False))
        self.arrow_button = KeyboardPushButton()
        self.arrow_button.setObjectName("importButton")
        self.arrow_button.setProperty("split", "arrow")
        self.arrow_button.setAccessibleName("More ways to add a folder")
        self.arrow_button.setToolTip("More ways to add a folder")
        self.arrow_button.setFixedWidth(28)
        self.arrow_button.setIcon(_import_icon("expand_more"))
        self.arrow_button.setIconSize(QSize(DROP_ICON_SIZE, DROP_ICON_SIZE))
        self.arrow_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        for button in (self.main_button, self.arrow_button):
            button.setFixedHeight(IMPORT_BUTTON_HEIGHT - 4)
            button.installEventFilter(self)
        self.add_folder_action = QAction("Add folder…", self)
        self.add_folder_recursive_action = QAction("Add folder and subfolders…", self)
        self.add_folder_action.triggered.connect(lambda: self.folder_requested.emit(False))
        self.add_folder_recursive_action.triggered.connect(lambda: self.folder_requested.emit(True))
        self.menu = QMenu(self)
        self.menu.addAction(self.add_folder_action)
        self.menu.addAction(self.add_folder_recursive_action)
        self.menu.aboutToShow.connect(self._menu_opened)
        self.menu.aboutToHide.connect(self._menu_closed)
        self.arrow_button.setMenu(self.menu)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.main_button)
        divider = QFrame()
        divider.setObjectName("folderSplitDivider")
        divider.setFixedWidth(1)
        layout.addWidget(divider)
        layout.addWidget(self.arrow_button)
        self.setFixedHeight(IMPORT_BUTTON_HEIGHT)

    def _menu_opened(self) -> None:
        self.setProperty("menuOpen", True)
        self.arrow_button.setProperty("menuOpen", True)
        self._sync_focus()

    def _menu_closed(self) -> None:
        self.setProperty("menuOpen", False)
        self.arrow_button.setProperty("menuOpen", False)
        self.arrow_button.setDown(False)
        _repolish(self.arrow_button)
        QTimer.singleShot(0, self, self._sync_focus)

    def _sync_focus(self) -> None:
        focused = bool(self.property("menuOpen")) or any(
            button.hasFocus() for button in (self.main_button, self.arrow_button)
        )
        self.setProperty("focusWithin", focused)
        _repolish(self)
        _repolish(self.arrow_button)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.FocusIn:
            self.setProperty("focusWithin", True)
            _repolish(self)
        elif event.type() == QEvent.Type.FocusOut:
            QTimer.singleShot(0, self, self._sync_focus)
        return super().eventFilter(watched, event)


# Empty-state copy of the files card's drop zone (the actions live in the card header).
DROP_ZONE_TITLE = "Drop fonts or folders here"
DROP_ZONE_DRAGGING = "Release to add"
DROP_ZONE_SCANNING = "Scanning…"
DROP_ZONE_GLYPH = "Aa"
# The glyph's pixel size follows the zone height, within these bounds; below
# GLYPH_MIN_ZONE_HEIGHT it is hidden so the title and formats always fit.
GLYPH_HEIGHT_RATIO = 0.25
GLYPH_PIXEL_RANGE = (56, 140)
GLYPH_MIN_ZONE_HEIGHT = 280
GLYPH_LETTER_SPACING = 96  # percent: slightly tight
GLYPH_GAP = 20  # visible space between the glyph's baseline and the title
FORMATS_GAP = 12  # between the title and the format chips


class DropZone(QFrame):
    """Empty-state drop target: a large decorative "Aa", the title and a row of
    supported-format chips, centered over a rounded dashed frame
    (see drop_zone_frame.py).

    While files are dragged over it, the title reads "Release to add" and the chips
    are hidden (keeping their room, so nothing moves); while a folder is scanned, the
    title reads "Scanning…".
    """

    paths_dropped = Signal(list)
    FORMATS = ("TTF", "OTF", "WOFF", "WOFF2", "TTC", "OTC")

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("dropZone")
        self.setAccessibleName("Font drop area")
        self.setAccessibleDescription("Supported formats: " + ", ".join(self.FORMATS))
        self.setAcceptDrops(True)
        self.setProperty("dragOver", "false")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._scanning = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)
        layout.addStretch()

        self.glyph = QLabel(DROP_ZONE_GLYPH)
        self.glyph.setObjectName("dropZoneGlyph")
        self.glyph.setAccessibleName("")
        self.glyph.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Not retained when hidden: the title and formats stay centered without it.
        self.glyph.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        font = ui_font()
        font.setWeight(QFont.Weight.DemiBold)
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, GLYPH_LETTER_SPACING)
        self.glyph.setFont(font)

        self.title = QLabel(DROP_ZONE_TITLE)
        self.title.setObjectName("dropZoneTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.formats = QWidget()
        formats_layout = QHBoxLayout(self.formats)
        formats_layout.setContentsMargins(0, FORMATS_GAP, 0, 0)
        formats_layout.setSpacing(6)
        formats_layout.addStretch()
        for name in self.FORMATS:
            chip = QLabel(name)
            chip.setObjectName("formatChip")
            chip.setProperty("format", name)
            formats_layout.addWidget(chip)
        formats_layout.addStretch()
        policy = self.formats.sizePolicy()
        policy.setRetainSizeWhenHidden(True)  # the title does not jump while dragging
        self.formats.setSizePolicy(policy)

        layout.addWidget(self.glyph)
        layout.addWidget(self.title)
        layout.addWidget(self.formats)
        layout.addStretch()
        self._sync_glyph_size()
        self._update_state()

    def set_scanning(self, scanning: bool) -> None:
        self._scanning = scanning
        self._update_state()

    def _update_state(self) -> None:
        dragging = self.property("dragOver") == "true"
        self.title.setText(
            DROP_ZONE_DRAGGING
            if dragging
            else DROP_ZONE_SCANNING
            if self._scanning
            else DROP_ZONE_TITLE
        )
        self.formats.setVisible(not (dragging or self._scanning))
        # The glyph's color depends on the zone's dragOver property (descendant selector).
        _repolish(self.glyph)
        self.update()

    def glyph_pixel_size(self) -> int:
        low, high = GLYPH_PIXEL_RANGE
        return max(low, min(high, round(self.height() * GLYPH_HEIGHT_RATIO)))

    def _sync_glyph_size(self) -> None:
        pixels = self.glyph_pixel_size()
        if self.glyph.font().pixelSize() != pixels:
            font = self.glyph.font()
            font.setPixelSize(pixels)
            self.glyph.setFont(font)
            # Fit the label to the ink of "Aa" (cap height, no descender): negative
            # margins drop the empty space above the capitals and below the baseline,
            # so the visible gap to the title is GLYPH_GAP and the block centers on ink.
            metrics = QFontMetrics(font)
            above = metrics.ascent() - metrics.capHeight()
            self.glyph.setContentsMargins(0, -above, 0, GLYPH_GAP - metrics.descent())
        self.glyph.setVisible(self.height() >= GLYPH_MIN_ZONE_HEIGHT)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._sync_glyph_size()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        paint_zone_frame(painter, self.width(), self.height(), self.property("dragOver") == "true")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        accept_local_files(event)
        set_drag_over(self, event.isAccepted())
        self._update_state()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        accept_local_files(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        set_drag_over(self, False)
        self._update_state()
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        set_drag_over(self, False)
        self._update_state()
        paths = dropped_paths(event)
        if paths:
            event.acceptProposedAction()
            self.paths_dropped.emit(paths)
        else:
            event.ignore()


class FileTable(QTableView):
    paths_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("fontFileTable")
        # Slashed zeros and tabular figures for every cell and the header.
        self.setFont(tabular_font(self.font()))
        self.horizontalHeader().setFont(tabular_font(self.horizontalHeader().font()))
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        # QTableView wraps by default: long names must be elided, never broken over two lines.
        self.setWordWrap(False)
        self.setTabKeyNavigation(False)
        self.setSortingEnabled(True)
        self.setMouseTracking(True)
        self.setAlternatingRowColors(False)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(30)
        self.horizontalHeader().setFixedHeight(30)
        self._scrollbar_header = ScrollbarHeaderFiller(self, self.horizontalHeader())
        self._scrollbar_header_cap = self._scrollbar_header.cap
        self.setProperty("dragOver", "false")
        self.muted_color = QColor(LIGHT.text_disabled)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        helper = getattr(self, "_scrollbar_header", None)
        if helper is not None:
            helper.handle_event(watched, event)
        return super().eventFilter(watched, event)

    def configure_columns(self) -> None:
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in ((1, 80), (2, 110), (3, 70), (4, 140), (5, 140)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(column, width)
        for column in (4, 5):
            self.setColumnHidden(column, True)

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
