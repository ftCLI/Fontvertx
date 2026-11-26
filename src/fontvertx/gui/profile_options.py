"""Profile-specific controls and typed option construction for the converter."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPaintEvent, QPixmap, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from fontvertx.gui.icons import material_icon
from fontvertx.gui.layout_manager import CARD_PADDING
from fontvertx.gui.styles import FIELD_HEIGHT, colors
from fontvertx.gui.tooltips import wrap_tip
from fontvertx.gui.widgets import (
    UPM_STEP_VALUES,
    DecimalSpinBox,
    KeyboardPushButton,
    StepperField,
    UpmSpinBox,
    card_heading,
    centered_icon_pixels,
)
from fontvertx.models import (
    ConversionOptions,
    ConversionSettings,
    InstanceSpec,
    OtfToTtfOptions,
    SfntToWebOptions,
    TtcToSfntOptions,
    TtfToOtfOptions,
    VarToStaticOptions,
    WebFormat,
    Woff2ToSfntOptions,
    WoffToSfntOptions,
)

# Factory values of the persisted widgets; user-configurable defaults override them
# for profiles that have not been customized yet.
FACTORY_DEFAULTS: dict[str, bool | int | float] = {
    "tolerance": 1.0,
    "simplify": 0,
    "use_target_upm": False,
    "target_upm": 1000,
    "subroutinize": True,
    "autohint": True,
    "format_woff": True,
    "format_woff2": True,
    "obfuscate_names": False,
    "remove_unused_glyphs": False,
    "remove_non_windows_names": False,
    "remove_dsig": False,
    "css_kit": False,
    "recalc_bboxes": True,
    "recalc_timestamp": False,
    "reorder_tables": True,
}


EMPTY_ICON_CIRCLE = 40
EMPTY_ICON_GLYPH = 20
EMPTY_TITLE = "No options yet"
EMPTY_BODY = "Choose a conversion above and its settings will show up here."
EMPTY_BODY_MAX_WIDTH = 240
EMPTY_BODY_LINE_HEIGHT = 17  # 12px text at 1.45
EMPTY_ICON_TITLE_GAP = 12
EMPTY_TITLE_BODY_GAP = 8  # clearly more than the gap between the body's lines


class _EmptyStateIcon(QWidget):
    """The "tune" glyph on a 40px accent-tint circle, painted at the screen's scale."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(EMPTY_ICON_CIRCLE, EMPTY_ICON_CIRCLE)
        self._icon = material_icon("tune", "accent_text", EMPTY_ICON_GLYPH)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors().accent_tint))
        painter.drawEllipse(QRectF(self.rect()))
        ratio = painter.device().devicePixelRatioF()
        glyph_px, offset_px = centered_icon_pixels(self.width(), EMPTY_ICON_GLYPH, ratio)
        pixmap = QPixmap(self._icon.pixmap(QSize(glyph_px, glyph_px), 1.0))
        pixmap.setDevicePixelRatio(ratio)
        painter.drawPixmap(QPointF(offset_px / ratio, offset_px / ratio), pixmap)


class OptionsEmptyState(QWidget):
    """Shown in the options card while no conversion is chosen."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("optionsEmptyState")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(0)
        self.icon = _EmptyStateIcon()
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(EMPTY_ICON_TITLE_GAP)
        self.title = QLabel(EMPTY_TITLE)
        self.title.setObjectName("optionsEmptyTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.title)
        layout.addSpacing(EMPTY_TITLE_BODY_GAP)
        self.body = QLabel()
        self.body.setObjectName("optionsEmptyBody")
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setWordWrap(True)
        self.body.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.body.setFixedWidth(EMPTY_BODY_MAX_WIDTH)
        self.body.setAccessibleName(EMPTY_BODY)
        layout.addWidget(self.body, 0, Qt.AlignmentFlag.AlignHCenter)
        self._reserve_body_height()

    def _reserve_body_height(self) -> None:
        self.body.ensurePolished()
        # Qt's rich-text line-height percentage is of the font's line spacing (15px for
        # Inter 12px), not of its size: derive the one that gives EMPTY_BODY_LINE_HEIGHT.
        spacing = QFontMetricsF(self.body.font()).lineSpacing()
        percent = round(100 * EMPTY_BODY_LINE_HEIGHT / spacing)
        self.body.setText(f'<p style="line-height: {percent}%; margin: 0">{EMPTY_BODY}</p>')
        # The card has a fixed vertical policy, so the wrapped body reserves its height.
        self.body.setMinimumHeight(self.body.heightForWidth(EMPTY_BODY_MAX_WIDTH))

    def showEvent(self, event: QShowEvent) -> None:
        self._reserve_body_height()
        super().showEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._reserve_body_height()
        super().changeEvent(event)


class ProfileOptionsPanel(QGroupBox):
    """Own controls that change with a selected conversion profile."""

    compatibilityChanged = Signal()
    validityChanged = Signal()

    # Widgets whose values are persisted per profile (checkbox → bool, spinbox → number).
    _PERSISTED_WIDGETS = (
        "tolerance",
        "simplify",
        "use_target_upm",
        "target_upm",
        "subroutinize",
        "autohint",
        "format_woff",
        "format_woff2",
        "obfuscate_names",
        "remove_unused_glyphs",
        "remove_non_windows_names",
        "remove_dsig",
        "css_kit",
        "recalc_bboxes",
        "recalc_timestamp",
        "reorder_tables",
    )

    def __init__(self, step_number: int | None = 3) -> None:
        super().__init__()
        self.setObjectName("card")
        self._outline_profile = False
        self._variable_profile = False
        self._web_profile = False
        self._instance_outlines: set[str] = set()
        options = QVBoxLayout(self)
        options.setContentsMargins(CARD_PADDING, CARD_PADDING, CARD_PADDING, CARD_PADDING)
        options.setSpacing(3)
        heading_row = QHBoxLayout()
        heading_row.setContentsMargins(0, 0, 0, 0)
        # No built-in bottom margin: the heading's visual center must coincide with the
        # reset button's, which is centered on the row (spacing is added below instead).
        heading = card_heading("Set options", step_number, bottom_margin=0, modified_chip=True)
        heading_row.addWidget(heading, 1, Qt.AlignmentFlag.AlignVCenter)
        self.reset_button = KeyboardPushButton("Reset")
        self.reset_button.setObjectName("ghostButton")
        self.reset_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.reset_button.setEnabled(False)
        self.reset_button.setToolTip("Restore this profile's options to the factory defaults.")
        self.reset_button.setAccessibleName("Restore default options")
        heading_row.addWidget(self.reset_button, 0, Qt.AlignmentFlag.AlignVCenter)
        options.addLayout(heading_row)
        options.addSpacing(6)

        self.tolerance_label = QLabel("Tolerance (0.0–3.0)")
        self.tolerance = DecimalSpinBox()
        self.tolerance.setRange(0, 3)
        self.tolerance.setSingleStep(0.1)
        self.tolerance.setValue(float(FACTORY_DEFAULTS["tolerance"]))
        self.tolerance.setDecimals(2)
        self.tolerance_field = StepperField(self.tolerance, tab_buttons=True)
        self.tolerance_field.setFixedWidth(170)
        tolerance_tooltip = (
            "Higher values allow larger curve deviations and usually produce fewer points; "
            "lower values preserve more detail. "
            "Tolerance is in thousandths of an em; actual deviation scales with UPM."
        )
        # One tooltip per row, on its label, so hovering the stepper stays quiet.
        self.tolerance_label.setToolTip(wrap_tip(tolerance_tooltip))
        self.use_target_upm = QCheckBox("Set target UPM")
        upm_tooltip = "UPM (units per em) is the font's design-grid size. Scale converted fonts to this value."
        self.use_target_upm.setToolTip(wrap_tip(upm_tooltip))
        self.target_upm = UpmSpinBox()
        self.target_upm_field = StepperField(self.target_upm, tab_buttons=True)
        self.target_upm_field.setFixedWidth(170)
        self.use_target_upm.toggled.connect(self._sync_target_upm_field)
        self.tolerance.setProperty("mono", "true")
        self.target_upm.setProperty("mono", "true")
        self._sync_target_upm_field(False)

        self.subroutinize = QCheckBox("Subroutinize")
        self.subroutinize.setChecked(bool(FACTORY_DEFAULTS["subroutinize"]))
        self.subroutinize.setToolTip(
            wrap_tip("Compress CFF outlines using shared subroutines (PostScript outlines only).")
        )
        self.simplify_label = QLabel("Simplify (0–3)")
        self.simplify_label.setWordWrap(True)
        self.simplify = QSpinBox()
        self.simplify.setRange(0, 3)
        self.simplify.setSpecialValueText("Off")
        self.simplify_label.setToolTip(
            wrap_tip(
                "Merge adjacent smooth curve segments to reduce the number of points "
                "(experimental). Higher values allow larger deviations; 0 disables simplification."
            )
        )
        self.simplify.setProperty("mono", "true")
        self.simplify_field = StepperField(self.simplify, tab_buttons=True)
        self.simplify_field.setFixedWidth(170)
        for field in (self.tolerance_field, self.simplify_field, self.target_upm_field):
            for control in (field.spin_box, field.decrement_button, field.increment_button):
                control.setProperty("compactStepper", True)
                control.setFixedHeight(FIELD_HEIGHT)
        self.autohint = QCheckBox("Autohint")
        self.autohint.setChecked(bool(FACTORY_DEFAULTS["autohint"]))
        self.autohint.setToolTip(
            wrap_tip("Add TrueType hinting instructions with ttfautohint (TrueType outlines only).")
        )

        spin_grid = QGridLayout()
        spin_grid.setHorizontalSpacing(12)
        spin_grid.setVerticalSpacing(6)
        # Left-aligned, so each label and checkbox (and its tooltip) is only as wide as
        # its text, not as the widest one in the column.
        spin_grid.addWidget(self.tolerance_label, 0, 0, Qt.AlignmentFlag.AlignLeft)
        spin_grid.addWidget(self.tolerance_field, 0, 1)
        spin_grid.addWidget(self.simplify_label, 1, 0, Qt.AlignmentFlag.AlignLeft)
        spin_grid.addWidget(self.simplify_field, 1, 1)
        spin_grid.addWidget(self.use_target_upm, 2, 0, Qt.AlignmentFlag.AlignLeft)
        spin_grid.addWidget(self.target_upm_field, 2, 1)
        spin_grid.setColumnStretch(2, 1)
        options.addLayout(spin_grid)

        self.upm_warning_label = QLabel()
        self.upm_warning_label.setTextFormat(Qt.TextFormat.RichText)
        self._render_upm_warning()
        self.upm_warning_label.setObjectName("upmWarning")
        self.upm_warning_label.setWordWrap(True)
        options.addWidget(self.upm_warning_label)
        self.use_target_upm.toggled.connect(self._update_upm_warning)
        self.target_upm.valueChanged.connect(self._update_upm_warning)
        # Checkboxes are left-aligned so they (and their tooltips) end with their text
        # instead of stretching across the card.
        options.addWidget(self.subroutinize, 0, Qt.AlignmentFlag.AlignLeft)
        options.addWidget(self.autohint, 0, Qt.AlignmentFlag.AlignLeft)

        self.format_label = QLabel("Output format:")
        self.format_woff = QCheckBox("WOFF")
        self.format_woff.setChecked(bool(FACTORY_DEFAULTS["format_woff"]))
        self.format_woff2 = QCheckBox("WOFF2")
        self.format_woff2.setChecked(bool(FACTORY_DEFAULTS["format_woff2"]))
        for checkbox in (self.format_woff, self.format_woff2):
            checkbox.toggled.connect(self.compatibilityChanged)
            checkbox.toggled.connect(self.validityChanged)
        self.obfuscate_names = QCheckBox("Obfuscate names")
        self.obfuscate_names.setToolTip(
            wrap_tip(
                "Replace the family, full and PostScript names with hashes, also in the file name."
            )
        )
        self.remove_unused_glyphs = QCheckBox("Remove unused glyphs")
        self.remove_unused_glyphs.setToolTip(
            wrap_tip(
                "Drop the glyphs not reachable from the character map or the OpenType features."
            )
        )
        self.remove_non_windows_names = QCheckBox("Remove non-Windows names")
        self.remove_non_windows_names.setToolTip(
            wrap_tip("Remove the name records whose platform ID is not 3 (e.g. Macintosh records).")
        )
        self.remove_dsig = QCheckBox("Remove DSIG table")
        self.remove_dsig.setToolTip(
            wrap_tip(
                "Remove the digital signature table from WOFF fonts. WOFF2 does not support it."
            )
        )
        self.format_woff.toggled.connect(self._update_dsig_visibility)
        self.css_kit = QCheckBox("Create CSS")
        self.css_kit.setToolTip(
            wrap_tip(
                "Write a fonts.css file with @font-face rules and a class for each OpenType feature."
            )
        )
        formats = QHBoxLayout()
        formats.setSpacing(16)
        formats.addWidget(self.format_label)
        formats.addWidget(self.format_woff)
        formats.addWidget(self.format_woff2)
        formats.addStretch()
        options.addLayout(formats)
        options.addWidget(self.obfuscate_names, 0, Qt.AlignmentFlag.AlignLeft)
        options.addWidget(self.remove_unused_glyphs, 0, Qt.AlignmentFlag.AlignLeft)
        options.addWidget(self.remove_non_windows_names, 0, Qt.AlignmentFlag.AlignLeft)
        options.addWidget(self.remove_dsig, 0, Qt.AlignmentFlag.AlignLeft)
        options.addWidget(self.css_kit, 0, Qt.AlignmentFlag.AlignLeft)

        self.no_profile_options = OptionsEmptyState()
        options.addWidget(self.no_profile_options)

        # Per-profile like the other options; the window exposes them as attributes too.
        self.recalc_bboxes = QCheckBox("Recalculate bounding boxes")
        self.recalc_bboxes.setChecked(bool(FACTORY_DEFAULTS["recalc_bboxes"]))
        self.recalc_bboxes.setToolTip("Rebuild glyph bounds before writing output files.")
        self.recalc_timestamp = QCheckBox("Recalculate modified timestamp")
        self.recalc_timestamp.setChecked(bool(FACTORY_DEFAULTS["recalc_timestamp"]))
        self.recalc_timestamp.setToolTip("Set a fresh font modification timestamp on save.")
        self.reorder_tables = QCheckBox("Reorder tables on save")
        self.reorder_tables.setChecked(bool(FACTORY_DEFAULTS["reorder_tables"]))
        self.reorder_tables.setToolTip("Use a standard table order for compatibility.")
        options.addWidget(self.recalc_bboxes, 0, Qt.AlignmentFlag.AlignLeft)
        options.addWidget(self.recalc_timestamp, 0, Qt.AlignmentFlag.AlignLeft)
        options.addWidget(self.reorder_tables, 0, Qt.AlignmentFlag.AlignLeft)
        self.set_conversion("ttf2otf")

    def set_conversion(self, conversion: str | None) -> None:
        self.setEnabled(conversion is not None)
        outline = conversion in ("ttf2otf", "otf2ttf")
        postscript = conversion == "ttf2otf"
        webfont = conversion == "ft2wf"
        self._web_profile = webfont
        variable = conversion == "var2static"
        self._outline_profile = outline

        # Qu2"uPen (TTF → OTF) rejects a tolerance of zero.
        self.tolerance.setMinimum(0.1 if postscript else 0.0)
        self.tolerance_label.setText("Tolerance (0.1–3.0)" if postscript else "Tolerance (0.0–3.0)")
        self.tolerance_label.setVisible(outline)
        self.tolerance_field.setVisible(outline)
        self.use_target_upm.setVisible(outline or variable)
        self.target_upm_field.setVisible(outline or variable)
        self._variable_profile = variable
        self._update_outline_options(conversion)
        self.format_label.setVisible(webfont)
        self.format_woff.setVisible(webfont)
        self.format_woff2.setVisible(webfont)
        self.obfuscate_names.setVisible(webfont)
        self.remove_unused_glyphs.setVisible(webfont)
        self.remove_non_windows_names.setVisible(webfont)
        self.css_kit.setVisible(webfont)
        self._update_dsig_visibility()
        self.no_profile_options.setVisible(conversion is None)
        for checkbox in (self.recalc_bboxes, self.recalc_timestamp, self.reorder_tables):
            checkbox.setVisible(conversion is not None)
        self.set_state("empty" if conversion is None else "")
        self._update_upm_warning()

    def set_state(self, state: str) -> None:
        """Emphasis of the card: "empty" (no profile) or normal."""
        if self.property("optionsState") != state:
            self.setProperty("optionsState", state)
            for widget in (self, *self.findChildren(QWidget)):
                widget.style().unpolish(widget)
                widget.style().polish(widget)

    def _sync_target_upm_field(self, enabled: bool) -> None:
        self.target_upm_field.setEnabled(enabled)
        # setEnabled() does not re-render the spin box text: refresh it manually.
        self.target_upm.lineEdit().setText(self.target_upm.textFromValue(self.target_upm.value()))

    def _update_dsig_visibility(self, *_: object) -> None:
        self.remove_dsig.setVisible(self._web_profile and self.format_woff.isChecked())

    def set_instance_outlines(self, outlines: set[str]) -> None:
        """Show only the options that apply to the outlines of the selected variable fonts."""
        if outlines != self._instance_outlines:
            self._instance_outlines = outlines
            if self._variable_profile:
                self._update_outline_options("var2static")

    def _update_outline_options(self, conversion: str | None) -> None:
        self.simplify_label.setVisible(conversion == "ttf2otf")
        self.simplify_field.setVisible(conversion == "ttf2otf")
        if conversion == "var2static":
            outlines = self._instance_outlines or {"TrueType", "PostScript"}
            self.subroutinize.setVisible("PostScript" in outlines)
            self.autohint.setVisible("TrueType" in outlines)
            self.subroutinize.setText("Subroutinize (PostScript only)")
            self.autohint.setText("Autohint (TrueType only)")
        else:
            self.subroutinize.setVisible(conversion == "ttf2otf")
            self.autohint.setVisible(conversion == "otf2ttf")
            self.subroutinize.setText("Subroutinize")
            self.autohint.setText("Autohint")

    def snapshot(self) -> dict[str, bool | int | float]:
        """Current values of the persisted widgets, for per-profile storage."""
        values: dict[str, bool | int | float] = {}
        for name in self._PERSISTED_WIDGETS:
            widget = getattr(self, name)
            values[name] = widget.isChecked() if isinstance(widget, QCheckBox) else widget.value()
        return values

    def restore(self, values: dict[str, object]) -> None:
        """Restore the persisted widgets: ``values`` win over the factory defaults."""
        merged: dict[str, object] = {**FACTORY_DEFAULTS, **values}
        for name in self._PERSISTED_WIDGETS:
            value = merged[name]
            widget = getattr(self, name)
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                widget.setValue(value)

    def connect_value_changes(self, slot: Callable[..., None]) -> None:
        """Connect ``slot`` to a signal emitted whenever a persisted value changes."""
        for name in self._PERSISTED_WIDGETS:
            widget = getattr(self, name)
            signal = widget.toggled if isinstance(widget, QCheckBox) else widget.valueChanged
            signal.connect(slot)

    def selected_web_format(self) -> WebFormat | None:
        woff, woff2 = self.format_woff.isChecked(), self.format_woff2.isChecked()
        if woff and not woff2:
            return "woff"
        if woff2 and not woff:
            return "woff2"
        return None

    def web_format_valid(self) -> bool:
        return self.format_woff.isChecked() or self.format_woff2.isChecked()

    def settings_for(
        self,
        conversion: str,
        common: ConversionOptions,
        instances: tuple[tuple[Path, tuple[InstanceSpec, ...]], ...] = (),
    ) -> ConversionSettings:
        if conversion == "ttf2otf":
            settings: ConversionSettings = TtfToOtfOptions(
                tolerance=self.tolerance.value(),
                target_upm=self.target_upm.value() if self.use_target_upm.isChecked() else None,
                subroutinize=self.subroutinize.isChecked(),
                simplify=self.simplify.value(),
            )
        elif conversion == "otf2ttf":
            settings = OtfToTtfOptions(
                tolerance=self.tolerance.value(),
                target_upm=self.target_upm.value() if self.use_target_upm.isChecked() else None,
                autohint=self.autohint.isChecked(),
            )
        elif conversion == "ft2wf":
            settings = SfntToWebOptions(
                format=self.selected_web_format(),
                obfuscate_names=self.obfuscate_names.isChecked(),
                remove_unused_glyphs=self.remove_unused_glyphs.isChecked(),
                remove_non_windows_names=self.remove_non_windows_names.isChecked(),
                css_kit=self.css_kit.isChecked(),
                remove_dsig=self.remove_dsig.isChecked() and self.format_woff.isChecked(),
            )
        elif conversion == "woff2ft":
            settings = WoffToSfntOptions()
        elif conversion == "woff22ft":
            settings = Woff2ToSfntOptions()
        elif conversion == "ttc2sfnt":
            settings = TtcToSfntOptions()
        elif conversion == "var2static":
            settings = VarToStaticOptions(
                instances=instances,
                target_upm=self.target_upm.value() if self.use_target_upm.isChecked() else None,
                autohint=self.autohint.isChecked(),
                subroutinize=self.subroutinize.isChecked(),
            )
        else:
            raise ValueError(f"Unsupported conversion profile: {conversion}")

        return replace(
            settings,
            recursive=common.recursive,
            output_dir=common.output_dir,
            overwrite=common.overwrite,
            recalc_bboxes=common.recalc_bboxes,
            recalc_timestamp=common.recalc_timestamp,
            reorder_tables=common.reorder_tables,
            organization_levels=common.organization_levels,
        )

    def _render_upm_warning(self) -> None:
        self.upm_warning_label.setText(
            f'<span style="color:{colors().warn_accent}">▲</span>&nbsp;Non-standard UPM.'
        )

    def refresh_theme(self) -> None:
        """Render the UPM warning again: its mark carries its color in the HTML."""
        self._render_upm_warning()

    def _update_upm_warning(self, *_: object) -> None:
        non_standard = (
            self.use_target_upm.isChecked() and self.target_upm.value() not in UPM_STEP_VALUES
        )
        self.upm_warning_label.setVisible(
            (self._outline_profile or self._variable_profile) and non_standard
        )
