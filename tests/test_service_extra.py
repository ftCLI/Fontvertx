from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from fontvertx import __main__ as entry
from fontvertx.models import (
    ConversionRequest,
    FontOutcomeKind,
    OtfToTtfOptions,
    SfntToWebOptions,
    TtcToSfntOptions,
    TtfToOtfOptions,
    Woff2ToSfntOptions,
    WoffToSfntOptions,
)
from fontvertx.service import ConverterService


def test_main_builds_application_and_window(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[object] = []

    class FakeWindow:
        def __init__(self) -> None:
            created.append(self)
            self.maximized = False

        def showMaximized(self) -> None:
            self.maximized = True

    monkeypatch.setattr(entry, "QApplication", lambda argv: qapp)
    monkeypatch.setattr(entry, "ConverterWindow", FakeWindow)
    monkeypatch.setattr(qapp, "exec", lambda: 7)
    assert entry.main() == 7
    assert created and created[0].maximized  # type: ignore[attr-defined]
    assert qapp.applicationName() == "Fontvertx"
    assert qapp.organizationName() == "Fontvertx"


def test_main_disables_combo_animation(qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeWindow:
        def showMaximized(self) -> None:
            pass

    monkeypatch.setattr(entry, "QApplication", lambda argv: qapp)
    monkeypatch.setattr(entry, "ConverterWindow", FakeWindow)
    monkeypatch.setattr(qapp, "exec", lambda: 0)
    original = QApplication.isEffectEnabled(Qt.UIEffect.UI_AnimateCombo)
    QApplication.setEffectEnabled(Qt.UIEffect.UI_AnimateCombo, True)
    try:
        entry.main()
        assert not QApplication.isEffectEnabled(Qt.UIEffect.UI_AnimateCombo)
    finally:
        QApplication.setEffectEnabled(Qt.UIEffect.UI_AnimateCombo, original)


def test_missing_input_path_is_reported(tmp_path: Path) -> None:
    result = ConverterService().convert(
        ConversionRequest((tmp_path / "missing",), TtfToOtfOptions())
    )
    assert not result.ok
    assert "FileNotFoundError" in (result.error or "")


def test_no_compatible_fonts_in_folder(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("not a font")
    result = ConverterService().convert(ConversionRequest((tmp_path,), TtfToOtfOptions()))
    assert result.error == "No compatible fonts found in the selected inputs."


def test_corrupt_collection_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "bad.ttc").write_bytes(b"ttcf" + b"\x00" * 8)
    result = ConverterService().convert(ConversionRequest((tmp_path,), TtcToSfntOptions()))
    assert result.error == "No compatible fonts found in the selected inputs."


def test_collection_extraction_cancel_between_members(fonts_dir: Path, tmp_path: Path) -> None:
    ttc = tmp_path / "c.ttc"
    shutil.copy(fonts_dir / "IBMPlexSans.ttc", ttc)
    calls = iter([False, False, True])
    result = ConverterService().convert(
        ConversionRequest((ttc,), TtcToSfntOptions(output_dir=tmp_path / "out")),
        should_cancel=lambda: next(calls, True),
    )
    assert result.cancelled
    assert result.converted_count == 1


def test_wrong_flavor_is_skipped_for_web_to_sfnt(fonts_dir: Path, tmp_path: Path) -> None:
    folder = tmp_path / "w"
    folder.mkdir()
    shutil.copy(fonts_dir / "IBMPlexSans-Regular-Latin1.woff", folder / "a.woff")
    shutil.copy(fonts_dir / "IBMPlexSans-Regular-Latin1.woff2", folder / "b.woff2")
    result = ConverterService().convert(
        ConversionRequest((folder,), Woff2ToSfntOptions(output_dir=tmp_path / "o"))
    )
    assert result.converted_count == 1
    assert result.skipped_count == 1
    assert [o.kind for o in result.outcomes].count(FontOutcomeKind.SKIPPED) == 1


def test_default_preserves_font_and_css_when_converting_twice(
    ttf_path: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    options = SfntToWebOptions(format="woff", output_dir=out, css_kit=True)
    assert not options.overwrite
    request = ConversionRequest((ttf_path,), options)
    first = ConverterService().convert(request)
    assert first.ok
    original = out / "test.woff"
    original_css = out / "fonts.css"
    first_bytes = original.read_bytes()
    first_css = original_css.read_text(encoding="utf-8")
    second = ConverterService().convert(request)
    assert second.ok
    assert second.saved_files == [out / "test#1.woff"]
    assert original.read_bytes() == first_bytes
    assert original_css.read_text(encoding="utf-8") == first_css
    # "#" is percent-encoded, otherwise it would be parsed as a fragment identifier.
    assert 'url("test%231.woff")' in (out / "fonts#1.css").read_text(encoding="utf-8")


def test_web_to_sfnt_default_preserves_existing_source_font(ttf_path: Path) -> None:
    original_bytes = ttf_path.read_bytes()
    web_result = ConverterService().convert(
        ConversionRequest((ttf_path,), SfntToWebOptions(format="woff"))
    )
    assert web_result.ok
    result = ConverterService().convert(
        ConversionRequest((web_result.saved_files[0],), WoffToSfntOptions())
    )
    assert result.ok
    assert result.saved_files == [ttf_path.with_name("test#1.ttf")]
    assert ttf_path.read_bytes() == original_bytes


def test_otf_to_ttf_with_target_upm_and_logging(fonts_dir: Path, tmp_path: Path) -> None:
    logs: list[str] = []
    options = OtfToTtfOptions(
        output_dir=tmp_path / "o", target_upm=2048, autohint=False, tolerance=1.0
    )
    result = ConverterService().convert(
        ConversionRequest((fonts_dir / "IBMPlexSans-Regular.otf",), options),
        on_log=logs.append,
    )
    assert result.ok and result.converted_count == 1
    assert any("Scaling UPM to 2048" in line for line in logs)
