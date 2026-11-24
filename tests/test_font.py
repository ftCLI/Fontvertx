from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fontTools.ttLib import newTable

from fontvertx.font import Font, FontConversionError, FontError


def test_font_properties_and_context_manager(ttf_path: Path) -> None:
    with Font(ttf_path) as font:
        assert font.file == ttf_path.resolve()
        assert font.bytesio is None
        assert font.is_tt
        assert not font.is_ps
        assert font.is_sfnt
        assert font.is_static
        assert not font.is_variable
        assert font.units_per_em == 1000
        assert font.get_file_ext() == ".ttf"

    assert font.ttfont.reader is None


def test_font_accepts_ttfont_and_bytesio_sources(ttf_path: Path) -> None:
    source = Font(ttf_path)
    copied = Font(source.ttfont)
    buffer = BytesIO()
    copied.save(buffer)
    buffer.seek(0)
    from_buffer = Font(buffer)

    assert copied.file is None
    assert from_buffer.file is None
    assert from_buffer.bytesio is buffer
    assert from_buffer.is_tt

    source.close()
    copied.close()
    from_buffer.close()
    assert buffer.closed


def test_font_rejects_unsupported_source_type() -> None:
    with pytest.raises(FontError, match="Invalid source type"):
        Font(object())  # type: ignore[arg-type]


def test_postscript_name_is_created_only_when_missing(ttf_path: Path) -> None:
    with Font(ttf_path) as font:
        font.ttfont["name"].removeNames(nameID=6)
        font.ensure_postscript_name()
        assert font.get_postscript_name() == "IBMPlexSans-Regular"

        font.ttfont["name"].setName("Custom-PS", 6, 3, 1, 0x409)
        font.ensure_postscript_name()
        assert font.get_postscript_name() == "Custom-PS"


def test_web_flavor_changes_and_duplicate_conversion_errors(ttf_path: Path) -> None:
    with Font(ttf_path) as font:
        font.to_woff()
        assert font.is_woff
        assert font.get_file_ext() == ".woff"
        with pytest.raises(FontConversionError, match="already a WOFF"):
            font.to_woff()

        font.to_woff2()
        assert font.is_woff2
        assert font.get_file_ext() == ".woff2"
        with pytest.raises(FontConversionError, match="already a WOFF2"):
            font.to_woff2()

        font.to_sfnt()
        assert font.is_sfnt
        with pytest.raises(FontConversionError, match="already a TTF or OTF"):
            font.to_sfnt()


def test_scale_upm_validates_bounds_and_scales_font(ttf_path: Path) -> None:
    with Font(ttf_path) as font:
        font.scale_upm(1000)
        assert font.units_per_em == 1000

        x_max = font.ttfont["glyf"]["A"].xMax
        font.scale_upm(2000)
        assert font.units_per_em == 2000
        assert font.ttfont["glyf"]["A"].xMax == x_max * 2

        for value in (15, 16385):
            with pytest.raises(ValueError, match="units_per_em must be in the range"):
                font.scale_upm(value)


def test_output_path_supports_custom_directories_and_non_overwrite(
    ttf_path: Path, tmp_path: Path
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    existing = output_dir / "test.ttf"
    existing.touch()

    with Font(ttf_path) as font:
        output = font.get_file_path(output_dir=output_dir, overwrite=False)

    assert output.parent == output_dir
    assert output != existing
    assert output.suffix == ".ttf"


def test_bytes_font_requires_explicit_filename(ttf_path: Path) -> None:
    with (
        Font(BytesIO(ttf_path.read_bytes())) as font,
        pytest.raises(ValueError, match="without providing a file name"),
    ):
        font.get_file_path()


@pytest.mark.parametrize(
    ("name", "named_instance_succeeds", "expected_label", "expected_updates"),
    [
        (None, True, "wght700", [False]),
        ("Bold", True, "wght700", [True]),
        ("Bold", False, "wght700", [True, False]),
    ],
)
def test_to_static_builds_instance_and_preserves_flavor(
    ttf_path: Path,
    name: str | None,
    named_instance_succeeds: bool,
    expected_label: str,
    expected_updates: list[bool],
) -> None:
    axis = SimpleNamespace(axisTag="wght", defaultValue=400)

    class VariableFont(dict[str, Any]):
        flavor = "woff2"
        closed = False

        def close(self) -> None:
            self.closed = True

    original = VariableFont(fvar=SimpleNamespace(axes=[axis]))
    instance = VariableFont()
    attempts: list[bool] = []
    written_names: list[str] = []

    with Font(ttf_path) as font:
        font._ttfont = original  # type: ignore[assignment]

        def instantiate(location: dict[str, float], update_names: bool) -> VariableFont:
            attempts.append(update_names)
            if update_names and not named_instance_succeeds:
                raise ValueError("STAT names unavailable")
            return instance

        font._instantiate = instantiate  # type: ignore[method-assign]
        font._write_instance_names = lambda target, label: written_names.append(label)  # type: ignore[method-assign]

        label = font.to_static({"wght": 700}, name=name)

        assert label == expected_label
        assert font.ttfont is instance
        assert font.ttfont.flavor == "woff2"
        assert original.closed
        assert attempts == expected_updates
        expected_name = name or expected_label
        assert written_names == ([] if name and named_instance_succeeds else [expected_name])


def test_write_instance_names_updates_standard_name_records(ttf_path: Path) -> None:
    with Font(ttf_path) as font:
        Font._write_instance_names(font.ttfont, "Bold")
        name_table = font.ttfont["name"]

        # RIBBI style: legacy family/subfamily must link to the Bold style.
        assert name_table.getDebugName(1) == "IBM Plex Sans"
        assert name_table.getDebugName(2) == "Bold"
        assert name_table.getDebugName(6) == "IBMPlexSans-Bold"


def test_write_instance_names_keeps_non_ribbi_style_in_family(ttf_path: Path) -> None:
    with Font(ttf_path) as font:
        Font._write_instance_names(font.ttfont, "Black")
        name_table = font.ttfont["name"]

        assert name_table.getDebugName(1) == "IBM Plex Sans Black"
        assert name_table.getDebugName(2) == "Regular"
        assert name_table.getDebugName(6) == "IBMPlexSans-Black"


def test_to_otf_renames_first_glyph_to_notdef(ttf_path: Path) -> None:
    with Font(ttf_path) as font:
        ttfont = font.ttfont
        order = ttfont.getGlyphOrder()
        old = order[0]
        glyf = ttfont["glyf"]
        glyf.glyphs["uniE000"] = glyf.glyphs.pop(old)
        ttfont["hmtx"].metrics["uniE000"] = ttfont["hmtx"].metrics.pop(old)
        ttfont.setGlyphOrder(["uniE000", *order[1:]])
        glyf.glyphOrder = ttfont.getGlyphOrder()

        font.to_otf()

        assert font.ttfont.getGlyphOrder()[0] == ".notdef"


def test_to_otf_and_back_to_ttf(ttf_path: Path) -> None:
    with Font(ttf_path) as font:
        font.to_otf()

        assert font.is_ps
        assert "CFF " in font.ttfont
        assert font.get_file_ext() == ".otf"

        with pytest.raises(FontConversionError, match="already a PostScript"):
            font.to_otf()
        with (
            Font(ttf_path) as already_ttf,
            pytest.raises(FontConversionError, match="already a TrueType"),
        ):
            already_ttf.to_ttf()

        font.to_ttf()
        assert font.is_tt
        assert "glyf" in font.ttfont
        assert font.get_file_ext() == ".ttf"


def test_obfuscate_names_updates_cff_names(otf_path_for_names: Path) -> None:
    with Font(otf_path_for_names) as font:
        family, ps_name = font.obfuscate_names()
        cff = font.ttfont["CFF "].cff
        assert cff.fontNames == [ps_name]
        assert cff.topDictIndex[0].FamilyName == family


def test_remove_non_windows_names_and_dsig_and_features(ttf_path: Path) -> None:
    with Font(ttf_path) as font:
        font.ttfont["DSIG"] = newTable("DSIG")
        assert font.remove_dsig() is True
        assert font.remove_dsig() is False
        assert "DSIG" not in font.ttfont
        font.ttfont["name"].setName("Mac", 1, 1, 0, 0)
        assert font.remove_non_windows_names() >= 1
        assert all(r.platformID == 3 for r in font.ttfont["name"].names)
        assert "kern" in font.get_features() or font.get_features()
        del font.ttfont["GSUB"]
        font.get_features()


def test_decompose_transformed_handles_scaled_components(ttf_path: Path) -> None:
    with Font(ttf_path) as font:
        glyf = font.ttfont["glyf"]
        name = next(n for n in font.ttfont.getGlyphOrder() if glyf[n].isComposite())
        glyf[name].components[0].transform = [[0.5, 0], [0, 0.5]]
        assert name in font.decompose_transformed()
        assert not glyf[name].isComposite()


@pytest.fixture
def otf_path_for_names(tmp_path: Path, fonts_dir: Path) -> Path:
    import shutil

    path = tmp_path / "test.otf"
    shutil.copy(fonts_dir / "IBMPlexSans-Regular.otf", path)
    return path
