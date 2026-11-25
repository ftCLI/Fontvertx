"""Responsive layout logic for the converter window.

The window owns the widgets; this module owns everything about how they are
arranged and resized: breakpoints, margins, text wrapping and sidebar metrics.
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QAbstractButton, QBoxLayout, QSizePolicy

from fontvertx.gui.profiles import CONVERSIONS
from fontvertx.gui.styles import CONVERT_PADDING_H, FIELD_BORDER, FOOTER_GAP

# Layout constants (pixels)
WINDOW_MIN_SIZE = QSize(800, 500)
WINDOW_PREFERRED_SIZE = QSize(1200, 880)
SCREEN_MARGIN_H = 40
SCREEN_MARGIN_V = 80
PAGE_MARGIN_H = FOOTER_GAP  # cards line up with the footer blocks
PAGE_MARGIN_TOP = 20
PAGE_MARGIN_BOTTOM = 14
CARD_GAP = 14  # between cards, and between the body and the footer blocks
CARD_PADDING = 16  # inner padding of every card
BODY_BREAKPOINT = 1055  # min window width for the horizontal body layout
CARD_MARGIN_H = CARD_PADDING
CONTENT_MARGIN = 2 * CARD_MARGIN_H + 2  # card margins + card border around the input controls
MIN_SIDEBAR_HEIGHT = 200
QWIDGETSIZE_MAX = (1 << 24) - 1  # Qt's default maximum widget size
SIDEBAR_SLACK = 2 * PAGE_MARGIN_H  # page side margins around the body
OPTIONS_ROW_SLACK = 70
# Checkbox text wrapping: indicator 16 + spacing 8 + padding 2x2 + focus border 2x2 = 32,
# plus a small safety margin.
BUTTON_PADDING_WIDE = 36
# Convert's fixed width fits the widest label it can show.
CONVERT_WIDEST_LABELS = ("Convert 9999 instances", "Convert 9999 fonts")
CONVERT_ICON_GAP = 8  # icon-to-text gap, with a safety margin over the style's 4px


def _window_sizes(available: QSize | None) -> tuple[QSize, QSize]:
    minimum = WINDOW_MIN_SIZE
    preferred = WINDOW_PREFERRED_SIZE
    if available is None:
        return minimum, preferred
    usable = QSize(
        max(1, available.width() - SCREEN_MARGIN_H), max(1, available.height() - SCREEN_MARGIN_V)
    )
    return minimum.boundedTo(usable), preferred.boundedTo(usable)


class LayoutManager:
    """Applies the responsive layout rules to the widgets of a ConverterWindow."""

    def __init__(self, window) -> None:
        self.w = window
        self._convert_width_key: tuple[str, float] | None = None
        self._sidebar_stacked: bool | None = None

    def sync_footer_margins(self) -> None:
        self.update_body()

    def update_body(self) -> None:
        w = self.w
        direction = (
            QBoxLayout.Direction.LeftToRight
            if w.width() >= BODY_BREAKPOINT
            else QBoxLayout.Direction.TopToBottom
        )
        if w.body_layout.direction() != direction:
            w.body_layout.setDirection(direction)
        horizontal = direction == QBoxLayout.Direction.LeftToRight
        # One source of truth: the footer's result buttons are icon-only exactly while
        # the cards are stacked, during a run and after it.
        w.status_pill.set_compact(not horizontal)
        w.body_layout.setStretch(0, 1)
        w.body_layout.setStretch(1, 0)
        w.sidebar_scroll.setSizePolicy(
            QSizePolicy.Policy.Maximum if horizontal else QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        sidebar = w.sidebar_scroll.widget()
        sidebar_width = self.sidebar_width()
        if horizontal:
            w.sidebar_scroll.setFixedWidth(sidebar_width)
        else:
            w.sidebar_scroll.setMaximumWidth(w._sidebar_maximum_width)
            w.sidebar_scroll.setMinimumWidth(
                min(
                    sidebar.minimumSizeHint().width(),
                    max(0, w.content_scroll.viewport().width() - SIDEBAR_SLACK),
                )
                if sidebar is not None
                else 0
            )
        available = w.width() - SIDEBAR_SLACK
        if horizontal:
            available -= sidebar_width + w.body_layout.spacing()
        if w.content_scroll.verticalScrollBar().isVisible():
            available -= w.content_scroll.verticalScrollBar().width()
        self.update_input(available - CONTENT_MARGIN)
        self.set_sidebar_stacked(not horizontal)
        self.update_footer()

    def set_sidebar_stacked(self, stacked: bool) -> None:
        """Side by side, the sidebar scrolls by itself with its overlay bar and fade.
        Stacked, it is exactly as tall as its content and only the page scrolls."""
        w = self.w
        if stacked != self._sidebar_stacked:
            self._sidebar_stacked = stacked
            w.sidebar_scrollbar.set_suspended(stacked)
            w.sidebar_overflow_fade.set_suspended(stacked)
            if not stacked:
                w.sidebar_scroll.setMinimumHeight(MIN_SIDEBAR_HEIGHT)
                w.sidebar_scroll.setMaximumHeight(QWIDGETSIZE_MAX)
        self.sync_stacked_sidebar_height()

    def sync_stacked_sidebar_height(self) -> None:
        """In the stacked layout, fix the sidebar's height to its content's height at
        its current width (wrapped text included). Called again whenever the content
        changes or the sidebar is resized."""
        w = self.w
        sidebar = w.sidebar_scroll.widget()
        if not self._sidebar_stacked or sidebar is None:
            return
        # The scroll area never makes its widget narrower than its minimum size hint.
        width = max(w.sidebar_scroll.viewport().width(), sidebar.minimumSizeHint().width())
        height = sidebar.heightForWidth(width) if sidebar.hasHeightForWidth() else -1
        if height < 0:
            height = sidebar.sizeHint().height()
        height = max(height, sidebar.minimumSizeHint().height())
        w.sidebar_scroll.setFixedHeight(height + 2 * w.sidebar_scroll.frameWidth())

    def sidebar_width(self) -> int:
        """Width of the sidebar cards in the horizontal layout."""
        w = self.w
        conversion_layout = w.conversion_group.layout()
        if conversion_layout is not None:
            conversion_layout.invalidate()
        widths = [
            w.conversion_group.sizeHint().width(),
            w.destination_group.minimumSizeHint().width(),
            w._profile_options_width,
        ]
        if not w.profile_options.isHidden():
            widths.append(w.profile_options.minimumSizeHint().width())
        return max(widths)

    def update_footer(self) -> None:
        """Line the footer card up with the content above it and size Convert.

        The card spans from the files card's left edge to the sidebar cards' right edge:
        the page side margins, plus the content scrollbar on the right (it narrows the
        body). It takes no part in the body's width calculations.
        """
        w = self.w
        scrollbar = w.content_scroll.verticalScrollBar()
        right_inset = scrollbar.width() if scrollbar.isVisible() else 0
        w.footer_outer_layout.setContentsMargins(
            PAGE_MARGIN_H, 0, PAGE_MARGIN_H + right_inset, FOOTER_GAP
        )
        self.sync_convert_width()

    def sync_convert_width(self) -> None:
        """Fixed Convert width from its widest label; recomputed only when the font or
        the screen scale changes, so it never moves while the font count changes."""
        button = self.w.convert_button
        button.ensurePolished()
        key = (button.font().key(), button.devicePixelRatioF())
        if key == self._convert_width_key:
            return
        self._convert_width_key = key
        metrics = button.fontMetrics()
        text = max(metrics.horizontalAdvance(label) for label in CONVERT_WIDEST_LABELS)
        width = (
            text
            + button.iconSize().width()
            + CONVERT_ICON_GAP
            + 2 * CONVERT_PADDING_H
            + 2 * FIELD_BORDER
        )
        button.setFixedWidth(width)
        # Pause / Cancel take Convert's place with the same width.
        self.w.primary_slot.setFixedWidth(width)

    def update_input(self, width: int) -> None:
        w = self.w
        horizontal = QBoxLayout.Direction.LeftToRight
        vertical = QBoxLayout.Direction.TopToBottom
        self.wrap_button_text(w.hide_incompatible, "Hide incompatible", width, BUTTON_PADDING_WIDE)
        self.wrap_button_text(w.select_all_checkbox, "Select all", width, BUTTON_PADDING_WIDE)
        # Hidden controls take no room: the expand / collapse buttons only count in
        # instance mode, so the other profiles keep their wider breakpoint.
        fixed = [
            w.select_all_checkbox,
            w.hide_incompatible,
            w.clear_button,
            w.expand_instances_button,
            w.collapse_instances_button,
        ]
        shown = [control for control in fixed if not control.isHidden()] or fixed[:3]
        options_width = (
            sum(control.sizeHint().expandedTo(control.minimumSize()).width() for control in shown)
            + OPTIONS_ROW_SLACK
            + len(shown) * w.file_options_row.spacing()
        )
        w.file_options_row.setDirection(horizontal if width >= options_width else vertical)

    def refresh_sidebar_metrics(self) -> None:
        from fontvertx.gui.profile_options import ProfileOptionsPanel

        w = self.w
        w.organization_button.setMinimumWidth(w.organization_button.sizeHint().width())
        destination_layout = w.destination_group.layout()
        if destination_layout is not None:
            destination_layout.invalidate()
            destination_layout.activate()
        # Measuring the options panel is expensive (off-screen widget, full stylesheet,
        # one layout pass per profile): do it once, the result does not change at runtime.
        if not w._sidebar_metrics_measured:
            w._sidebar_metrics_measured = True
            panel = ProfileOptionsPanel()
            panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
            panel.setStyleSheet(w.styleSheet())
            panel.show()
            widest = 0
            for conversion in CONVERSIONS:
                panel.set_conversion(conversion)
                layout = panel.layout()
                if layout is not None:
                    layout.invalidate()
                    layout.activate()
                widest = max(widest, panel.minimumSizeHint().width())
            panel.close()
            panel.deleteLater()
            w._profile_options_width = widest
        self.update_body()

    @staticmethod
    def wrap_button_text(button: QAbstractButton, text: str, width: int, padding: int) -> None:
        lines: list[str] = []
        for word in text.split():
            candidate = f"{lines[-1]} {word}" if lines else word
            if lines and button.fontMetrics().horizontalAdvance(candidate) + padding > width:
                lines.append(word)
            elif lines:
                lines[-1] = candidate
            else:
                lines.append(word)
        wrapped = "\n".join(lines)
        if button.text() != wrapped:
            button.setText(wrapped)
