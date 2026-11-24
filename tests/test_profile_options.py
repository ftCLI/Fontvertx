from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QGridLayout, QLabel, QWidget

from fontvertx.__main__ import _app_font
from fontvertx.gui.profile_options import ProfileOptionsPanel
from fontvertx.gui.styles import FIELD_HEIGHT, stylesheet
from fontvertx.models import (
    ConversionOptions,
    InstanceSpec,
    OtfToTtfOptions,
    SfntToWebOptions,
    TtcToSfntOptions,
    TtfToOtfOptions,
    VarToStaticOptions,
    Woff2ToSfntOptions,
    WoffToSfntOptions,
)


def test_option_rows_use_compact_consistent_pitch(qapp: QApplication) -> None:
    original_font = qapp.font()
    try:
        qapp.setFont(_app_font())
        panel = ProfileOptionsPanel()
        panel.setStyleSheet(stylesheet())
        panel.set_conversion("ft2wf")
        panel.show()
        qapp.processEvents()
        checks = (
            panel.format_woff,
            panel.obfuscate_names,
            panel.remove_unused_glyphs,
            panel.remove_non_windows_names,
            panel.remove_dsig,
            panel.css_kit,
            panel.recalc_bboxes,
            panel.recalc_timestamp,
            panel.reorder_tables,
        )
        assert all(b.y() - a.y() == 28 for a, b in zip(checks, checks[1:], strict=False))
        panel.set_conversion("ttf2otf")
        qapp.processEvents()
        panel.adjustSize()
        qapp.processEvents()
        fields = (panel.tolerance_field, panel.simplify_field, panel.target_upm_field)
        assert [field.y() for field in fields] == [
            fields[0].y(),
            fields[0].y() + FIELD_HEIGHT + 6,
            fields[0].y() + 2 * (FIELD_HEIGHT + 6),
        ]
        for field in fields:
            for control in (field.spin_box, field.decrement_button, field.increment_button):
                assert control.height() == FIELD_HEIGHT
        panel.close()
    finally:
        qapp.setFont(original_font)


def test_profile_switching_updates_visible_controls(qapp: QApplication) -> None:
    panel = ProfileOptionsPanel()

    assert panel.tolerance.minimum() == 0.1
    assert not panel.tolerance_field.isHidden()
    # One tooltip per option row, on its label or checkbox; the steppers stay quiet.
    # Long tooltips wrap (wrap_tip): compare the words.
    tolerance_tip = " ".join(panel.tolerance_label.toolTip().split())
    assert "fewer points" in tolerance_tip
    assert "thousandths of an em" in tolerance_tip
    assert "deviation scales with UPM" in tolerance_tip
    assert "units per em" in " ".join(panel.use_target_upm.toolTip().split())
    assert panel.simplify_label.text() == "Simplify (0–3)"
    assert not hasattr(panel, "instances_hint")
    assert "reduce the number of points" in " ".join(panel.simplify_label.toolTip().split())
    for field in (panel.tolerance_field, panel.target_upm_field, panel.simplify_field):
        for widget in (field, field.spin_box, field.decrement_button, field.increment_button):
            assert widget.toolTip() == ""
    assert panel.subroutinize.isVisibleTo(panel)

    panel.set_conversion("otf2ttf")
    assert panel.tolerance.minimum() == 0
    assert panel.autohint.isVisibleTo(panel)
    assert panel.subroutinize.isHidden()
    assert panel.format_label.isHidden()

    panel.set_conversion("ft2wf")
    assert panel.format_label.text() == "Output format:"
    assert not panel.format_woff.isHidden()
    assert panel.use_target_upm.isHidden()
    assert not panel.css_kit.isHidden()

    for conversion in ("woff2ft", "woff22ft"):
        panel.set_conversion(conversion)
        assert panel.format_label.isHidden()
        assert panel.css_kit.isHidden()
        assert panel.no_profile_options.isHidden()

    panel.set_conversion("var2static")
    assert not panel.use_target_upm.isHidden()
    assert panel.no_profile_options.isHidden()

    panel.set_conversion("ttc2sfnt")
    assert panel.no_profile_options.isHidden()


def test_variable_profile_has_no_gap_before_common_options(qapp: QApplication) -> None:
    """The removed instances hint leaves no spacing behind: same pitch as the rows below."""
    panel = ProfileOptionsPanel()
    panel.setStyleSheet(stylesheet())
    panel.show()
    for conversion in ("var2static", "ttf2otf", "otf2ttf"):
        panel.set_conversion(conversion)
        layout = panel.layout()
        assert layout is not None
        layout.activate()
        qapp.processEvents()
        above = max(
            (
                widget
                for widget in panel.findChildren(QWidget)
                if widget.parentWidget() is panel
                and widget.isVisible()
                and widget.geometry().bottom() < panel.recalc_bboxes.y()
            ),
            key=lambda widget: widget.geometry().bottom(),
        )
        gap = panel.recalc_bboxes.y() - above.geometry().bottom()
        pitch = panel.recalc_timestamp.y() - panel.recalc_bboxes.geometry().bottom()
        assert gap <= pitch, conversion
        labels = [label for label in panel.findChildren(QLabel) if label.isVisible()]
        assert not any("Check the instances" in label.text() for label in labels)


def test_unselected_profile_disables_visible_card(qapp: QApplication) -> None:
    panel = ProfileOptionsPanel()
    panel.show()
    panel.set_conversion(None)
    assert not panel.isHidden()
    assert not panel.isEnabled()
    assert not panel.no_profile_options.isHidden()
    assert panel.no_profile_options.title.text() == "No options yet"
    assert panel.no_profile_options.body.accessibleName() == (
        "Choose a conversion above and its settings will show up here."
    )
    assert panel.property("optionsState") == "empty"
    assert panel.recalc_bboxes.isHidden()

    panel.set_conversion("ttf2otf")
    assert panel.isEnabled()
    assert panel.tolerance.isEnabled()
    assert not panel.target_upm_field.isEnabled()
    assert panel.target_upm.text() == ""  # empty while disabled
    panel.use_target_upm.setChecked(True)
    assert panel.target_upm_field.isEnabled()
    assert panel.target_upm.text() == "1000"

    panel.set_conversion(None)
    assert not panel.isEnabled()
    panel.set_conversion("ttf2otf")
    assert panel.isEnabled()
    assert panel.target_upm_field.isEnabled()

    panel.set_conversion("woff2ft")
    assert panel.isEnabled()
    assert panel.no_profile_options.isHidden()


def test_target_upm_field_is_empty_while_disabled(qapp: QApplication) -> None:
    panel = ProfileOptionsPanel()
    panel.set_conversion("ttf2otf")

    panel.restore({"use_target_upm": True, "target_upm": 2048})
    assert panel.target_upm_field.isEnabled()
    assert panel.target_upm.text() == "2048"

    # Restoring an unchecked state keeps the stored value but shows an empty field.
    panel.restore({"use_target_upm": False, "target_upm": 2048})
    assert not panel.target_upm_field.isEnabled()
    assert panel.target_upm.text() == ""
    assert panel.target_upm.value() == 2048

    # Re-checking the box brings the stored value back.
    panel.use_target_upm.setChecked(True)
    assert panel.target_upm.text() == "2048"


def test_ttf2otf_simplify_follows_tolerance(qapp: QApplication) -> None:
    panel = ProfileOptionsPanel()
    # Item 0 is the heading row (title + reset button), item 1 the spacing below it.
    grid = panel.layout().itemAt(2).layout()
    assert isinstance(grid, QGridLayout)
    assert grid.itemAtPosition(0, 0).widget() is panel.tolerance_label
    assert grid.itemAtPosition(1, 0).widget() is panel.simplify_label
    assert grid.itemAtPosition(1, 1).widget() is panel.simplify_field
    assert grid.itemAtPosition(2, 0).widget() is panel.use_target_upm

    panel.set_conversion("otf2ttf")
    assert panel.simplify_label.isHidden()
    assert panel.simplify_field.isHidden()
    assert not panel.use_target_upm.isHidden()


def test_variable_profile_limits_outline_options_to_selected_fonts(qapp: QApplication) -> None:
    panel = ProfileOptionsPanel()
    panel.set_conversion("var2static")

    panel.set_instance_outlines({"TrueType"})
    assert panel.autohint.isVisibleTo(panel)
    assert panel.subroutinize.isHidden()

    panel.set_instance_outlines({"PostScript"})
    assert panel.autohint.isHidden()
    assert panel.subroutinize.isVisibleTo(panel)

    panel.set_instance_outlines({"TrueType", "PostScript"})
    assert panel.autohint.isVisibleTo(panel)
    assert panel.subroutinize.isVisibleTo(panel)
    assert panel.autohint.text() == "Autohint (TrueType only)"
    assert panel.subroutinize.text() == "Subroutinize (PostScript only)"


def test_web_format_selection_and_validity(qapp: QApplication) -> None:
    panel = ProfileOptionsPanel()

    assert panel.selected_web_format() is None
    assert panel.web_format_valid()

    panel.format_woff2.setChecked(False)
    assert panel.selected_web_format() == "woff"
    assert panel.web_format_valid()

    panel.format_woff.setChecked(False)
    assert panel.selected_web_format() is None
    assert not panel.web_format_valid()

    panel.format_woff2.setChecked(True)
    assert panel.selected_web_format() == "woff2"


def test_web_format_checkboxes_share_a_row_and_preserve_choices(qapp: QApplication) -> None:
    panel = ProfileOptionsPanel()
    panel.set_conversion("ft2wf")
    panel.resize(panel.minimumSizeHint().width(), panel.sizeHint().height())
    panel.show()
    qapp.processEvents()
    first, second = panel.format_woff, panel.format_woff2
    assert first.isVisible() and second.isVisible()
    assert panel.format_label.isVisible()
    assert panel.format_label.geometry().right() < first.geometry().left()
    assert abs(panel.format_label.geometry().center().y() - first.geometry().center().y()) <= 1
    assert panel.format_label.width() >= panel.format_label.sizeHint().width()
    assert first.y() == second.y()
    assert first.geometry().right() < second.geometry().left()
    assert first.width() >= first.sizeHint().width()
    assert second.width() >= second.sizeHint().width()
    first.setChecked(False)
    assert panel.selected_web_format() == "woff2"
    panel.set_conversion("ttf2otf")
    assert panel.format_label.isHidden() and first.isHidden() and second.isHidden()
    panel.set_conversion("ft2wf")
    assert not first.isChecked() and second.isChecked()
    panel.close()


def test_remove_dsig_option_is_available_only_with_woff_output(qapp: QApplication) -> None:
    panel = ProfileOptionsPanel()
    panel.set_conversion("ttf2otf")
    assert panel.remove_dsig.isHidden()

    panel.set_conversion("ft2wf")
    assert panel.remove_dsig.isVisibleTo(panel)
    panel.remove_dsig.setChecked(True)

    panel.format_woff.setChecked(False)
    assert panel.remove_dsig.isHidden()
    assert not panel.settings_for("ft2wf", ConversionOptions()).remove_dsig  # type: ignore[union-attr]

    panel.format_woff.setChecked(True)
    assert panel.remove_dsig.isVisibleTo(panel)
    assert panel.settings_for("ft2wf", ConversionOptions()).remove_dsig  # type: ignore[union-attr]


def test_target_upm_warning_tracks_option_and_common_values(qapp: QApplication) -> None:
    panel = ProfileOptionsPanel()
    panel.set_conversion("ttf2otf")

    assert panel.upm_warning_label.isHidden()
    panel.use_target_upm.setChecked(True)
    panel.target_upm.setValue(1234)
    assert not panel.upm_warning_label.isHidden()
    assert panel.target_upm_field.isEnabled()

    panel.target_upm.setValue(2048)
    assert panel.upm_warning_label.isHidden()
    panel.set_conversion("ft2wf")
    panel.target_upm.setValue(1234)
    assert panel.upm_warning_label.isHidden()


@pytest.mark.parametrize(
    ("conversion", "expected_type"),
    [
        ("ttf2otf", TtfToOtfOptions),
        ("otf2ttf", OtfToTtfOptions),
        ("ft2wf", SfntToWebOptions),
        ("woff2ft", WoffToSfntOptions),
        ("woff22ft", Woff2ToSfntOptions),
        ("ttc2sfnt", TtcToSfntOptions),
        ("var2static", VarToStaticOptions),
    ],
)
def test_settings_for_returns_typed_options_and_copies_common_values(
    qapp: QApplication, conversion: str, expected_type: type[ConversionOptions]
) -> None:
    panel = ProfileOptionsPanel()
    panel.set_conversion(conversion)
    panel.tolerance.setValue(1.5)
    panel.use_target_upm.setChecked(True)
    panel.target_upm.setValue(2048)
    panel.format_woff2.setChecked(False)
    instances = ((Path("variable.ttf"), (InstanceSpec((("wght", 700),), "Bold"),)),)
    common = ConversionOptions(
        recursive=True,
        output_dir=Path("output"),
        overwrite=False,
        recalc_bboxes=False,
        recalc_timestamp=True,
        reorder_tables=True,
        organization_levels=(("family", "format"), ("outline", "upm")),
    )

    settings = panel.settings_for(conversion, common, instances)

    assert isinstance(settings, expected_type)
    assert settings.recursive
    assert settings.output_dir == Path("output")
    assert not settings.overwrite
    assert not settings.recalc_bboxes
    assert settings.recalc_timestamp
    assert settings.reorder_tables
    assert settings.organization_levels == (("family", "format"), ("outline", "upm"))
    if isinstance(settings, (TtfToOtfOptions, OtfToTtfOptions)):
        assert settings.tolerance == 1.5
        assert settings.target_upm == 2048
    if isinstance(settings, SfntToWebOptions):
        assert settings.format == "woff"
    if isinstance(settings, VarToStaticOptions):
        assert settings.instances == instances
        assert settings.target_upm == 2048


def test_settings_for_rejects_unknown_conversion(qapp: QApplication) -> None:
    panel = ProfileOptionsPanel()

    with pytest.raises(ValueError, match="Unsupported conversion profile"):
        panel.settings_for("unknown", ConversionOptions())


def test_simplify_is_off_by_default_and_only_for_ttf2otf(qapp: QApplication) -> None:
    panel = ProfileOptionsPanel()

    assert panel.simplify.value() == 0
    assert panel.simplify.specialValueText() == "Off"
    assert not panel.simplify_field.isHidden()
    assert panel.settings_for("ttf2otf", ConversionOptions()).simplify == 0  # type: ignore[union-attr]

    panel.simplify.setValue(3)
    assert panel.settings_for("ttf2otf", ConversionOptions()).simplify == 3  # type: ignore[union-attr]

    panel.set_conversion("otf2ttf")
    assert panel.simplify_field.isHidden()


def test_empty_options_block_only_without_a_conversion(qapp: QApplication, app_font: None) -> None:
    from fontvertx.gui.profiles import CONVERSIONS

    panel = ProfileOptionsPanel()
    panel.setStyleSheet(stylesheet())
    panel.set_conversion(None)
    panel.show()
    qapp.processEvents()
    block = panel.no_profile_options
    assert block.isVisible()
    assert block.icon.size().width() == block.icon.size().height() == 40
    assert block.body.width() == 240
    # The whole wrapped body fits (the card has a fixed vertical policy).
    assert block.body.height() >= block.body.heightForWidth(240)
    # Icon -> title 12px, title -> body 8px, body lines 17px apart (12px text at 1.45).
    assert block.title.y() - block.icon.geometry().bottom() - 1 == 12
    assert block.body.y() - block.title.geometry().bottom() - 1 == 8
    lines = round(block.body.heightForWidth(240) / 17)
    assert lines >= 2
    assert abs(block.body.heightForWidth(240) - 17 * lines) <= 1
    for conversion in CONVERSIONS:
        panel.set_conversion(conversion)
        assert block.isHidden(), conversion
    panel.set_conversion(None)
    assert not block.isHidden()
    panel.close()
