"""Dialog for composing output-directory organization rules."""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QIcon,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from fontvertx.gui.icons import material_icon
from fontvertx.gui.profiles import PROFILES, available_organization_criteria
from fontvertx.gui.styles import RADIUS_MD, RADIUS_XL, colors, radius_px
from fontvertx.gui.tooltips import wrap_tip
from fontvertx.gui.widgets import (
    ComboItemDelegate,
    ExamplePathLabel,
    KeyboardPushButton,
    PopupComboBox,
    section_heading,
)
from fontvertx.service import organization_level_name

ICON_ONLY_SIZE = 18
ICON_WITH_TEXT_SIZE = 16
ANIMATIONS_ENABLED = True
SWAP_DURATION_MS = 160
HIGHLIGHT_DURATION_MS = 400
_SPI_GETCLIENTAREAANIMATION = 0x1042


def _client_area_animations_enabled() -> bool:
    if sys.platform != "win32":
        return True
    try:
        enabled = ctypes.c_int()
        result = ctypes.WinDLL("user32", use_last_error=True).SystemParametersInfoW(
            _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
        )
        return not bool(result) or bool(enabled.value)
    except (AttributeError, OSError):
        return True


def _animations_enabled() -> bool:
    return ANIMATIONS_ENABLED and _client_area_animations_enabled()


def _paint_highlight(widget: QWidget, color: QColor, radius: int) -> None:
    if color.alpha() == 0:
        return
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(widget.rect().adjusted(1, 1, -1, -1), radius, radius)
    painter.end()


class _AnimatedFrame(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.highlight_color = QColor(colors().accent_tint)
        self.highlight_color.setAlpha(0)

    def set_highlight_color(self, color: QColor) -> None:
        self.highlight_color = color
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        _paint_highlight(self, self.highlight_color, radius_px(RADIUS_XL))


class _AnimatedWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.highlight_color = QColor(colors().accent_tint)
        self.highlight_color.setAlpha(0)

    def set_highlight_color(self, color: QColor) -> None:
        self.highlight_color = color
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        _paint_highlight(self, self.highlight_color, radius_px(RADIUS_MD))


class _SwapAnimation:
    """Animate two widgets exchanging layout positions."""

    def __init__(
        self, first: QWidget, second: QWidget, duration: int, easing: QEasingCurve.Type
    ) -> None:
        self.widgets = (first, second)
        self.old_positions = (first.pos(), second.pos())
        self.duration = duration
        self.easing = easing
        self.group: QParallelAnimationGroup | None = None
        self.highlight: QVariantAnimation | None = None
        self.final_positions = self.old_positions

    def start(self, moved: _AnimatedFrame | _AnimatedWidget, layout: QLayout) -> None:
        layout.activate()
        self.final_positions = (self.widgets[0].pos(), self.widgets[1].pos())
        self.group = QParallelAnimationGroup()
        for widget, start, end in zip(
            self.widgets, self.old_positions, self.final_positions, strict=True
        ):
            if start == end:
                continue
            animation = QPropertyAnimation(widget, b"pos")
            animation.setDuration(self.duration)
            animation.setEasingCurve(QEasingCurve(self.easing))
            animation.setStartValue(start)
            animation.setEndValue(end)
            self.group.addAnimation(animation)
            widget.move(start)

        start_color = QColor(colors().accent_tint)
        end_color = QColor(start_color)
        end_color.setAlpha(0)
        self.highlight = QVariantAnimation()
        self.highlight.setDuration(HIGHLIGHT_DURATION_MS)
        self.highlight.setEasingCurve(QEasingCurve.Type.Linear)
        self.highlight.setStartValue(start_color)
        self.highlight.setEndValue(end_color)

        def set_highlight_color(color: QColor) -> None:
            if isValid(moved):
                moved.set_highlight_color(color)

        self.highlight.valueChanged.connect(set_highlight_color)
        self.highlight.finished.connect(lambda: set_highlight_color(end_color))
        self.group.addAnimation(self.highlight)
        moved.set_highlight_color(start_color)
        self.group.start()

    def running(self) -> bool:
        return (
            self.group is not None and self.group.state() == QParallelAnimationGroup.State.Running
        )

    def finish(self) -> None:
        if self.group is None:
            return
        if self.group.state() == QParallelAnimationGroup.State.Running:
            self.group.setCurrentTime(self.group.duration())
        self.group.stop()
        for widget, position in zip(self.widgets, self.final_positions, strict=True):
            if isValid(widget):
                widget.move(position)
        self.group = None
        self.highlight = None


def _icon(name: str, size: int, accent: bool = False) -> QIcon:
    """Dialog icon: slate by default, accent for ``add``, muted when disabled."""
    color = colors().accent if accent else colors().slate
    return material_icon(name, color, size, disabled_color=colors().icon_disabled)


def _icon_button(
    name: str, object_name: str, tooltip: str, accessible_name: str | None = None
) -> KeyboardPushButton:
    button = KeyboardPushButton()
    button.setObjectName(object_name)
    button.setIcon(_icon(name, ICON_ONLY_SIZE))
    button.setIconSize(QSize(ICON_ONLY_SIZE, ICON_ONLY_SIZE))
    button.setFixedSize(30, 30)
    button.setToolTip(tooltip)
    button.setAccessibleName(accessible_name or tooltip)
    return button


def _text_icon_button(
    text: str, name: str, object_name: str, accent: bool = False
) -> KeyboardPushButton:
    button = KeyboardPushButton(text)
    button.setObjectName(object_name)
    button.setIcon(_icon(name, ICON_WITH_TEXT_SIZE, accent))
    button.setIconSize(QSize(ICON_WITH_TEXT_SIZE, ICON_WITH_TEXT_SIZE))
    return button


if TYPE_CHECKING:
    from fontvertx.gui.profile_options import ProfileOptionsPanel

__all__ = [
    "CRITERIA",
    "OrganizationDialog",
    "available_organization_criteria",
    "organization_preview_values",
]


def organization_preview_values(
    conversion: str, panel: ProfileOptionsPanel
) -> tuple[dict[str, str], str]:
    """Sample values and file extension for the organization preview of a profile."""
    profile = PROFILES.get(conversion)
    format_: str = panel.selected_web_format() or "woff2"
    if conversion != "ft2wf":
        format_ = "opentype"
    upm = str(panel.target_upm.value()) if panel.use_target_upm.isChecked() else "1000"
    values = {
        "family": "Sample Family",
        "format": format_,
        "outline": profile.outline if profile is not None else "tt",
        "upm": upm,
        "tolerance": f"{panel.tolerance.value():g}",
        "simplify": str(panel.simplify.value()),
    }
    template = profile.extension if profile is not None else ".ttf"
    return values, template.replace("{format}", format_)


CRITERIA: dict[str, str] = {
    "family": "Family",
    "format": "Format",
    "outline": "Outline type",
    "upm": "UPM",
    "tolerance": "Tolerance",
    "simplify": "Contour simplification",
}


@dataclass
class _LevelRow:
    widget: _AnimatedFrame
    number: QLabel
    criteria_layout: QGridLayout
    add_criterion: QPushButton
    move_up: QPushButton
    move_down: QPushButton
    remove_level: QPushButton
    combos: list[QComboBox] = field(default_factory=list)
    criterion_moves: dict[QComboBox, tuple[QPushButton, QPushButton]] = field(default_factory=dict)
    criterion_removes: dict[QComboBox, QPushButton] = field(default_factory=dict)


class OrganizationDialog(QDialog):
    """Configure ordered directory levels, with multiple criteria per level."""

    def __init__(
        self,
        conversion: str,
        levels: tuple[tuple[str, ...], ...],
        values: dict[str, str],
        extension: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Organize output")
        self.setMinimumWidth(680)
        self.resize(800, 360)
        self._available = available_organization_criteria(conversion)
        self._values = values
        self._extension = extension
        self._rows: list[_LevelRow] = []
        self._previous: dict[QComboBox, str] = {}
        self._models: dict[QComboBox, QStandardItemModel] = {}
        self._swap_animation: _SwapAnimation | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(8)
        intro = QLabel(
            "Choose font properties to organize your output. Criteria in the same level are "
            "joined with “_”; separate levels create nested folders, like family_format/outline."
        )
        intro.setObjectName("organizationIntro")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(section_heading("Folder levels", "organizationSection"))
        self._levels_layout = QVBoxLayout()
        self._levels_layout.setSpacing(7)
        layout.addLayout(self._levels_layout)
        self.empty_hint = QLabel(
            "No folder levels: files will be saved directly in the chosen output location."
        )
        self.empty_hint.setObjectName("hint")
        self.empty_hint.setWordWrap(True)
        layout.addWidget(self.empty_hint)

        actions = QHBoxLayout()
        self.add_level_button = _text_icon_button(
            "Add folder level", "add", "organizationAddButton", accent=True
        )
        self.add_level_button.clicked.connect(lambda: self._add_level())
        actions.addWidget(self.add_level_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.criteria_exhausted_hint = QLabel(
            "All available criteria are already in use. Remove one to add it elsewhere."
        )
        self.criteria_exhausted_hint.setObjectName("hint")
        self.criteria_exhausted_hint.setWordWrap(True)
        layout.addWidget(self.criteria_exhausted_hint)

        self.preview_section = QWidget()
        preview_layout = QVBoxLayout(self.preview_section)
        preview_layout.setContentsMargins(0, 10, 0, 0)
        preview_layout.setSpacing(6)
        preview_layout.addWidget(section_heading("Example", "organizationSection"))
        preview_hint = QLabel(
            "Folder names and the file name are examples; actual output depends on the font."
        )
        preview_hint.setObjectName("exampleHint")
        preview_hint.setWordWrap(True)
        preview_layout.addWidget(preview_hint)
        self.preview = ExamplePathLabel()
        self.preview.setProperty("previewContext", "dialog")
        preview_layout.addWidget(self.preview)
        layout.addWidget(self.preview_section)
        layout.addStretch()
        layout.addSpacing(8)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults
        )
        apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if apply_button is not None:
            apply_button.setText("Apply")
            apply_button.setObjectName("primaryButton")
        self.restore_defaults_button = self.buttons.button(
            QDialogButtonBox.StandardButton.RestoreDefaults
        )
        if self.restore_defaults_button is not None:
            self.restore_defaults_button.setText("Restore defaults")
            self.restore_defaults_button.setToolTip(
                wrap_tip(
                    "Remove every folder level: files are saved directly in the output location."
                )
            )
            self.restore_defaults_button.clicked.connect(self._restore_defaults)
        self.buttons.setObjectName("organizationButtons")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        for level in levels:
            supported = tuple(key for key in level if key in self._available)
            if supported:
                self._add_level(supported)
        self._refresh()

    @property
    def levels(self) -> tuple[tuple[str, ...], ...]:
        return tuple(tuple(str(combo.currentData()) for combo in row.combos) for row in self._rows)

    def event(self, event: QEvent) -> bool:
        result = super().event(event)
        if event.type() in (QEvent.Type.LayoutRequest, QEvent.Type.Show) and self.isVisible():
            self._ensure_content_height()
        return result

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._ensure_content_height()

    def done(self, result: int) -> None:
        self._finish_swap_animation()
        super().done(result)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._finish_swap_animation()
        super().closeEvent(event)

    def _ensure_content_height(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.activate()
            required_height = layout.heightForWidth(self.width())
            if required_height > self.height():
                self.resize(self.width(), required_height)

    def _add_level(self, criteria: tuple[str, ...] | None = None, *_: object) -> None:
        focus_new_level = criteria is None and self.add_level_button.hasFocus()
        used = {key for level in self.levels for key in level}
        choices = [key for key in self._available if key not in used]
        if criteria is None:
            if not choices:
                return
            criteria = (choices[0],)
        row_widget = _AnimatedFrame(self)
        row_widget.setObjectName("organizationLevel")
        row_layout = QVBoxLayout(row_widget)
        row_layout.setContentsMargins(12, 9, 12, 10)
        row_layout.setSpacing(8)
        header_layout = QHBoxLayout()
        number = QLabel()
        number.setObjectName("organizationLevelNumber")
        header_layout.addWidget(number)
        header_layout.addWidget(QLabel("Folder level"))
        header_layout.addStretch()
        move_up = _icon_button(
            "arrow_upward", "organizationIconButton", "Move this folder level up", "Move level up"
        )
        move_down = _icon_button(
            "arrow_downward",
            "organizationIconButton",
            "Move this folder level down",
            "Move level down",
        )
        remove_level = _text_icon_button("Remove level", "remove", "organizationRemoveButton")
        remove_level.setToolTip("Remove this folder level and all its criteria.")
        remove_level.setAccessibleName("Remove folder level and all its criteria")
        header_layout.addWidget(move_up)
        header_layout.addWidget(move_down)
        header_layout.addWidget(remove_level)
        row_layout.addLayout(header_layout)

        criteria_layout = QGridLayout()
        criteria_layout.setContentsMargins(0, 0, 0, 0)
        criteria_layout.setHorizontalSpacing(8)
        criteria_layout.setVerticalSpacing(6)
        row_layout.addLayout(criteria_layout)
        add_criterion = _text_icon_button(
            "Add criterion", "add", "organizationAddCriterionButton", accent=True
        )
        row_layout.addWidget(add_criterion, 0, Qt.AlignmentFlag.AlignLeft)
        row = _LevelRow(
            row_widget, number, criteria_layout, add_criterion, move_up, move_down, remove_level
        )
        add_criterion.clicked.connect(lambda: self._add_criterion(row))
        move_up.clicked.connect(lambda: self._move_level(row, -1))
        move_down.clicked.connect(lambda: self._move_level(row, 1))
        remove_level.clicked.connect(lambda: self._remove_level(row))
        for criterion in criteria:
            self._append_criterion(row, criterion)
        self._rows.append(row)
        self._refresh()
        if focus_new_level:
            row.combos[0].setFocus()

    def _append_criterion(self, row: _LevelRow, criterion: str) -> None:
        combo = PopupComboBox()
        combo.setMinimumWidth(130)
        combo.setProperty("compact", True)
        combo.setItemDelegate(ComboItemDelegate(combo, 32))
        model = QStandardItemModel(combo)
        for key in self._available:
            item = QStandardItem(CRITERIA[key])
            item.setData(key, Qt.ItemDataRole.UserRole)
            model.appendRow(item)
        combo.setModel(model)
        combo.setCurrentIndex(combo.findData(criterion))
        combo.currentIndexChanged.connect(
            lambda _index, current=combo: self._criterion_changed(current)
        )
        move_left = _icon_button(
            "arrow_back",
            "organizationIconButton",
            "Move this criterion earlier in the folder name.",
            "Move criterion earlier",
        )
        move_left.clicked.connect(lambda: self._move_criterion(row, combo, -1))
        move_right = _icon_button(
            "arrow_forward",
            "organizationIconButton",
            "Move this criterion later in the folder name.",
            "Move criterion later",
        )
        move_right.clicked.connect(lambda: self._move_criterion(row, combo, 1))
        remove = _icon_button(
            "close",
            "organizationRemoveCriterionButton",
            "Remove this criterion; removing the last one also removes the level.",
            "Remove criterion",
        )
        remove.clicked.connect(lambda: self._remove_criterion(row, combo))
        wrapper = _AnimatedWidget()
        wrapper_layout = QHBoxLayout(wrapper)
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.setSpacing(2)
        wrapper_layout.addWidget(combo)
        wrapper_layout.addWidget(move_left)
        wrapper_layout.addWidget(move_right)
        wrapper_layout.addWidget(remove)
        row.combos.append(combo)
        row.criterion_moves[combo] = (move_left, move_right)
        row.criterion_removes[combo] = remove
        self._layout_criteria(row)
        self._previous[combo] = criterion
        self._models[combo] = model

    def _add_criterion(self, row: _LevelRow) -> None:
        focus_new_criterion = row.add_criterion.hasFocus()
        used = {key for level in self.levels for key in level}
        criterion = next((key for key in self._available if key not in used), None)
        if criterion is not None:
            self._append_criterion(row, criterion)
            self._refresh()
            if focus_new_criterion:
                row.combos[-1].setFocus()

    def _criterion_changed(self, combo: QComboBox) -> None:
        selected = str(combo.currentData())
        if any(
            other is not combo and other.currentData() == selected for other in self._all_combos()
        ):
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData(self._previous[combo]))
            combo.blockSignals(False)
            return
        self._previous[combo] = selected
        self._refresh()

    def _remove_criterion(self, row: _LevelRow, combo: QComboBox) -> None:
        self._finish_swap_animation()
        wrapper = combo.parentWidget()
        focused = self.focusWidget()
        focus_removed = (
            wrapper is not None
            and focused is not None
            and (focused is wrapper or wrapper.isAncestorOf(focused))
        )
        index = row.combos.index(combo)
        if combo in row.combos:
            row.combos.remove(combo)
        row.criterion_moves.pop(combo, None)
        row.criterion_removes.pop(combo, None)
        if wrapper is not None:
            row.criteria_layout.removeWidget(wrapper)
            wrapper.hide()
            wrapper.deleteLater()
        self._previous.pop(combo, None)
        self._models.pop(combo, None)
        if not row.combos:
            # _remove_level already moves the focus out of the removed row.
            self._remove_level(row)
        else:
            self._layout_criteria(row)
            self._refresh()
            if focus_removed:
                row.combos[min(index, len(row.combos) - 1)].setFocus()

    def _remove_level(self, row: _LevelRow) -> None:
        self._finish_swap_animation()
        focused = self.focusWidget()
        focus_removed = focused is not None and (
            focused is row.widget or row.widget.isAncestorOf(focused)
        )
        index = self._rows.index(row)
        if row in self._rows:
            self._rows.remove(row)
        for combo in row.combos:
            self._previous.pop(combo, None)
            self._models.pop(combo, None)
        self._levels_layout.removeWidget(row.widget)
        row.widget.hide()
        row.widget.deleteLater()
        self._refresh()
        if focus_removed:
            if self._rows:
                self._rows[min(index, len(self._rows) - 1)].combos[0].setFocus()
            else:
                self.add_level_button.setFocus()

    def _restore_defaults(self) -> None:
        """Factory default: no folder levels."""
        had_focus = self.restore_defaults_button is not None and (
            self.restore_defaults_button.hasFocus()
        )
        for row in list(self._rows):
            self._remove_level(row)
        if had_focus:
            self.add_level_button.setFocus()

    def _move_level(self, row: _LevelRow, offset: int) -> None:
        self._finish_swap_animation()
        focused = self.focusWidget()
        index = self._rows.index(row)
        target = index + offset
        if 0 <= target < len(self._rows):
            animation = (
                _SwapAnimation(
                    row.widget,
                    self._rows[target].widget,
                    SWAP_DURATION_MS,
                    QEasingCurve.Type.OutCubic,
                )
                if _animations_enabled()
                else None
            )
            self._rows[index], self._rows[target] = self._rows[target], self._rows[index]
            self._refresh()
            if animation is not None:
                animation.start(row.widget, self._levels_layout)
                self._swap_animation = animation
            if focused in (row.move_up, row.move_down) and not focused.isEnabled():
                opposite = row.move_down if focused is row.move_up else row.move_up
                opposite.setFocus()

    def _move_criterion(self, row: _LevelRow, combo: QComboBox, offset: int) -> None:
        self._finish_swap_animation()
        focused = self.focusWidget()
        index = row.combos.index(combo)
        target = index + offset
        if 0 <= target < len(row.combos):
            moved_wrapper = combo.parentWidget()
            other_wrapper = row.combos[target].parentWidget()
            animation = (
                _SwapAnimation(
                    moved_wrapper,
                    other_wrapper,
                    SWAP_DURATION_MS,
                    QEasingCurve.Type.OutCubic,
                )
                if _animations_enabled()
                and isinstance(moved_wrapper, _AnimatedWidget)
                and isinstance(other_wrapper, _AnimatedWidget)
                else None
            )
            row.combos[index], row.combos[target] = row.combos[target], row.combos[index]
            self._layout_criteria(row)
            self._refresh()
            if animation is not None and isinstance(moved_wrapper, _AnimatedWidget):
                animation.start(moved_wrapper, row.criteria_layout)
                self._swap_animation = animation
            if focused in row.criterion_moves[combo] and not focused.isEnabled():
                move_left, move_right = row.criterion_moves[combo]
                opposite = move_right if focused is move_left else move_left
                opposite.setFocus()

    def _finish_swap_animation(self) -> None:
        if self._swap_animation is not None:
            self._swap_animation.finish()
            self._swap_animation = None

    def _all_combos(self) -> list[QComboBox]:
        return [combo for row in self._rows for combo in row.combos]

    @staticmethod
    def _layout_criteria(row: _LevelRow) -> None:
        # takeAt detaches the wrappers from the grid; their parent stays row.widget.
        while row.criteria_layout.count():
            row.criteria_layout.takeAt(0)
        for index, combo in enumerate(row.combos):
            wrapper = combo.parentWidget()
            if wrapper is not None:
                row.criteria_layout.addWidget(wrapper, index // 2, index % 2)

    def _refresh(self) -> None:
        used = {key for level in self.levels for key in level}
        has_available_criteria = any(key not in used for key in self._available)
        self.criteria_exhausted_hint.setVisible(not has_available_criteria)
        self.add_level_button.setEnabled(has_available_criteria)
        self.empty_hint.setVisible(not self._rows)
        if self.restore_defaults_button is not None:
            self.restore_defaults_button.setEnabled(bool(self._rows))
        for index, row in enumerate(self._rows):
            row.number.setText(str(index + 1))
            self._levels_layout.removeWidget(row.widget)
            self._levels_layout.insertWidget(index, row.widget)
            row.move_up.setEnabled(index > 0)
            row.move_down.setEnabled(index < len(self._rows) - 1)
            row.add_criterion.setEnabled(has_available_criteria)
            for position, combo in enumerate(row.combos):
                move_left, move_right = row.criterion_moves[combo]
                move_left.setEnabled(position > 0)
                move_right.setEnabled(position < len(row.combos) - 1)
                used_by_others = used - {str(combo.currentData())}
                model = self._models[combo]
                for item_index, key in enumerate(self._available):
                    item = model.item(item_index)
                    if item is not None:
                        item.setEnabled(key not in used_by_others)
        pieces = [organization_level_name(level, self._values) for level in self.levels]
        suffix = "/" if pieces else ""
        self.preview.set_path(f"{'/'.join(pieces)}{suffix}font{self._extension}")
        self._configure_tab_order()
        QTimer.singleShot(0, self, self._ensure_content_height)

    def _configure_tab_order(self) -> None:
        chain: list[QWidget] = []
        for row in self._rows:
            chain.extend((row.move_up, row.move_down, row.remove_level))
            for combo in row.combos:
                chain.append(combo)
                chain.extend(row.criterion_moves[combo])
                chain.append(row.criterion_removes[combo])
            chain.append(row.add_criterion)
        chain.append(self.add_level_button)
        for role in (
            QDialogButtonBox.StandardButton.RestoreDefaults,
            QDialogButtonBox.StandardButton.Ok,
            QDialogButtonBox.StandardButton.Cancel,
        ):
            button = self.buttons.button(role)
            if button is not None:
                chain.append(button)
        for current, following in zip(chain, chain[1:], strict=False):
            QWidget.setTabOrder(current, following)
