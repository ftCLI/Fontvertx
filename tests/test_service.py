import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fontvertx import service as service_module
from fontvertx.models import (
    ConversionOptions,
    ConversionProgress,
    ConversionRequest,
    ConversionResult,
    FontOutcome,
    FontOutcomeKind,
    InstanceSpec,
    OtfToTtfOptions,
    SfntToWebOptions,
    TtcToSfntOptions,
    TtfToOtfOptions,
    VarToStaticOptions,
    WoffToSfntOptions,
)
from fontvertx.service import (
    ConverterService,
    _expect_settings,
    instance_label,
    instance_stem,
)


class FakeFont:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.path = args[0] if args else None

    def __enter__(self) -> "FakeFont":
        return self

    def __exit__(self, *args: Any) -> None:
        return None


def test_convert_rejects_empty_input() -> None:
    result = ConverterService().convert(ConversionRequest((), TtfToOtfOptions()))

    assert result == ConversionResult(error="Select at least one input file or folder.")


def test_convert_reports_skipped_candidates_when_none_are_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = Path("unsupported.otf")
    monkeypatch.setattr(
        ConverterService,
        "_find_candidates",
        lambda self, request: [(input_path, 1, False)],
    )
    progress: list[ConversionProgress] = []
    outcomes = []

    result = ConverterService().convert(
        ConversionRequest((input_path,), TtfToOtfOptions()),
        on_progress=progress.append,
        on_outcome=outcomes.append,
    )

    assert result.error == "No compatible fonts found in the selected inputs."
    assert result.skipped_count == 1
    assert result.converted_count == result.failed_count == 0
    assert progress == [ConversionProgress(0, 1), ConversionProgress(1, 1)]
    assert [outcome.kind for outcome in outcomes] == [FontOutcomeKind.SKIPPED]


def test_convert_reports_success_failure_and_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good_path = Path("good.ttf")
    bad_path = Path("bad.ttf")
    skipped_path = Path("unsupported.otf")
    monkeypatch.setattr(service_module, "Font", FakeFont)
    monkeypatch.setattr(
        ConverterService,
        "_find_candidates",
        lambda self, request: [
            (good_path, 1, True),
            (bad_path, 1, True),
            (skipped_path, 1, False),
        ],
    )

    def convert_by_path(
        self: ConverterService, font: FakeFont, settings: Any, on_log: Any, web_entries: Any = None
    ) -> list[Path]:
        if font.path == bad_path:
            raise ValueError("conversion failed")
        return [Path("output.otf")]

    monkeypatch.setattr(ConverterService, "_convert_font", convert_by_path)
    progress: list[ConversionProgress] = []
    reported = []

    result = ConverterService().convert(
        ConversionRequest((good_path, bad_path, skipped_path), TtfToOtfOptions()),
        on_progress=progress.append,
        on_outcome=reported.append,
    )

    assert [outcome.kind for outcome in result.outcomes] == [
        FontOutcomeKind.CONVERTED,
        FontOutcomeKind.FAILED,
        FontOutcomeKind.SKIPPED,
    ]
    assert result.outcomes[0].output_paths == (Path("output.otf"),)
    assert result.outcomes[1].error == "ValueError: conversion failed"
    assert (result.converted_count, result.failed_count, result.skipped_count) == (1, 1, 1)
    assert not result.ok
    assert progress == [
        ConversionProgress(0, 3),
        ConversionProgress(1, 3),
        ConversionProgress(2, 3),
        ConversionProgress(3, 3),
    ]
    assert reported == list(result.outcomes)


def test_convert_cancels_after_reporting_completed_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_path = Path("first.ttf")
    second_path = Path("second.ttf")
    monkeypatch.setattr(service_module, "Font", FakeFont)
    monkeypatch.setattr(
        ConverterService,
        "_find_candidates",
        lambda self, request: [(first_path, 1, True), (second_path, 1, True)],
    )
    monkeypatch.setattr(
        ConverterService,
        "_convert_font",
        lambda self, font, settings, on_log: [Path("first.otf")],
    )
    cancelled = False

    def on_outcome(_: Any) -> None:
        nonlocal cancelled
        cancelled = True

    result = ConverterService().convert(
        ConversionRequest((first_path, second_path), TtfToOtfOptions()),
        on_outcome=on_outcome,
        should_cancel=lambda: cancelled,
    )

    assert result.cancelled
    assert len(result.outcomes) == 1
    assert result.outcomes[0].input_path == first_path


def test_find_candidates_scans_recursively_and_ignores_invalid_files(
    tmp_path: Path, fonts_dir: Path
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    root_font = tmp_path / "root.ttf"
    nested_font = nested / "nested.ttf"
    shutil.copy(fonts_dir / "IBMPlexSans-Regular.ttf", root_font)
    shutil.copy(fonts_dir / "IBMPlexSans-Regular.ttf", nested_font)
    (tmp_path / "notes.txt").touch()

    request = ConversionRequest((tmp_path,), TtfToOtfOptions(recursive=True))

    candidates = ConverterService()._find_candidates(request)

    assert {path for path, _, compatible in candidates if compatible} == {
        root_font.resolve(),
        nested_font.resolve(),
    }


def test_conversion_result_summarizes_outcomes() -> None:
    result = ConversionResult(
        (
            FontOutcome(
                Path("converted.ttf"),
                FontOutcomeKind.CONVERTED,
                (Path("a.otf"), Path("b.otf")),
                elapsed=2.5,
            ),
            FontOutcome(Path("skipped.otf"), FontOutcomeKind.SKIPPED, elapsed=1.0),
            FontOutcome(
                Path("failed.ttf"), FontOutcomeKind.FAILED, error="conversion failed", elapsed=0.5
            ),
        )
    )

    assert result.elapsed == 4.0
    assert result.converted_count == 1
    assert result.skipped_count == 1
    assert result.failed_count == 1
    assert result.saved_files == [Path("a.otf"), Path("b.otf")]
    assert not result.ok


def test_instance_helpers_format_labels_and_sanitize_stems() -> None:
    coordinates = (("wght", 450.0), ("opsz", 11.5))

    assert instance_label(coordinates) == "wght450 opsz11.5"
    assert instance_stem(Path("Sample[opsz].ttf"), "Bold Italic", "") == "Sample-BoldItalic"
    assert (
        instance_stem(Path("Sample[opsz].ttf"), None, "wght450 opsz11.5")
        == "Sample-wght450-opsz11.5"
    )


def test_expect_settings_rejects_mismatched_conversion_options() -> None:
    with pytest.raises(TypeError, match="Expected OtfToTtfOptions, got TtfToOtfOptions"):
        _expect_settings(TtfToOtfOptions(), OtfToTtfOptions)


def test_output_dir_uses_requested_organization_levels(tmp_path: Path) -> None:
    font = SimpleNamespace(
        file=tmp_path / "input.ttf",
        units_per_em=1000,
        ttfont={"name": SimpleNamespace(getBestFamilyName=lambda: "Sample Family")},
    )
    settings = ConversionOptions(
        organization_levels=(("family",), ("format", "outline")),
    )

    output_dir = ConverterService._output_dir(font, settings, "woff2", is_tt=True)

    assert output_dir == tmp_path / "Sample Family" / "woff2_tt"
    assert output_dir.is_dir()


def test_output_dir_uses_ordered_combined_organization_levels(tmp_path: Path) -> None:
    font = SimpleNamespace(
        file=tmp_path / "input.ttf",
        units_per_em=1000,
        ttfont={"name": SimpleNamespace(getBestFamilyName=lambda: "Sample Family")},
    )
    settings = TtfToOtfOptions(
        target_upm=100,
        tolerance=1.5,
        simplify=2,
        organization_levels=(
            ("family", "format"),
            ("outline", "upm"),
            ("tolerance", "simplify"),
        ),
    )

    output_dir = ConverterService._output_dir(font, settings, "woff", is_tt=True)

    assert output_dir == (
        tmp_path / "Sample Family_woff" / "tt_upm_100" / "tolerance_1.5_simplify_2"
    )
    assert output_dir.is_dir()


def test_output_dir_rejects_organizing_bytes_without_destination() -> None:
    font = SimpleNamespace(file=None)
    settings = ConversionOptions(organization_levels=(("family",),))

    with pytest.raises(ValueError, match="Cannot organize output"):
        ConverterService._output_dir(font, settings, None, is_tt=False)


def test_instances_for_uses_matching_specs_or_default(tmp_path: Path) -> None:
    path = tmp_path / "variable.ttf"
    specs = (InstanceSpec((("wght", 700),), "Bold"),)
    settings = VarToStaticOptions(instances=((path, specs),))

    assert ConverterService._instances_for(settings, path.resolve()) == specs
    assert ConverterService._instances_for(settings, tmp_path / "other.ttf") == (InstanceSpec(()),)


class StubConversionFont:
    def __init__(self, path: Path, flavor: str | None = None, is_tt: bool = True) -> None:
        self.file = path
        self.ttfont = StubTTFont(flavor)
        self.is_tt = is_tt
        self.units_per_em = 1000
        self.operations: list[tuple[Any, ...]] = []

    def get_file_ext(self) -> str:
        return {None: ".ttf" if self.is_tt else ".otf", "woff": ".woff", "woff2": ".woff2"}[
            self.ttfont.flavor
        ]

    def get_file_path(
        self,
        file: Path | None = None,
        output_dir: Path | None = None,
        overwrite: bool = True,
        extension: str | None = None,
    ) -> Path:
        source = file or self.file
        return (output_dir or source.parent) / f"{source.stem}{extension or self.get_file_ext()}"

    def scale_upm(self, target: int) -> None:
        self.operations.append(("scale_upm", target))

    def to_otf(self, tolerance: float, simplify: int = 0) -> None:
        self.operations.append(("to_otf", tolerance))
        self.is_tt = False

    def subroutinize(self) -> bool:
        self.operations.append(("subroutinize",))
        return True

    def to_ttf(self, max_err: float, reverse_direction: bool) -> None:
        self.operations.append(("to_ttf", max_err, reverse_direction))
        self.is_tt = True

    def ttf_autohint(self) -> bool:
        self.operations.append(("autohint",))
        return True

    def remove_dsig(self) -> bool:
        self.operations.append(("remove_dsig",))
        return True

    def to_woff(self) -> None:
        self.operations.append(("to_woff",))
        self.ttfont.flavor = "woff"

    def to_woff2(self) -> None:
        self.operations.append(("to_woff2",))
        self.ttfont.flavor = "woff2"

    def to_sfnt(self) -> None:
        self.operations.append(("to_sfnt",))
        self.ttfont.flavor = None

    def save(self, path: Path, reorder_tables: bool | None = True) -> None:
        self.operations.append(("save", path, reorder_tables))


class StubTTFont:
    def __init__(self, flavor: str | None) -> None:
        self.flavor = flavor

    def __getitem__(self, key: str) -> SimpleNamespace:
        return SimpleNamespace(recalcAvgCharWidth=lambda ttFont: None)


def test_convert_font_runs_ttf_to_otf_steps() -> None:
    font = StubConversionFont(Path("input.ttf"))
    logs: list[str] = []

    outputs = ConverterService()._convert_font(font, TtfToOtfOptions(), logs.append)

    assert outputs == [Path("input.otf")]
    assert font.operations == [
        ("to_otf", 1.0),
        ("subroutinize",),
        ("save", Path("input.otf"), True),
    ]
    assert logs == ["Converting to OTF...", "Subroutinizing..."]


def test_convert_font_runs_otf_to_ttf_steps() -> None:
    font = StubConversionFont(Path("input.otf"), is_tt=False)

    outputs = ConverterService()._convert_font(
        font,
        OtfToTtfOptions(target_upm=2048),
        None,
    )

    assert outputs == [Path("input.ttf")]
    assert font.operations == [
        ("to_ttf", 1.0, True),
        ("scale_upm", 2048),
        ("autohint",),
        ("save", Path("input.ttf"), True),
    ]


@pytest.mark.parametrize(
    ("font", "settings", "expected_output"),
    [
        (
            StubConversionFont(Path("input.ttf")),
            TtfToOtfOptions(target_upm=1000),
            Path("input.otf"),
        ),
        (
            StubConversionFont(Path("input.otf"), is_tt=False),
            OtfToTtfOptions(target_upm=1000),
            Path("input.ttf"),
        ),
    ],
)
def test_convert_font_skips_scaling_when_target_upm_matches(
    font: StubConversionFont, settings: Any, expected_output: Path
) -> None:
    logs: list[str] = []

    outputs = ConverterService()._convert_font(font, settings, logs.append)

    assert outputs == [expected_output]
    assert not any(operation[0] == "scale_upm" for operation in font.operations)
    assert not any("Scaling UPM" in line for line in logs)


def test_convert_font_converts_sfnt_to_both_web_formats() -> None:
    font = StubConversionFont(Path("input.ttf"))
    logs: list[str] = []

    outputs = ConverterService()._convert_font(font, SfntToWebOptions(), logs.append)

    assert outputs == [Path("input.woff"), Path("input.woff2")]
    assert font.operations == [
        ("to_woff",),
        ("save", Path("input.woff"), True),
        ("to_woff2",),
        ("save", Path("input.woff2"), True),
    ]
    assert logs == ["Converting to WOFF", "Converting to WOFF2"]


def test_convert_font_removes_dsig_only_for_woff() -> None:
    font = StubConversionFont(Path("input.ttf"))
    logs: list[str] = []

    ConverterService()._convert_font(font, SfntToWebOptions(remove_dsig=True), logs.append)

    assert font.operations[0] == ("remove_dsig",)
    assert [op[0] for op in font.operations].count("remove_dsig") == 1
    assert logs == ["Removed the DSIG table", "Converting to WOFF", "Converting to WOFF2"]


def test_convert_font_removes_dsig_for_woff2_only() -> None:
    font = StubConversionFont(Path("input.ttf"))

    ConverterService()._convert_font(font, SfntToWebOptions(format="woff2", remove_dsig=True), None)

    assert ("remove_dsig",) in font.operations


def test_convert_font_converts_web_font_back_to_sfnt() -> None:
    font = StubConversionFont(Path("input.woff"), flavor="woff")

    outputs = ConverterService()._convert_font(font, WoffToSfntOptions(), None)

    assert outputs == [Path("input.ttf")]
    assert font.operations == [("to_sfnt",), ("save", Path("input.ttf"), True)]


def test_convert_extracts_each_collection_member_and_closes_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "collection.ttc"
    members = [object(), object()]

    class FakeCollection:
        closed = False

        def __init__(self, path: Path) -> None:
            assert path == input_path
            self.fonts = members

        def close(self) -> None:
            self.closed = True

    collection = FakeCollection(input_path)
    monkeypatch.setattr(service_module, "TTCollection", lambda path: collection)
    monkeypatch.setattr(
        ConverterService,
        "_find_candidates",
        lambda self, request: [(input_path, 2, True)],
    )
    monkeypatch.setattr(
        ConverterService,
        "_extract_collection_member",
        lambda self, path, member, settings, log: FontOutcome(
            path, FontOutcomeKind.CONVERTED, (Path(f"{members.index(member)}.ttf"),)
        ),
    )
    progress: list[ConversionProgress] = []
    started: list[Path] = []

    result = ConverterService().convert(
        ConversionRequest((input_path,), TtcToSfntOptions()),
        on_progress=progress.append,
        on_font_start=started.append,
    )

    assert result.converted_count == 2
    assert result.saved_files == [Path("0.ttf"), Path("1.ttf")]
    assert progress == [
        ConversionProgress(0, 2),
        ConversionProgress(1, 2),
        ConversionProgress(2, 2),
    ]
    assert started == [input_path, input_path]
    assert collection.closed


def test_convert_exports_each_selected_variable_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "variable.ttf"
    specs = (
        InstanceSpec((("wght", 400),), "Regular"),
        InstanceSpec((("wght", 700),), "Bold"),
    )
    monkeypatch.setattr(
        ConverterService,
        "_find_candidates",
        lambda self, request: [(input_path, len(specs), True)],
    )
    exported: list[InstanceSpec] = []

    def convert_instance(
        self: ConverterService,
        path: Path,
        spec: InstanceSpec,
        settings: VarToStaticOptions,
        used_stems: set[str],
        on_log: Any,
        log: Any,
    ) -> FontOutcome:
        exported.append(spec)
        return FontOutcome(path, FontOutcomeKind.CONVERTED, (Path(f"{spec.name}.ttf"),))

    monkeypatch.setattr(ConverterService, "_convert_instance", convert_instance)
    progress: list[ConversionProgress] = []
    started: list[Path] = []
    request = ConversionRequest(
        (input_path,),
        VarToStaticOptions(instances=((input_path, specs),)),
    )

    result = ConverterService().convert(
        request,
        on_progress=progress.append,
        on_font_start=started.append,
    )

    assert exported == list(specs)
    assert result.saved_files == [Path("Regular.ttf"), Path("Bold.ttf")]
    assert progress == [
        ConversionProgress(0, 2),
        ConversionProgress(1, 2),
        ConversionProgress(2, 2),
    ]
    assert started == [input_path, input_path]
