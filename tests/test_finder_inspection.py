from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fontTools.ttLib import TTLibError

from fontvertx import finder as finder_module
from fontvertx import inspection as inspection_module
from fontvertx.finder import (
    FinderError,
    FinderFilter,
    FinderOptions,
    FontFinder,
    iter_files,
)
from fontvertx.inspection import (
    AxisInfo,
    FontInfo,
    NamedInstanceInfo,
    incompatibility,
    inspect_font,
)


class FakeFont:
    def __init__(self, path: Path, **kwargs: Any) -> None:
        if path.suffix == ".invalid":
            raise TTLibError("invalid font")
        self.path = path
        self.closed = False
        self.is_tt = True
        self.is_ps = False
        self.is_woff = False
        self.is_woff2 = False
        self.is_sfnt = True
        self.is_static = True
        self.is_variable = False

    def __enter__(self) -> "FakeFont":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("filter_", "message"),
    [
        (FinderFilter(filter_out_tt=True, filter_out_ps=True), "both TrueType and PostScript"),
        (
            FinderFilter(filter_out_woff=True, filter_out_woff2=True, filter_out_sfnt=True),
            "WOFF, WOFF2, TTF and OTF",
        ),
        (
            FinderFilter(filter_out_static=True, filter_out_variable=True),
            "both static and variable",
        ),
    ],
)
def test_finder_rejects_conflicting_filters(filter_: FinderFilter, message: str) -> None:
    with pytest.raises(FinderError, match=message):
        FontFinder(Path.cwd(), filter_=filter_)


def test_finder_requires_an_existing_path(tmp_path: Path) -> None:
    with pytest.raises(FinderError, match="Invalid input path"):
        FontFinder(tmp_path / "missing")


def test_finder_filters_closes_rejected_fonts_and_skips_invalid_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    accepted = tmp_path / "accepted.ttf"
    rejected = tmp_path / "rejected.ttf"
    invalid = tmp_path / "broken.invalid"
    for path in (accepted, rejected, invalid):
        path.touch()
    fonts: list[FakeFont] = []

    def make_font(path: Path, **kwargs: Any) -> FakeFont:
        font = FakeFont(path)
        fonts.append(font)
        if path == rejected:
            font.is_tt = False
            font.is_ps = True
        return font

    monkeypatch.setattr(finder_module, "Font", make_font)
    finder = FontFinder(tmp_path, filter_=FinderFilter(filter_out_ps=True))

    found = finder.find_fonts()

    assert [font.path for font in found] == [accepted]
    assert all(font.closed for font in fonts if font.path == rejected)
    assert all(font.path != invalid for font in fonts)


def test_finder_respects_recursive_option(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "root.ttf").touch()
    (nested / "nested.ttf").touch()

    shallow = list(FontFinder(tmp_path)._generate_files())
    recursive = list(FontFinder(tmp_path, options=FinderOptions(recursive=True))._generate_files())

    assert {path.name for path in shallow} == {"root.ttf"}
    assert {path.name for path in recursive} == {"root.ttf", "nested.ttf"}


def test_iter_files_expands_files_and_folders(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    single = tmp_path / "single.ttf"
    single.touch()
    (nested / "a.ttf").touch()
    (nested / "deep").mkdir()
    (nested / "deep" / "b.ttf").touch()

    sources = [single, nested, tmp_path / "missing"]
    shallow = list(iter_files(sources, recursive=False))
    recursive = list(iter_files(sources, recursive=True))

    assert {path.name for path in shallow} == {"single.ttf", "a.ttf"}
    assert {path.name for path in recursive} == {"single.ttf", "a.ttf", "b.ttf"}


@pytest.mark.parametrize(
    ("info", "conversion", "expected"),
    [
        (
            FontInfo(Path("font.ttc"), "TTC", "TrueType", 1000, collection=True),
            "ttc2sfnt",
            None,
        ),
        (
            FontInfo(Path("font.otf"), "OTF", "PostScript", 1000),
            "ttf2otf",
            "Not a TrueType font",
        ),
        (
            FontInfo(Path("font.ttf"), "TTF", "TrueType", 1000),
            "otf2ttf",
            "Not a PostScript font",
        ),
        (
            FontInfo(Path("font.ttf"), "TTF", "TrueType", 1000),
            "var2static",
            "Not a variable font",
        ),
        (
            FontInfo(Path("font.woff"), "WOFF", "TrueType", 1000),
            "ft2wf",
            "Already a web font",
        ),
        (FontInfo(Path("font.ttf"), "TTF", "TrueType", 1000), "woff2ft", "Not a web font"),
        (
            FontInfo(Path("font.woff"), "WOFF", "TrueType", 1000),
            "woff22ft",
            "Not a WOFF2 font",
        ),
        (
            FontInfo(Path("font.woff2"), "WOFF2", "TrueType", 1000),
            "woff2ft",
            "Not a WOFF font",
        ),
        (FontInfo(Path("font.woff"), "WOFF", "TrueType", 1000), "woff2ft", None),
    ],
)
def test_incompatibility_explains_format_mismatches(
    info: FontInfo, conversion: str, expected: str | None
) -> None:
    assert incompatibility(info, conversion) == expected


def test_incompatibility_handles_collections_and_variable_fonts() -> None:
    collection = FontInfo(Path("font.ttc"), "TTC", "Mixed", None, collection=True)
    variable = FontInfo(Path("font.ttf"), "TTF", "TrueType", 1000, variable=True)

    assert incompatibility(collection, "ttf2otf") == (
        "Font collections require the Collection (TTC/OTC) → TTF / OTF profile"
    )
    assert incompatibility(collection, "ttc2sfnt") is None
    assert incompatibility(variable, "ttf2otf") == "Variable fonts are not supported"
    assert incompatibility(variable, "var2static") is None


def test_inspect_font_caches_results_and_refreshes_when_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "font.ttf"
    path.write_bytes(b"font")
    first = FontInfo(path, "TTF", "TrueType", 1000, family="First", style="Regular")
    second = FontInfo(path, "OTF", "PostScript", 1000, family="Second", style="Bold")
    reads = []

    def read_font_info(font_path: Path) -> FontInfo:
        reads.append(font_path)
        return first if len(reads) == 1 else second

    monkeypatch.setattr("fontvertx.inspection._read_font_info", read_font_info)

    assert inspect_font(path) == first
    assert inspect_font(path) == first
    path.write_bytes(b"changed font")
    assert inspect_font(path) == second
    assert reads == [path, path]


def test_inspect_font_returns_none_for_missing_file() -> None:
    assert inspect_font(Path("missing-font-file.ttf")) is None


def test_read_font_info_includes_variable_axes_and_named_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "variable.ttf"
    axis = SimpleNamespace(axisTag="wght", minValue=100, defaultValue=400, maxValue=900)
    instance = SimpleNamespace(subfamilyNameID=2, coordinates={"wght": 700})
    ttfont = {
        "fvar": SimpleNamespace(axes=[axis], instances=[instance]),
        "name": SimpleNamespace(
            getDebugName=lambda name_id: "Bold",
            getBestFamilyName=lambda: "Example",
            getBestSubFamilyName=lambda: "Regular",
        ),
    }

    class VariableFont(FakeFont):
        def __init__(self, path: Path, **kwargs: Any) -> None:
            super().__init__(path)
            self.is_variable = True
            self.units_per_em = 1000
            self.ttfont = ttfont

    class FakeFinder:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def generate_fonts(self) -> list[VariableFont]:
            return [VariableFont(path)]

    monkeypatch.setattr(inspection_module, "FontFinder", FakeFinder)

    info = inspection_module._read_font_info(path)

    assert info == FontInfo(
        path,
        "TTF",
        "TrueType",
        1000,
        variable=True,
        axes=(AxisInfo("wght", 100, 400, 900),),
        instances=(NamedInstanceInfo("Bold", (("wght", 700),)),),
        family="Example",
        style="Regular",
    )


@pytest.mark.parametrize(
    ("flags", "expected_format", "expected_outlines"),
    [
        ({"is_woff2": True}, "WOFF2", "TrueType"),
        ({"is_woff": True}, "WOFF", "TrueType"),
        ({"is_ps": True}, "OTF", "PostScript"),
        ({}, "TTF", "TrueType"),
    ],
)
def test_read_font_info_detects_outline_and_container_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    flags: dict[str, bool],
    expected_format: str,
    expected_outlines: str,
) -> None:
    path = tmp_path / "font.bin"
    font = FakeFont(path)
    font.is_woff2 = flags.get("is_woff2", False)
    font.is_woff = flags.get("is_woff", False)
    font.is_ps = flags.get("is_ps", False)
    font.units_per_em = 1000
    font.ttfont = {}

    class FakeFinder:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def generate_fonts(self) -> list[FakeFont]:
            return [font]

    monkeypatch.setattr(inspection_module, "FontFinder", FakeFinder)

    info = inspection_module._read_font_info(path)

    assert info is not None
    assert (info.format, info.outlines) == (expected_format, expected_outlines)
    assert (info.family, info.style) == ("", "")


@pytest.mark.parametrize(
    ("font_data", "expected_outlines", "expected_upm", "expected_variable", "family", "style"),
    [
        (
            [("ps", 1000, False, "Family", "Regular"), ("ps", 1000, False, "Family", "Regular")],
            "PostScript",
            1000,
            False,
            "Family",
            "Regular",
        ),
        (
            [("ps", 1000, False, "One", "Regular"), ("tt", 2000, True, "Two", "Bold")],
            "Mixed",
            None,
            True,
            "Mixed",
            "Mixed",
        ),
        (
            [("ps", 1000, False, "Family", None), ("ps", 1000, False, "Family", "Bold")],
            "PostScript",
            1000,
            False,
            "Family",
            "Mixed",
        ),
    ],
)
def test_read_collection_info_summarizes_members_and_closes_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    font_data: list[tuple[str, int, bool, str | None, str | None]],
    expected_outlines: str,
    expected_upm: int | None,
    expected_variable: bool,
    family: str,
    style: str,
) -> None:
    path = tmp_path / "fonts.ttc"

    class FakeMember(dict[str, Any]):
        def __init__(self, sfnt_version: str) -> None:
            super().__init__()
            self.sfntVersion = sfnt_version

    members = []
    for outline, upm, variable, member_family, member_style in font_data:
        member = FakeMember("OTTO" if outline == "ps" else "\x00\x01\x00\x00")
        member["head"] = SimpleNamespace(unitsPerEm=upm)
        member["name"] = SimpleNamespace(
            getBestFamilyName=lambda name=member_family: name,
            getBestSubFamilyName=lambda name=member_style: name,
        )
        if variable:
            member["fvar"] = object()
        members.append(member)
    collection = SimpleNamespace(fonts=members, closed=False)
    collection.close = lambda: setattr(collection, "closed", True)

    class FakeFinder:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def generate_fonts(self) -> list[FakeFont]:
            return []

        def generate_collections(self) -> list[Any]:
            return [collection]

    monkeypatch.setattr(inspection_module, "FontFinder", FakeFinder)

    info = inspection_module._read_font_info(path)

    assert info == FontInfo(
        path,
        "TTC",
        expected_outlines,
        expected_upm,
        variable=expected_variable,
        collection=True,
        num_fonts=len(font_data),
        family=family,
        style=style,
    )
    assert collection.closed


@pytest.mark.parametrize(
    ("filename", "family", "style"),
    [
        ("IBMPlexSans-Regular.ttf", "IBM Plex Sans", "Regular"),
        ("IBMPlexSans-Regular.otf", "IBM Plex Sans", "Regular"),
        ("IBMPlexSans-Regular-Latin1.woff", "IBM Plex Sans", "Regular"),
        ("IBMPlexSans-Regular-Latin1.woff2", "IBM Plex Sans", "Regular"),
        ("IBMPlexSans.ttc", "IBM Plex Sans", "Mixed"),
        ("TestVF.ttf", "TestVF", "Regular"),
    ],
)
def test_inspect_font_reads_family_and_style(
    fonts_dir: Path, filename: str, family: str, style: str
) -> None:
    info = inspect_font(fonts_dir / filename)
    assert info is not None
    assert (info.family, info.style) == (family, style)


def test_read_font_info_returns_none_when_no_font_or_collection_is_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeFinder:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def generate_fonts(self) -> list[FakeFont]:
            return []

        def generate_collections(self) -> list[Any]:
            return []

    monkeypatch.setattr(inspection_module, "FontFinder", FakeFinder)

    assert inspection_module._read_font_info(tmp_path / "empty.ttf") is None


def test_font_info_instance_fields_are_immutable_values() -> None:
    info = FontInfo(
        Path("variable.ttf"),
        "TTF",
        "TrueType",
        1000,
        variable=True,
        axes=(AxisInfo("wght", 100, 400, 900),),
        instances=(NamedInstanceInfo("Bold", (("wght", 700),)),),
    )

    assert info.axes[0].default == 400
    assert info.instances[0].coordinates == (("wght", 700),)
