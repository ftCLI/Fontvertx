"""Native Fontvertx converter window."""

from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QSettings,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QIcon,
    QKeySequence,
    QResizeEvent,
    QShortcut,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QBoxLayout,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from fontvertx.gui.conversion_controller import ConversionController
from fontvertx.gui.conversion_dialog import ConversionDialog
from fontvertx.gui.file_list import FontFileList
from fontvertx.gui.icons import material_icon
from fontvertx.gui.instance_tree import InstanceTree
from fontvertx.gui.layout_manager import (
    CARD_GAP,
    PAGE_MARGIN_BOTTOM,
    PAGE_MARGIN_H,
    PAGE_MARGIN_TOP,
    LayoutManager,
    _window_sizes,
)
from fontvertx.gui.logs import LogEntry
from fontvertx.gui.organization_dialog import (
    CRITERIA,
    OrganizationDialog,
    available_organization_criteria,
    organization_preview_values,
)
from fontvertx.gui.panels.conversion_panel import build_conversion_card
from fontvertx.gui.panels.destination_panel import build_destination_card
from fontvertx.gui.panels.source_panel import (
    FONT_FILTER_PLACEHOLDER,
    build_source_card,
    list_status_text,
    place_drop_zone,
    scan_label_width,
    sync_drop_zone_height,
)
from fontvertx.gui.profile_options import FACTORY_DEFAULTS, ProfileOptionsPanel
from fontvertx.gui.profiles import CONVERSIONS
from fontvertx.gui.scanner import Source
from fontvertx.gui.settings_store import (
    INPUT_DIR_KEY,
    LOG_DIR_KEY,
    MODIFY_RIGHTS_KEY,
    OPTION_KEYS,
    OPTIONAL_FONT_COLUMNS,
    OUTPUT_DIR_KEY,
    SettingsStore,
)
from fontvertx.gui.status_pill import StatusPill, StatusState
from fontvertx.gui.styles import (
    FOOTER_CARD_BORDER,
    FOOTER_CARD_HEIGHT,
    FOOTER_GAP,
    FOOTER_HEIGHT,
    FOOTER_PAD_LEFT,
    FOOTER_PAD_RIGHT,
    FOOTER_PAD_V,
    LIGHT,
    stylesheet,
)
from fontvertx.gui.widgets import (
    ConversionSelector,
    DropZone,
    ElidedLabel,
    ExamplePathLabel,
    FileTable,
    FolderSplitButton,
    KeyboardPushButton,
    OverlayScrollBar,
    ScrollOverflowFade,
    StepBadge,
)
from fontvertx.gui.worker import ConversionWorker, RunState
from fontvertx.inspection import FontInfo, incompatibility
from fontvertx.models import (
    ConversionOptions,
    ConversionRequest,
    ConversionResult,
    ConversionSettings,
)
from fontvertx.service import organization_level_name

FONT_FILE_FILTER = "Font files (*.ttf *.otf *.woff *.woff2 *.ttc *.otc);;All files (*)"

__all__ = [
    "FONT_FILE_FILTER",
    "OPTIONAL_FONT_COLUMNS",  # re-exported for tests
    "ConverterWindow",
    "_window_sizes",  # re-exported for tests
]


class ConverterWindow(QMainWindow):
    # Widgets built by the panel builders (fontvertx.gui.panels).
    conversion: ConversionSelector
    profile_options: ProfileOptionsPanel
    add_button: KeyboardPushButton
    add_folder_button: KeyboardPushButton
    folder_split: FolderSplitButton
    clear_button: KeyboardPushButton
    select_all_checkbox: QCheckBox
    hide_incompatible: QCheckBox
    font_filter: QLineEdit
    file_options_row: QBoxLayout
    expand_instances_button: KeyboardPushButton
    collapse_instances_button: KeyboardPushButton
    files: FileTable
    file_list: FontFileList
    column_menu: QMenu
    instance_tree: InstanceTree
    files_stack: QStackedWidget
    drop_zone: DropZone
    drop_slot: QWidget
    files_column: QWidget
    files_column_layout: QVBoxLayout
    files_header: QWidget
    files_header_line: QFrame
    files_group_layout: QVBoxLayout
    scan_widget: QWidget
    scan_label: QLabel
    scan_progress: QProgressBar
    scan_stop_button: KeyboardPushButton
    overwrite: QCheckBox
    recalc_bboxes: QCheckBox
    recalc_timestamp: QCheckBox
    reorder_tables: QCheckBox
    organization_button: KeyboardPushButton
    destination_source_radio: QRadioButton
    destination_folder_radio: QRadioButton
    destination_mode_group: QButtonGroup
    destination_edit: QLineEdit
    destination_button: KeyboardPushButton
    organization_preview: ExamplePathLabel
    organization_example: QWidget
    overwrite_panel: QFrame

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Fontvertx")
        screen = self.screen()
        available = screen.availableGeometry().size() if screen is not None else None
        minimum, initial = _window_sizes(available)
        self.setMinimumSize(minimum)
        self.resize(initial)
        self.output_directory: Path | None = None
        self.organization_levels: tuple[tuple[str, ...], ...] = ()
        self._settings = QSettings()
        self.store = SettingsStore(self._settings)
        self._sources: list[Source] = []
        self._scan_cancelled = False
        self._scan_counts = (0, 0)
        self._input_check_states: dict[Path, bool] = {}
        self._log_entries: list[LogEntry] = []
        self._profile_options_width = 0
        self._active_profile: str | None = None
        # While True, widget changes caused by restore() are not written back to the store.
        self._suspend_profile_save = False
        self._sidebar_metrics_measured = False
        self._initial_focus_set = False
        self._layout_signature: tuple[bool, bool, bool] | None = None
        self._layout = LayoutManager(self)
        self.converter = ConversionController(self)

        page = QWidget()
        page.setObjectName("page")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PAGE_MARGIN_H, PAGE_MARGIN_TOP, PAGE_MARGIN_H, PAGE_MARGIN_BOTTOM)
        layout.setSpacing(CARD_GAP)

        self.conversion_group = build_conversion_card(self)
        self.files_group = build_source_card(self)
        self.destination_group = build_destination_card(self)
        cards = (
            self.files_group,
            self.conversion_group,
            self.profile_options,
            self.destination_group,
        )
        self._step_badges = tuple(
            badge
            for card in cards
            if (badge := card.findChild(StepBadge, "cardNumber")) is not None
        )
        if len(self._step_badges) != 4:
            raise RuntimeError("Each converter card must have a numbered step badge.")

        sidebar = QWidget()
        sidebar.setObjectName("page")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(CARD_GAP)
        sidebar_layout.addWidget(self.conversion_group)
        sidebar_layout.addWidget(self.profile_options)
        sidebar_layout.addWidget(self.destination_group)
        sidebar_layout.addStretch()
        self.sidebar_scroll = QScrollArea()
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.sidebar_scroll.setWidget(sidebar)
        self.sidebar_overflow_fade = ScrollOverflowFade(self.sidebar_scroll)
        self.sidebar_scrollbar = OverlayScrollBar(self.sidebar_scroll)
        self.sidebar_scroll.setMinimumSize(0, 200)
        self._sidebar_maximum_width = self.sidebar_scroll.maximumWidth()
        self.sidebar_scroll.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Expanding)

        self.body_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.body_layout.setSpacing(CARD_GAP)
        self.body_layout.addWidget(self.files_column, 1)
        self.body_layout.addWidget(self.sidebar_scroll)
        layout.addLayout(self.body_layout, 1)

        self.convert_button = KeyboardPushButton("Convert")
        self._convert_icon = material_icon(
            "sync_alt", LIGHT.on_primary, size=20, disabled_color=LIGHT.convert_disabled_text
        )
        self.convert_button.setIcon(self._convert_icon)
        self.convert_button.setIconSize(QSize(20, 20))
        self.convert_button.setObjectName("primaryButton")
        self.convert_button.setProperty("footerPrimary", True)
        # Width: the sidebar cards' width, set by LayoutManager.update_footer.
        self.convert_button.setFixedHeight(FOOTER_HEIGHT)
        self.convert_button.setDefault(True)
        self.convert_button.setToolTip("Start conversion (Ctrl+Enter).")
        # Ctrl+Return (main keyboard) and Ctrl+Enter (keypad) are distinct keys in Qt.
        self.convert_shortcuts = [
            QShortcut(QKeySequence(key), self) for key in ("Ctrl+Return", "Ctrl+Enter")
        ]
        for shortcut in self.convert_shortcuts:
            shortcut.activated.connect(self.convert_button.click)
        self.convert_button.setEnabled(False)
        self.conversion_dialog = ConversionDialog(self)
        self.cancel_button = self.conversion_dialog.cancel_button
        self.pause_button = self.conversion_dialog.pause_button
        self.progress = self.conversion_dialog.progress
        self.log = self.conversion_dialog.log
        self.save_logs_button = self.conversion_dialog.save_logs_button
        self.summary = ElidedLabel()
        self.summary.setObjectName("footerSummary")
        self.summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.history_button = KeyboardPushButton("View last run")
        self.history_button.setObjectName("footerHistory")
        self.history_button.setIcon(material_icon("history", LIGHT.accent, size=16))
        self.history_button.setIconSize(QSize(16, 16))
        self.history_button.hide()
        self.summary_zone = QWidget()
        summary_layout = QHBoxLayout(self.summary_zone)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(10)
        summary_layout.addWidget(self.summary, 1)
        summary_layout.addWidget(self.history_button)
        self.status_pill = StatusPill()
        self.last_run_button = self.status_pill.last_run_button
        self.open_output_button = self.status_pill.output_button
        self.last_run_button.setEnabled(False)
        self.open_output_button.setEnabled(False)
        self._last_status: tuple[StatusState, str] | None = None
        self.status_zone = QStackedWidget()
        self.status_zone.setFixedHeight(FOOTER_HEIGHT)
        self.status_zone.setMinimumWidth(0)
        self.status_zone.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.status_zone.addWidget(self.summary_zone)
        self.status_zone.addWidget(self.status_pill)
        self.status_zone.setCurrentWidget(self.summary_zone)
        # One card under the body, from the files card's left edge to the sidebar cards'
        # right edge (outer margins set by LayoutManager.update_footer). Its tone follows
        # the status; Convert keeps a fixed width on its right.
        self.footer = QWidget()
        self.footer.setObjectName("actionBar")
        self.footer.setFixedHeight(FOOTER_CARD_HEIGHT + FOOTER_GAP)
        self.footer_outer_layout = QHBoxLayout(self.footer)
        self.footer_outer_layout.setContentsMargins(FOOTER_GAP, 0, FOOTER_GAP, FOOTER_GAP)
        self.footer_card = QFrame()
        self.footer_card.setObjectName("footerCard")
        self.footer_card.setProperty("tone", "")
        self.footer_card.setFixedHeight(FOOTER_CARD_HEIGHT)
        self.footer_outer_layout.addWidget(self.footer_card)
        # Layout margins, not a QSS margin: the stylesheet border already insets the
        # contents by its width, so the padding is counted from the outer edge.
        self.footer_layout = QHBoxLayout(self.footer_card)
        self.footer_layout.setContentsMargins(
            FOOTER_PAD_LEFT - FOOTER_CARD_BORDER,
            FOOTER_PAD_V - FOOTER_CARD_BORDER,
            FOOTER_PAD_RIGHT - FOOTER_CARD_BORDER,
            FOOTER_PAD_V - FOOTER_CARD_BORDER,
        )
        self.footer_layout.setSpacing(CARD_GAP)
        self.footer_layout.addWidget(self.status_zone, 1)
        self.footer_layout.addWidget(self.convert_button)
        self.status_pill.toneChanged.connect(lambda _tone: self._sync_footer_tone())
        self.status_zone.currentChanged.connect(lambda _index: self._sync_footer_tone())
        self.content_scroll = QScrollArea()
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.content_scroll.setWidget(page)
        self.content_scroll.viewport().installEventFilter(self)
        central = QWidget()
        central.setObjectName("page")
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.content_scroll, 1)
        central_layout.addWidget(self.footer)
        self.setCentralWidget(central)
        self.setStyleSheet(stylesheet())
        self.scan_widget.setFixedHeight(self.scan_stop_button.sizeHint().height())

        self.add_button.clicked.connect(self._choose_files)
        self.clear_button.clicked.connect(self._clear_files)
        self.files.paths_dropped.connect(self._add_paths)
        self.instance_tree.paths_dropped.connect(self._add_paths)
        self.drop_zone.paths_dropped.connect(self._add_paths)
        self.files.selectionModel().selectionChanged.connect(lambda *_: self._update_buttons())
        self.destination_button.clicked.connect(self._choose_destination)
        self.destination_source_radio.toggled.connect(self._on_destination_mode_changed)
        self.convert_button.clicked.connect(self._start_conversion)
        self.cancel_button.clicked.connect(self._cancel_conversion)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.open_output_button.clicked.connect(self._open_output_folder)
        self.conversion_dialog.open_output_button.clicked.connect(self._open_output_folder)
        self.save_logs_button.clicked.connect(self._save_logs)
        self.last_run_button.clicked.connect(self._show_conversion_dialog)
        self.history_button.clicked.connect(self._show_conversion_dialog)
        self.status_pill.dismissed.connect(self._dismiss_status)
        self.conversion_dialog.finished.connect(self._dialog_finished)
        self._configure_tab_order()
        self.profile_options.set_conversion(None)
        self._update_body_layout()
        self._update_buttons()
        self._restore_preferences()
        self._connect_preference_persistence()
        self._connect_profile_persistence()

    # --- Conversion run state lives in self.converter; these are kept for compatibility ---

    @property
    def worker(self) -> ConversionWorker | None:
        return self.converter.worker

    @worker.setter
    def worker(self, value: ConversionWorker | None) -> None:
        self.converter.worker = value

    @property
    def _run_state(self) -> RunState:
        return self.converter.run_state

    @_run_state.setter
    def _run_state(self, value: RunState) -> None:
        self.converter.run_state = value

    @property
    def _cancelling(self) -> bool:
        return self.converter.cancelling

    @_cancelling.setter
    def _cancelling(self, value: bool) -> None:
        self.converter.cancelling = value

    @property
    def _close_when_finished(self) -> bool:
        return self.converter.close_when_finished

    @_close_when_finished.setter
    def _close_when_finished(self, value: bool) -> None:
        self.converter.close_when_finished = value

    @property
    def _session_elapsed(self) -> float:
        return self.converter.session_elapsed

    @_session_elapsed.setter
    def _session_elapsed(self, value: float) -> None:
        self.converter.session_elapsed = value

    @property
    def _session_started_at(self) -> float | None:
        return self.converter.session_started_at

    @_session_started_at.setter
    def _session_started_at(self, value: float | None) -> None:
        self.converter.session_started_at = value

    @property
    def _progress_done(self) -> int:
        return self.converter.progress_done

    @_progress_done.setter
    def _progress_done(self, value: int) -> None:
        self.converter.progress_done = value

    @property
    def _progress_total(self) -> int:
        return self.converter.progress_total

    @_progress_total.setter
    def _progress_total(self, value: int) -> None:
        self.converter.progress_total = value

    @property
    def _saved_files(self) -> list[Path]:
        return self.converter.saved_files

    @_saved_files.setter
    def _saved_files(self, value: list[Path]) -> None:
        self.converter.saved_files = value

    @property
    def _last_run_available(self) -> bool:
        return self.converter.last_run_available

    @_last_run_available.setter
    def _last_run_available(self, value: bool) -> None:
        self.converter.last_run_available = value

    @property
    def _run_output_directory(self) -> Path | None:
        return self.converter.run_output_directory

    @_run_output_directory.setter
    def _run_output_directory(self, value: Path | None) -> None:
        self.converter.run_output_directory = value

    @property
    def _run_input_directory(self) -> Path | None:
        return self.converter.run_input_directory

    @_run_input_directory.setter
    def _run_input_directory(self, value: Path | None) -> None:
        self.converter.run_input_directory = value

    @property
    def _elapsed_timer(self) -> QTimer:
        return self.converter.elapsed_timer

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "body_layout"):
            self._update_body_layout()

    def event(self, event: QEvent) -> bool:
        # Font or screen-scale changes resize nothing, but Convert's fixed width depends
        # on its font metrics.
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.DevicePixelRatioChange) and hasattr(
            self, "body_layout"
        ):
            QTimer.singleShot(0, self, self._update_body_layout)
        return super().event(event)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            hasattr(self, "content_scroll")
            and watched is self.content_scroll.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            QTimer.singleShot(0, self, self._sync_footer_margins)
        return super().eventFilter(watched, event)

    def _sync_footer_margins(self) -> None:
        self._layout.sync_footer_margins()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._refresh_sidebar_metrics)
        if not self._initial_focus_set:
            # Synchronously, before activation picks the first focusable control; later
            # focus changes (clicks, Tab, code) are never taken back.
            self._initial_focus_set = True
            self._park_focus()

    def _park_focus(self) -> None:
        """Give focus to the central widget (no focus ring) until the user tabs or clicks."""
        central = self.centralWidget()
        if central is not None:
            central.setFocus(Qt.FocusReason.OtherFocusReason)

    def focusNextPrevChild(self, next: bool) -> bool:  # noqa: A002 - Qt signature
        # From the parked focus, the first Tab starts the tab chain at "Add files…".
        if (
            next
            and QApplication.focusWidget() is self.centralWidget()
            and self.add_button.isVisible()
            and self.add_button.isEnabled()
        ):
            self.add_button.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        return super().focusNextPrevChild(next)

    def _refresh_sidebar_metrics(self) -> None:
        self._layout.refresh_sidebar_metrics()

    def _update_body_layout(self) -> None:
        self._layout.update_body()

    def _update_input_layout(self, width: int) -> None:
        self._layout.update_input(width)

    def _configure_tab_order(self) -> None:
        profile = self.profile_options
        chain: list[QWidget] = [
            self.add_button,
            self.add_folder_button,
            self.folder_split.arrow_button,
            self.select_all_checkbox,
            self.font_filter,
            self.hide_incompatible,
            self.clear_button,
            self.expand_instances_button,
            self.collapse_instances_button,
            self.files,
            self.instance_tree,
            self.conversion.combo,
            profile.reset_button,
            profile.tolerance_field.decrement_button,
            profile.tolerance,
            profile.tolerance_field.increment_button,
            profile.simplify_field.decrement_button,
            profile.simplify,
            profile.simplify_field.increment_button,
            profile.use_target_upm,
            profile.target_upm_field.decrement_button,
            profile.target_upm,
            profile.target_upm_field.increment_button,
            profile.subroutinize,
            profile.autohint,
            profile.format_woff,
            profile.format_woff2,
            profile.obfuscate_names,
            profile.remove_unused_glyphs,
            profile.remove_non_windows_names,
            profile.remove_dsig,
            profile.css_kit,
            profile.recalc_bboxes,
            profile.recalc_timestamp,
            profile.reorder_tables,
            self.destination_source_radio,
            self.destination_folder_radio,
            self.destination_button,
            self.overwrite,
            self.organization_button,
            self.history_button,
            self.last_run_button,
            self.open_output_button,
            self.status_pill.close_button,
            self.convert_button,
        ]
        for current, following in zip(chain, chain[1:], strict=False):
            QWidget.setTabOrder(current, following)

    def _show_column_menu(self, pos: QPoint) -> None:
        self.column_menu.popup(self.files.horizontalHeader().mapToGlobal(pos))

    def _set_column_visible(self, visible: bool) -> None:
        action = self.sender()
        if not isinstance(action, QAction):
            raise TypeError("Column visibility changes must come from a QAction")
        column = int(action.data())
        self.files.setColumnHidden(column, not visible)
        self.store.set_bool(OPTIONAL_FONT_COLUMNS[column][1], visible)

    def _restore_preferences(self) -> None:
        """Reload the persisted options; called once at the end of __init__."""
        for attribute, key in OPTION_KEYS.items():
            checkbox = getattr(self, attribute)
            checkbox.setChecked(self.store.get_bool(key, checkbox.isChecked()))
        # The selected conversion profile is deliberately not restored: every launch
        # starts with no profile; per-profile options load when one is chosen.
        self._update_organization_button()
        geometry = self.store.geometry
        if geometry is not None:
            self.restoreGeometry(geometry)

    def _save_active_profile_preferences(self) -> None:
        if self._active_profile is not None:
            self.store.set_profile_options(self._active_profile, self.profile_options.snapshot())
            self.store.set_organization_levels(self._active_profile, self.organization_levels)

    def _connect_preference_persistence(self) -> None:
        for attribute, key in OPTION_KEYS.items():
            getattr(self, attribute).toggled.connect(
                lambda checked, k=key: self.store.set_bool(k, checked)
            )

    def _connect_profile_persistence(self) -> None:
        self.profile_options.connect_value_changes(self._persist_active_profile_options)
        self.profile_options.connect_value_changes(self._update_profile_options_state)

    def _update_profile_options_state(self, *_: object) -> None:
        modified = self.conversion.currentData() is not None and (
            self.profile_options.snapshot() != FACTORY_DEFAULTS
        )
        chip = self.profile_options.findChild(QLabel, "modifiedChip")
        if chip is None:
            raise RuntimeError("The options card must include its modified chip.")
        chip.setVisible(modified)
        self.profile_options.reset_button.setEnabled(modified)

    def _persist_active_profile_options(self, *_: object) -> None:
        if self._suspend_profile_save or self._active_profile is None:
            return
        self.store.set_profile_options(self._active_profile, self.profile_options.snapshot())

    def _reset_active_profile_options(self) -> None:
        """Restore the active profile's options to the factory defaults."""
        if self._active_profile is None:
            return
        self.store.clear_profile_options(self._active_profile)
        self._suspend_profile_save = True
        try:
            self.profile_options.restore({})
        finally:
            self._suspend_profile_save = False
        self._update_profile_options_state()

    def _on_conversion_changed(self) -> None:
        conversion = self.conversion.currentData()
        if conversion != self._active_profile and self._last_run_available:
            self._last_status = None
            self._show_summary()
        if self._active_profile is not None and self._active_profile != conversion:
            self._save_active_profile_preferences()
        self._active_profile = conversion
        if conversion is None:
            return
        self.profile_options.set_conversion(conversion)
        self._suspend_profile_save = True
        try:
            self.profile_options.restore(self.store.profile_options(conversion))
        finally:
            self._suspend_profile_save = False
        self._update_profile_options_state()
        available = set(available_organization_criteria(conversion))
        self.organization_levels = tuple(
            filtered
            for level in self.store.organization_levels_for(conversion)
            if (filtered := tuple(key for key in level if key in available))
        )
        self._update_organization_button()
        self._update_body_layout()

    def _organization_preview(self) -> tuple[dict[str, str], str]:
        return organization_preview_values(str(self.conversion.currentData()), self.profile_options)

    def _show_organization_dialog(self) -> None:
        values, extension = self._organization_preview()
        dialog = OrganizationDialog(
            str(self.conversion.currentData()),
            self.organization_levels,
            values,
            extension,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.organization_levels = dialog.levels
            if self._active_profile is not None:
                self.store.set_organization_levels(self._active_profile, self.organization_levels)
            self._update_organization_button()
            self._update_body_layout()

    def _update_organization_button(self, *_: object) -> None:
        has_profile = self.conversion.currentData() is not None
        self.organization_example.setVisible(has_profile and bool(self.organization_levels))
        if not has_profile:
            return
        if not self.organization_levels:
            self.organization_button.setToolTip(
                "Choose how converted fonts are grouped into folders."
            )
        else:
            summary = " → ".join(
                " + ".join(CRITERIA[key] for key in level) for level in self.organization_levels
            )
            self.organization_button.setToolTip(f"Output folder levels: {summary}")
        values, extension = self._organization_preview()
        pieces = [organization_level_name(level, values) for level in self.organization_levels]
        self.organization_preview.set_path("/".join([*pieces, f"font{extension}"]))

    def _saved_dir(self, key: str) -> str:
        return self.store.saved_dir(key)

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select font files", self._saved_dir(INPUT_DIR_KEY), FONT_FILE_FILTER
        )
        if paths:
            self.store.set_dir(INPUT_DIR_KEY, str(Path(paths[0]).parent))
        self._add_paths(paths)

    def _choose_folder(self, recursive: bool = False) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Select font folder", self._saved_dir(INPUT_DIR_KEY) or str(Path.home())
        )
        if selected:
            self.store.set_dir(INPUT_DIR_KEY, selected)
            self._add_paths([selected], recursive)

    def _add_paths(self, paths: list[str], recursive: bool = False) -> None:
        changed = False
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_dir() and not path.is_file():
                continue
            path = path.resolve()
            recurse = recursive and path.is_dir()
            index = next((i for i, s in enumerate(self._sources) if s.path == path), None)
            if index is None:
                self._sources.append(Source(path, recurse))
            elif recurse and not self._sources[index].recursive:
                self._sources[index] = Source(path, True)
            else:
                continue
            changed = True
        if changed:
            self._refresh_folder_contents()

    def _refresh_folder_contents(self) -> None:
        self._remember_input_checks()
        self._stop_scan()
        self.files.setSortingEnabled(False)
        self.file_list.clear()
        self.instance_tree.clear_fonts()
        self._update_body_layout()
        self._scan_cancelled = False
        self._scan_counts = (0, 0)
        self.scan_progress.setVisible(False)
        if not self._sources:
            self.files.setSortingEnabled(True)
            self._update_buttons()
            return
        self.scan_progress.setRange(0, 1)
        self.scan_progress.setValue(0)
        self.scan_label.setText("Counting fonts…")
        self.scan_widget.setVisible(True)
        self.scan_stop_button.setEnabled(True)
        self.file_list.start(list(self._sources))
        self._update_buttons()

    def _stop_scan(self) -> None:
        self.file_list.stop()

    def _cancel_scan(self) -> None:
        if not self.file_list.scanning:
            return
        self._scan_cancelled = True
        self.scan_stop_button.setEnabled(False)
        self.file_list.cancel()

    def _on_scan_progress(self, done: int, total: int) -> None:
        self._scan_counts = (done, total)
        if total == 0:
            # The busy animation is not reliable with the styled bar: text only until known.
            self.scan_progress.setVisible(False)
            self.scan_label.setText("Counting fonts…")
            return
        self.scan_progress.setVisible(True)
        self.scan_progress.setRange(0, total)
        self.scan_progress.setValue(done)
        self.scan_label.setText(f"Scanning fonts… {done} / {total}")

    def _is_instance_mode(self) -> bool:
        return self.conversion.currentData() == "var2static"

    def _on_font_found(self, path: Path, info: FontInfo) -> None:
        source = next(
            (s.path for s in self._sources if s.path.is_dir() and path.is_relative_to(s.path)),
            None,
        )
        label = path.name if source is None else path.relative_to(source).as_posix()
        checked = self._input_check_states.setdefault(path, True)
        was_blocked = self.files.blockSignals(True)
        self.file_list.add_font(path, label, info, checked)
        self.files.blockSignals(was_blocked)
        if info.variable and not info.collection:
            self.instance_tree.add_font(path, label, info, checked_by_default=checked)
        else:
            reason = incompatibility(info, "var2static") or "Not a variable font"
            self.instance_tree.add_skipped(path, label, reason, info)
        if self.file_list.row_count == 1:
            self._update_buttons()

    def _on_scan_failed(self, message: str) -> None:
        self.scan_progress.setVisible(False)
        self._set_status(f"Scan failed: {message}", "error")
        self._append_log(LogEntry.create("ERROR", "scan.failed", f"Scan failed: {message}", {}))

    def _on_scan_finished(self) -> None:
        self.scan_progress.setVisible(False)
        self.files.setSortingEnabled(True)
        header = self.files.horizontalHeader()
        self.files.sortByColumn(header.sortIndicatorSection(), header.sortIndicatorOrder())
        self.instance_tree.auto_expand()
        self._update_body_layout()
        self._update_buttons()

    def _apply_compatibility(self, *_: object) -> None:
        self.file_list.apply_compatibility()
        self.instance_tree.set_hide_incompatible(self.hide_incompatible.isChecked())

    def _selected_input_paths(self) -> list[Path]:
        if self._is_instance_mode():
            return self.instance_tree.selected_paths()
        return self.file_list.selected_paths()

    def _remember_input_checks(self) -> None:
        self._input_check_states.update(self.file_list.remember_checks())

    def _on_file_item_changed(self, *_: object) -> None:
        for row in self.file_list.rows():
            if (
                row.path in self._input_check_states
                and self._input_check_states[row.path] != row.checked
            ):
                self.instance_tree.set_font_checked(row.path, row.checked)
        self._remember_input_checks()
        self._update_buttons()

    def _set_visible_checks(self, checked: bool) -> None:
        if self._is_instance_mode():
            self.instance_tree.set_all_checked(checked)
            return
        self.file_list.set_visible_checks(checked)
        self._remember_input_checks()
        self._update_buttons()

    def _toggle_visible_checks(self) -> None:
        checked = self.select_all_checkbox.checkState() != Qt.CheckState.Unchecked
        self._set_visible_checks(checked)

    def _clear_files(self) -> None:
        self._sources.clear()
        self._input_check_states.clear()
        self.instance_tree.forget()
        self._refresh_folder_contents()
        # "Clear list" hides itself: park focus instead of ringing the next control.
        self._park_focus()

    def _choose_destination(self) -> None:
        start = str(self.output_directory or self._saved_dir(OUTPUT_DIR_KEY) or Path.home())
        selected = QFileDialog.getExistingDirectory(self, "Choose output folder", start)
        if selected:
            self.store.set_dir(OUTPUT_DIR_KEY, selected)
            self.output_directory = Path(selected)
            self.destination_edit.setText(selected)
            self._update_buttons()
        elif self.output_directory is None:
            self.destination_source_radio.setChecked(True)

    def _on_destination_mode_changed(self, source_selected: bool) -> None:
        if source_selected:
            self.output_directory = None
            self.destination_edit.clear()
            self.destination_edit.setPlaceholderText("")
        else:
            self.destination_edit.setPlaceholderText("Choose an output folder…")
            saved_directory = self._saved_dir(OUTPUT_DIR_KEY)
            if saved_directory:
                self.destination_edit.setText(saved_directory)
                self.output_directory = Path(saved_directory)
            else:
                self.output_directory = None
                self._choose_destination()
        self._update_buttons()

    def _web_format_valid(self) -> bool:
        conversion = self.conversion.currentData()
        if conversion != "ft2wf":
            return True
        return self.profile_options.web_format_valid()

    def _update_buttons(self) -> None:
        instance_mode = self._is_instance_mode()
        has_rows = self.file_list.row_count > 0
        self.drop_zone.set_scanning(self.file_list.scanning)
        if has_rows != getattr(self, "_controls_docked", None):
            self._controls_docked = has_rows
            place_drop_zone(self, has_rows)
            self._configure_tab_order()
        self.files_stack.setVisible(has_rows)
        if has_rows:
            self.files_stack.setCurrentWidget(self.instance_tree if instance_mode else self.files)
        self.clear_button.setVisible(has_rows)
        self.select_all_checkbox.setVisible(has_rows)
        self.hide_incompatible.setVisible(has_rows)
        self.font_filter.setVisible(has_rows)
        if instance_mode:
            self.font_filter.setPlaceholderText("Filter fonts or instances…")
            self.font_filter.setToolTip(
                "Show fonts and instances whose names, locations, or paths match."
            )
        else:
            self.font_filter.setPlaceholderText(FONT_FILTER_PLACEHOLDER)
            self.font_filter.setToolTip(
                "Filter fonts by name, family, style, format, outlines, or UPM."
            )
        has_fonts = self.instance_tree.font_count() > 0
        self.expand_instances_button.setVisible(instance_mode and has_fonts)
        self.collapse_instances_button.setVisible(instance_mode and has_fonts)
        self.font_filter.setEnabled(
            self.instance_tree.font_count() > 0 if instance_mode else self.file_list.row_count > 0
        )
        self.profile_options.set_instance_outlines(
            self.instance_tree.selected_outlines() if instance_mode else set()
        )
        self.select_all_checkbox.setToolTip(
            "Select or clear all visible instances."
            if instance_mode
            else "Select or clear all visible compatible fonts."
        )
        # Recompute the body layout only when control visibility actually changed;
        # this method is called on every model/filter update.
        signature = (has_rows, instance_mode, has_fonts)
        if signature != self._layout_signature:
            self._layout_signature = signature
            self._update_body_layout()
        has_roots = bool(self._sources)
        selected = (
            self.instance_tree.instance_count()
            if instance_mode
            else len(self.file_list.selected_paths())
        )
        has_files = selected > 0
        has_logs = self.log.count() > 0
        scanning = self.file_list.scanning
        folder_mode = self.destination_folder_radio.isChecked()
        conversion = self.conversion.currentData()
        unit = "instance" if instance_mode else "font"
        if selected != 1:
            unit += "s"
        compatible_fonts = (
            self.instance_tree.font_count() if instance_mode else self.file_list.compatible_count()
        )
        has_profile = conversion is not None
        ready = has_profile and has_files and not scanning and self._web_format_valid()
        busy_worker = self.worker is not None
        running = busy_worker and (
            self._last_status is None
            or self._last_status[0] in (StatusState.RUNNING, StatusState.PAUSED)
        )
        paused = running and self._run_state is RunState.PAUSED
        # During a run Convert keeps its label (disabled); the footer card shows progress.
        self.convert_button.setText(
            f"Convert {selected} {unit}" if has_profile and has_files else "Convert"
        )
        self.convert_button.setIcon(self._convert_icon if has_profile and has_files else QIcon())
        self.convert_button.setEnabled(
            ready and not busy_worker and not self.conversion_dialog.isVisible()
        )
        footer_reason = None
        if self.worker is None:
            if not has_profile:
                footer_reason = (
                    "Choose a conversion to start" if has_rows else "Add fonts to start converting"
                )
            elif not has_rows:
                footer_reason = "Add fonts to start converting"
            elif compatible_fonts == 0:
                footer_reason = "No compatible fonts for this conversion"
        badge_states = (
            "" if not has_rows else ("valid" if compatible_fonts else "invalid"),
            "valid" if has_profile else "",
        )
        for index, (badge, state) in enumerate(
            zip(self._step_badges[:2], badge_states, strict=True), 1
        ):
            badge.set_done(state == "valid")
            badge.setProperty("state", state or "muted")
            done = {"valid": "complete", "invalid": "incomplete"}.get(state, "pending")
            badge.setAccessibleName(f"Step {index} {done}")
            badge.style().unpolish(badge)
            badge.style().polish(badge)
        for badge in self._step_badges[2:]:
            badge.set_done(False)
            badge.setProperty("state", "")
        for badge in self._step_badges[2:]:
            badge.style().unpolish(badge)
            badge.style().polish(badge)
        if self.overwrite_panel.property("active") != self.overwrite.isChecked():
            self.overwrite_panel.setProperty("active", self.overwrite.isChecked())
            # Descendant selectors ([active="true"] QCheckBox / QLabel) only apply once the
            # children are re-polished too, not just the panel.
            for widget in (self.overwrite_panel, *self.overwrite_panel.findChildren(QWidget)):
                widget.style().unpolish(widget)
                widget.style().polish(widget)
                widget.update()
        self.profile_options.set_state("empty" if not has_profile else "")
        self.hide_incompatible.setEnabled(has_profile)
        self.organization_example.setVisible(has_profile and bool(self.organization_levels))
        options_modified = conversion is not None and (
            self.profile_options.snapshot() != FACTORY_DEFAULTS
        )
        options_chip = self.profile_options.findChild(QLabel, "modifiedChip")
        if options_chip is None:
            raise RuntimeError("The options card must include its modified chip.")
        options_chip.setVisible(options_modified)
        self.profile_options.reset_button.setEnabled(options_modified)
        self.conversion_dialog.set_running(self.worker is not None)
        self.last_run_button.setEnabled(has_logs)
        self.pause_button.setText("Resume" if self._run_state is RunState.PAUSED else "Pause")
        self.pause_button.setEnabled(
            self._run_state in (RunState.RUNNING, RunState.PAUSED) and not self._cancelling
        )
        self.clear_button.setEnabled(has_roots)
        check_state = (
            self.instance_tree.check_state()
            if instance_mode
            else self.file_list.visible_check_state()
        )
        self.select_all_checkbox.setEnabled(check_state is not None and not scanning)
        self.select_all_checkbox.setCheckState(
            Qt.CheckState.Unchecked if check_state is None else check_state
        )
        self.destination_edit.setEnabled(folder_mode)
        self.destination_button.setEnabled(folder_mode)
        if footer_reason is not None:
            summary = footer_reason
        elif not has_files:
            summary = "Select compatible fonts or instances to continue."
        elif not self._web_format_valid():
            summary = "Choose at least one web font format to continue."
        else:
            summary = f"{CONVERSIONS[str(conversion)]} · {selected} {unit} selected"
        self.summary.setText(summary)
        self.summary.setProperty("reason", footer_reason is not None)
        self.summary.style().unpolish(self.summary)
        self.summary.style().polish(self.summary)
        # Only what the footer does not already say: the shortcut, or why the button waits.
        self.convert_button.setToolTip(
            "Waiting for the scan to finish"
            if scanning
            else ""
            if not ready or paused or running
            else "Close the conversion dialog before starting another run."
            if self.conversion_dialog.isVisible()
            else "Start conversion (Ctrl+Enter)."
        )
        self.save_logs_button.setEnabled(has_logs and self.worker is None)
        self.scan_stop_button.setVisible(scanning)
        # The count row only exists with a list or a scan: when empty, the drop zone
        # takes its room and ends one card padding above the bottom edge.
        self.scan_widget.setVisible(scanning or has_rows)
        sync_drop_zone_height(self)
        if scanning:
            self.scan_label.setFixedWidth(scan_label_width(self.scan_label))
        else:
            self.scan_label.setMinimumWidth(0)
            self.scan_label.setMaximumWidth(16777215)
            self.scan_progress.setVisible(False)
        if not scanning:
            count = self.file_list.row_count
            if instance_mode:
                shown, hidden = self.instance_tree.list_status_counts()
            else:
                shown = self.file_list.proxy.rowCount()
                hidden = self.file_list.proxy.hidden_incompatible_count()
            text = list_status_text(count, shown, hidden, filtered=bool(self.font_filter.text()))
            if instance_mode and count:
                fonts = self.instance_tree.font_count()
                instances = self.instance_tree.instance_count()
                text += (
                    " · "
                    f"{fonts} variable font{'' if fonts == 1 else 's'} · "
                    f"{instances} instance{'' if instances == 1 else 's'} selected"
                )
                skipped = self.instance_tree.skipped_count()
                if skipped:
                    text += f" · {skipped} skipped"
            if not instance_mode:
                selected_rows = self.files.selectionModel().selectedRows()
                if len(selected_rows) == 1:
                    reason = selected_rows[0].data(Qt.ItemDataRole.UserRole + 1)
                    if reason:
                        text += f" · {reason}"
            self.scan_label.setText(text)

    def _append_log(self, entry: LogEntry) -> None:
        self._log_entries.append(entry)
        self.log.append_entry(entry)
        # Only the log-driven controls change here; the rest is updated at lifecycle points.
        self.save_logs_button.setEnabled(self.worker is None)
        self.last_run_button.setEnabled(True)

    def _show_conversion_dialog(self) -> None:
        self.conversion_dialog.open()
        if self._last_status is not None and not self.status_pill.isHidden():
            self._render_run_status(*self._last_status)
        self._update_buttons()

    def _set_output_available(self, available: bool) -> None:
        self.open_output_button.setEnabled(available)
        self.conversion_dialog.open_output_button.setEnabled(available)

    def _set_status(self, text: str, state: str = "", *, terminal: bool = False) -> None:
        if state == "error" and self.conversion_dialog.isVisible():
            QMessageBox.warning(self.conversion_dialog, "Error", text)
        self.status_pill.set_state(
            StatusState.NOTICE,
            done=0,
            total=0,
            elapsed=0,
            dialog_open=False,
            detail=text,
            notice_tone=state,
        )
        self.status_zone.setCurrentWidget(self.status_pill)

    def _set_run_status(self, state: StatusState, *, detail: str = "") -> None:
        self._last_status = (state, detail)
        self._render_run_status(state, detail)
        if state not in (StatusState.RUNNING, StatusState.PAUSED):
            self._update_buttons()

    def _render_run_status(self, state: StatusState, detail: str) -> None:
        outcome = self.converter.outcome
        done = (
            self.converter.progress_done
            if state in (StatusState.RUNNING, StatusState.PAUSED)
            else outcome.converted
        )
        self.status_pill.set_state(
            state,
            done=done,
            total=outcome.total,
            elapsed=outcome.elapsed,
            skipped=outcome.skipped,
            failed=outcome.failed,
            converted=outcome.converted,
            dialog_open=self.conversion_dialog.isVisible(),
            detail=detail,
        )
        self.conversion_dialog.set_run_status(
            state,
            self.status_pill.label.text(),
            detail,
            converted=outcome.converted,
            total=outcome.total,
            failed_files=outcome.failed_files,
        )
        self.status_zone.setCurrentWidget(self.status_pill)

    def _dismiss_status(self) -> None:
        if self.status_pill.state is StatusState.NOTICE and self._last_status is not None:
            self._render_run_status(*self._last_status)
            return
        self._last_status = None
        self.status_pill.state = None
        self._show_summary()

    def _sync_footer_tone(self) -> None:
        """Footer card colors: the status tone, or idle (white) while the summary shows."""
        tone = self.status_pill.tone if self.status_zone.currentWidget() is self.status_pill else ""
        if self.footer_card.property("tone") != tone:
            self.footer_card.setProperty("tone", tone)
            self.footer_card.style().unpolish(self.footer_card)
            self.footer_card.style().polish(self.footer_card)
            self.footer_card.update()

    def _show_summary(self) -> None:
        self.history_button.setVisible(self._last_run_available)
        self.history_button.setEnabled(self._last_run_available)
        self.status_zone.setCurrentWidget(self.summary_zone)

    def _dialog_finished(self) -> None:
        if self._last_status is not None and self.status_pill.state is not StatusState.NOTICE:
            self._render_run_status(*self._last_status)
        self._update_buttons()

    def _save_logs(self) -> None:
        if not self._log_entries:
            self._set_status("No logs available to save.", "warning")
            return
        start = str(Path(self._saved_dir(LOG_DIR_KEY) or Path.home()) / "font-converter.jsonl")
        selected, _ = QFileDialog.getSaveFileName(
            self, "Save logs", start, "JSON Lines logs (*.jsonl);;All files (*)"
        )
        if not selected:
            return
        text = "\n".join(entry.to_json() for entry in self._log_entries)
        try:
            Path(selected).write_text(text + "\n", encoding="utf-8")
        except OSError as error:
            self._set_status(f"Could not save logs: {error}", "error")
            return
        self.store.set_dir(LOG_DIR_KEY, str(Path(selected).parent))
        self._set_status(f"Logs saved to {selected}.")

    def _options(self) -> ConversionSettings:
        conversion = self.conversion.currentData()
        if conversion is None:
            raise ValueError("Choose a conversion profile first.")
        common = ConversionOptions(
            output_dir=self.output_directory,
            overwrite=self.overwrite.isChecked(),
            recalc_bboxes=self.recalc_bboxes.isChecked(),
            recalc_timestamp=self.recalc_timestamp.isChecked(),
            reorder_tables=self.reorder_tables.isChecked(),
            organization_levels=self.organization_levels,
        )
        return self.profile_options.settings_for(
            conversion, common, self.instance_tree.selection() if conversion == "var2static" else ()
        )

    def _compatibility_profile(self) -> tuple[str | None, bool]:
        return (
            self.conversion.currentData(),
            self.hide_incompatible.isChecked(),
        )

    def _confirm_modify_rights(self) -> bool:
        if self.store.get_bool(MODIFY_RIGHTS_KEY):
            return True

        dialog = QMessageBox(self)
        dialog.setWindowTitle("Confirm font modification rights")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(
            "Before converting, confirm that you have the legal right to modify these fonts."
        )
        dialog.setInformativeText(
            "If you are not the intellectual property owner of these fonts, please ensure you "
            "have obtained permission to modify them.\n\n"
            "The developers of Fontvertx are not responsible for users' violations of font EULAs "
            "or other applicable license terms."
        )
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Yes).setText("I have permission")
        remember = QCheckBox("Remember this choice")
        dialog.setCheckBox(remember)
        if dialog.exec() != QMessageBox.StandardButton.Yes:
            return False
        if remember.isChecked():
            self.store.set_bool(MODIFY_RIGHTS_KEY, True)
        return True

    def _start_conversion(self) -> None:
        if self.conversion.currentData() is None:
            return
        input_paths = self._selected_input_paths()
        if not input_paths:
            return
        if any(not path.exists() for path in input_paths):
            QMessageBox.critical(
                self, "Input unavailable", "One or more selected inputs no longer exist."
            )
            return
        if not self._confirm_modify_rights():
            return

        total = (
            self.instance_tree.instance_count() if self._is_instance_mode() else len(input_paths)
        )
        self.converter.start(ConversionRequest(tuple(input_paths), self._options()), total)

    def _conversion_elapsed(self) -> float:
        return self.converter.elapsed()

    def _finish_conversion_timer(self) -> None:
        self.converter.finish_timer()

    def _refresh_progress_status(self) -> None:
        self.converter.refresh_progress_status()

    def _on_conversion_progress(self, done: int, total: int) -> None:
        self.converter.on_progress(done, total)

    def _output_folder_to_open(self) -> Path | None:
        return self.converter.output_folder_to_open()

    def _toggle_pause(self) -> None:
        self.converter.toggle_pause()

    def _on_paused_changed(self, paused: bool) -> None:
        self.converter.on_paused_changed(paused)

    def _cancel_conversion(self) -> None:
        self.converter.cancel()

    def _request_cancel(self) -> None:
        self.converter.request_cancel()

    def _conversion_finished(self, result: ConversionResult) -> None:
        self.converter.finished(result)

    @staticmethod
    def _status_summary(result: ConversionResult) -> str:
        return ConversionController.status_summary(result)

    @staticmethod
    def _batch_summary(result: ConversionResult) -> str:
        return ConversionController.batch_summary(result)

    def _show_error(
        self,
        message: str,
        log_event: str | None = "application.error",
        log_context: dict[str, object] | None = None,
        *,
        terminal: bool = False,
    ) -> None:
        self.converter.show_error(message, log_event, log_context, terminal=terminal)

    def _conversion_failed(self, message: str) -> None:
        self.converter.failed(message)

    def _worker_stopped(self) -> None:
        self.converter.worker_stopped()

    def _open_output_folder(self) -> None:
        self.converter.open_output_folder()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker is not None and self.worker.isRunning():
            if self._run_state is RunState.PAUSED and not self._cancelling:
                box = QMessageBox(self)
                box.setWindowTitle("Conversion paused")
                box.setText("The conversion is paused. What do you want to do?")
                resume = box.addButton("Resume", QMessageBox.ButtonRole.AcceptRole)
                cancel = box.addButton("Cancel conversion", QMessageBox.ButtonRole.DestructiveRole)
                box.addButton("Keep window open", QMessageBox.ButtonRole.RejectRole)
                box.exec()
                clicked = box.clickedButton()
                if clicked is cancel:
                    self._close_when_finished = True
                    self._request_cancel()
                elif clicked is resume:
                    self._toggle_pause()
                event.ignore()
                return
            if self._cancelling:
                self._close_when_finished = True
                event.ignore()
                return
            answer = QMessageBox.question(
                self,
                "Conversion in progress",
                "Wait for the current conversion to finish before closing?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._close_when_finished = True
                self._set_status("The window will close when conversion finishes.", "warning")
                event.ignore()
                return
            # Last resort for a stuck worker (e.g. fontTools hung on a corrupt font):
            # offer to terminate the thread, warning about partial output files.
            force = QMessageBox.question(
                self,
                "Force close",
                "Stop the conversion immediately and close?\n\n"
                "The font being converted may be left corrupted on disk.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if force != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.converter.force_stop()
        self._save_active_profile_preferences()
        self.store.set_geometry(self.saveGeometry())
        self._stop_scan()
        self.file_list.shutdown()
        event.accept()
