from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from fontvertx.font import Font, FontConversionError
from fontvertx.models import (
    ConversionRequest,
    FontOutcomeKind,
    InstanceSpec,
    VarToStaticOptions,
)
from fontvertx.service import ConverterService


@pytest.fixture
def vf_path(tmp_path: Path, fonts_dir: Path) -> Path:
    path = tmp_path / "TestVF.ttf"
    shutil.copy(fonts_dir / "TestVF.ttf", path)
    return path


def test_variable_font_properties(vf_path: Path) -> None:
    with Font(vf_path) as font:
        assert font.is_variable
        assert not font.is_static
        assert [axis.axisTag for axis in font.axes] == ["wght"]


def test_variable_font_rejects_static_conversions(vf_path: Path) -> None:
    with Font(vf_path) as font, pytest.raises(FontConversionError):
        font.to_otf()
    with Font(vf_path) as font:
        font.ttfont.sfntVersion = "OTTO"
        with pytest.raises(FontConversionError):
            font.to_ttf()


def test_to_static_custom_instance_rebuilds_names(vf_path: Path) -> None:
    with Font(vf_path) as font:
        label = font.to_static({"wght": 550})
        assert label == "wght550"
        assert font.is_static
        assert font.get_postscript_name() == "TestVF-wght550"


def test_to_static_named_instance(vf_path: Path) -> None:
    with Font(vf_path) as font:
        label = font.to_static({"wght": 700}, name="Bold")
        assert label == "wght700"
        assert font.is_static


def test_to_static_default_location_and_static_error(vf_path: Path, ttf_path: Path) -> None:
    with Font(vf_path) as font:
        assert font.to_static() == "wght400"
    with Font(ttf_path) as font, pytest.raises(FontConversionError):
        font.to_static()


def test_static_instance_pipeline(vf_path: Path) -> None:
    with Font(vf_path) as font:
        font.to_static({"wght": 600})
        font.scale_upm(2000)
        assert font.units_per_em == 2000
        font.correct_contours()
        assert font.ttf_autohint()
        assert font.is_tt


def test_autohint_and_subroutinize_type_checks(vf_path: Path, fonts_dir: Path) -> None:
    with Font(vf_path) as font, pytest.raises(NotImplementedError):
        font.subroutinize()
    with Font(fonts_dir / "IBMPlexSans-Regular.otf") as font:
        with pytest.raises(NotImplementedError):
            font.ttf_autohint()
        assert font.subroutinize()


def test_autohint_failure_restores_flavor(ttf_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fontvertx import font as font_module

    def boom(**kwargs: object) -> bytes:
        raise RuntimeError("no hinter")

    monkeypatch.setattr(font_module, "ttfautohint", boom)
    with Font(ttf_path) as font:
        font.to_woff()
        with pytest.raises(FontConversionError, match="Autohinting failed"):
            font.ttf_autohint()
        assert font.is_woff


def test_correct_contours_postscript(fonts_dir: Path) -> None:
    with Font(fonts_dir / "IBMPlexSans-Regular.otf") as font:
        assert isinstance(font.correct_contours(), set)


def test_invalid_source_type() -> None:
    from fontvertx.font import FontError

    with pytest.raises(FontError):
        Font(123)  # type: ignore[arg-type]


def test_get_file_path_requires_name_for_bytesio(ttf_path: Path) -> None:
    from io import BytesIO

    buffer = BytesIO(ttf_path.read_bytes())
    with Font(buffer) as font, pytest.raises(ValueError):
        font.get_file_path()


def _convert(path: Path, **kwargs: object) -> tuple[object, list[Path]]:
    options = VarToStaticOptions(**kwargs)  # type: ignore[arg-type]
    result = ConverterService().convert(ConversionRequest((path,), options))
    return result, [p for outcome in result.outcomes for p in outcome.output_paths]


def test_service_var2static_default_instance(vf_path: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    result, outputs = _convert(vf_path, output_dir=out)
    assert result.ok  # type: ignore[attr-defined]
    assert len(outputs) == 1
    assert outputs[0].exists()
    with Font(outputs[0]) as font:
        assert font.is_static


def test_service_var2static_preserves_existing_instance(vf_path: Path, tmp_path: Path) -> None:
    options = VarToStaticOptions(output_dir=tmp_path / "out", autohint=False)
    request = ConversionRequest((vf_path,), options)
    first = ConverterService().convert(request)
    assert first.ok
    original = first.saved_files[0]
    original_bytes = original.read_bytes()
    second = ConverterService().convert(request)
    assert second.ok
    assert second.saved_files == [original.with_name(f"{original.stem}#1{original.suffix}")]
    assert original.read_bytes() == original_bytes


def test_service_var2static_multiple_instances_and_organize(vf_path: Path, tmp_path: Path) -> None:
    specs = (
        InstanceSpec((("wght", 400.0),), "Light"),
        InstanceSpec((("wght", 700.0),), "Light"),
        InstanceSpec((("wght", 550.0),)),
    )
    logs: list[str] = []
    options = VarToStaticOptions(
        output_dir=tmp_path / "out",
        organization_levels=(("family",), ("format", "outline")),
        instances=((vf_path, specs),),
        target_upm=2000,
    )
    result = ConverterService().convert(ConversionRequest((vf_path,), options), on_log=logs.append)
    assert result.converted_count == 3
    names = {p.name for p in result.saved_files}
    assert len(names) == 3
    assert all("TestVF" in str(p) and "opentype_tt" in str(p) for p in result.saved_files)
    assert any("Scaling UPM" in line for line in logs)


def test_service_var2static_skips_scaling_when_target_upm_matches(
    vf_path: Path, tmp_path: Path
) -> None:
    with Font(vf_path) as font:
        target_upm = font.units_per_em
    logs: list[str] = []
    result = ConverterService().convert(
        ConversionRequest(
            (vf_path,),
            VarToStaticOptions(output_dir=tmp_path / "out", target_upm=target_upm),
        ),
        on_log=logs.append,
    )

    assert result.ok
    assert not any("Scaling UPM" in line for line in logs)


def test_service_var2static_instance_with_unknown_axes_fails(vf_path: Path, tmp_path: Path) -> None:
    options = VarToStaticOptions(
        output_dir=tmp_path / "out",
        instances=((vf_path, (InstanceSpec((("slnt", 1.0),)),)),),
    )
    result = ConverterService().convert(ConversionRequest((vf_path,), options))
    assert result.failed_count == 1
    assert result.outcomes[0].kind is FontOutcomeKind.FAILED
    assert "does not match" in (result.outcomes[0].error or "")


def test_service_var2static_skips_static_fonts(
    vf_path: Path, ttf_path: Path, tmp_path: Path
) -> None:
    folder = tmp_path / "mix"
    folder.mkdir()
    shutil.copy(vf_path, folder / "v.ttf")
    shutil.copy(ttf_path, folder / "s.ttf")
    result = ConverterService().convert(
        ConversionRequest((folder,), VarToStaticOptions(output_dir=tmp_path / "o"))
    )
    assert result.converted_count == 1
    assert result.skipped_count == 1


def test_service_var2static_cancel(vf_path: Path, tmp_path: Path) -> None:
    result = ConverterService().convert(
        ConversionRequest((vf_path,), VarToStaticOptions(output_dir=tmp_path / "o")),
        should_cancel=lambda: True,
    )
    assert result.cancelled
