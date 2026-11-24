import shutil
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from fontvertx.finder import FontFinder
from fontvertx.models import (
    ConversionRequest,
    OtfToTtfOptions,
    SfntToWebOptions,
    TtcToSfntOptions,
    TtfToOtfOptions,
    Woff2ToSfntOptions,
    WoffToSfntOptions,
)
from fontvertx.service import ConverterService

REGULAR_TTF = "IBMPlexSans-Regular.ttf"
REGULAR_OTF = "IBMPlexSans-Regular.otf"
WOFF = "IBMPlexSans-Regular-Latin1.woff"
WOFF2 = "IBMPlexSans-Regular-Latin1.woff2"
TTC = "IBMPlexSans.ttc"


@pytest.fixture
def work_dir(tmp_path: Path, fonts_dir: Path) -> Path:
    for name in (REGULAR_TTF, REGULAR_OTF, WOFF, WOFF2, TTC):
        shutil.copy(fonts_dir / name, tmp_path / name)
    return tmp_path


def convert(path: Path, settings: object) -> list[Path]:
    result = ConverterService().convert(ConversionRequest((path,), settings))  # type: ignore[arg-type]
    assert result.ok, [outcome.error for outcome in result.outcomes]
    assert result.converted_count == 1
    return result.saved_files


def test_ttf_converts_to_otf(work_dir: Path) -> None:
    out_dir = work_dir / "out"
    (output,) = convert(
        work_dir / REGULAR_TTF,
        TtfToOtfOptions(output_dir=out_dir, subroutinize=False),
    )

    assert output.suffix == ".otf"
    with TTFont(output) as font:
        assert "CFF " in font
        assert "glyf" not in font


def test_otf_converts_to_ttf(work_dir: Path) -> None:
    out_dir = work_dir / "out"
    (output,) = convert(
        work_dir / REGULAR_OTF,
        OtfToTtfOptions(output_dir=out_dir, autohint=False),
    )

    assert output.suffix == ".ttf"
    with TTFont(output) as font:
        assert "glyf" in font
        assert "CFF " not in font


def test_ttf_converts_to_woff_and_woff2(work_dir: Path) -> None:
    out_dir = work_dir / "out"
    outputs = convert(work_dir / REGULAR_TTF, SfntToWebOptions(output_dir=out_dir))

    assert sorted(output.suffix for output in outputs) == [".woff", ".woff2"]
    flavors = {}
    for output in outputs:
        with TTFont(output) as font:
            flavors[output.suffix] = font.flavor
    assert flavors == {".woff": "woff", ".woff2": "woff2"}


@pytest.mark.parametrize(
    ("name", "options"), [(WOFF, WoffToSfntOptions), (WOFF2, Woff2ToSfntOptions)]
)
def test_web_fonts_convert_back_to_sfnt(work_dir: Path, name: str, options: type) -> None:
    out_dir = work_dir / "out"
    (output,) = convert(work_dir / name, options(output_dir=out_dir))

    assert output.suffix == ".ttf"
    with TTFont(output) as font:
        assert font.flavor is None
        assert "glyf" in font


def test_web_font_is_skipped_by_the_other_web_profile(work_dir: Path) -> None:
    result = ConverterService().convert(
        ConversionRequest((work_dir / WOFF2,), WoffToSfntOptions(output_dir=work_dir / "out"))
    )

    assert result.converted_count == 0
    assert result.skipped_count == 1


def test_web_options_obfuscate_subset_and_write_css_kit(work_dir: Path) -> None:
    out_dir = work_dir / "out"
    result = ConverterService().convert(
        ConversionRequest(
            (work_dir / REGULAR_TTF,),
            SfntToWebOptions(
                output_dir=out_dir,
                format="woff2",
                obfuscate_names=True,
                remove_unused_glyphs=True,
                css_kit=True,
            ),
        )
    )

    assert result.ok
    (output,) = result.saved_files
    assert not output.name.startswith("IBMPlexSans")
    with TTFont(work_dir / REGULAR_TTF) as original, TTFont(output) as font:
        assert "IBM" not in str(font["name"].getDebugName(1))
        assert str(font["name"].getDebugName(6)) == output.stem
        assert len(font.getGlyphOrder()) <= len(original.getGlyphOrder())
        assert set(original.getBestCmap()) == set(font.getBestCmap())
    css = (out_dir / "fonts.css").read_text(encoding="utf-8")
    assert f'url("{output.name}") format("woff2")' in css
    assert ".ft-liga" in css


def test_remove_non_windows_names_keeps_only_platform_3(work_dir: Path) -> None:
    out_dir = work_dir / "out"
    with TTFont(work_dir / REGULAR_TTF) as source:
        source["name"].setName("Mac only", 255, 1, 0, 0)
        assert any(record.platformID != 3 for record in source["name"].names)
        source.save(work_dir / "mac.ttf")

    (output,) = convert(
        work_dir / "mac.ttf",
        SfntToWebOptions(output_dir=out_dir, format="woff2", remove_non_windows_names=True),
    )

    with TTFont(output) as font:
        records = font["name"].names
        assert records
        assert {record.platformID for record in records} == {3}


def test_css_kit_is_not_written_by_default(work_dir: Path) -> None:
    out_dir = work_dir / "out"
    convert(work_dir / REGULAR_TTF, SfntToWebOptions(output_dir=out_dir, format="woff"))

    assert not (out_dir / "fonts.css").exists()


def test_ttc_is_split_into_members(work_dir: Path) -> None:
    out_dir = work_dir / "out"
    result = ConverterService().convert(
        ConversionRequest((work_dir / TTC,), TtcToSfntOptions(output_dir=out_dir))
    )

    assert result.ok
    assert sorted(path.name for path in result.saved_files) == [
        "IBMPlexSans-Italic.ttf",
        "IBMPlexSans.ttf",
    ]
    for path in result.saved_files:
        with TTFont(path) as font:
            assert "glyf" in font


def test_directory_scan_skips_incompatible_fonts(work_dir: Path) -> None:
    out_dir = work_dir / "out"
    result = ConverterService().convert(
        ConversionRequest((work_dir,), TtfToOtfOptions(output_dir=out_dir, subroutinize=False))
    )

    assert result.ok
    assert result.converted_count == 3
    assert result.skipped_count >= 1
    assert ".otf" in {path.suffix for path in result.saved_files}


def test_finder_accepts_real_fonts(fonts_dir: Path) -> None:
    fonts = FontFinder(fonts_dir).find_fonts()
    names = {font.file.name for font in fonts if font.file}
    for font in fonts:
        font.close()
    assert {REGULAR_TTF, REGULAR_OTF, WOFF, WOFF2} <= names

    collections = FontFinder(fonts_dir).find_collections()
    assert [len(collection.fonts) for collection in collections] == [2]
