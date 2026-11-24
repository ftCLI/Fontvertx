import logging
from pathlib import Path
from typing import Any

import pathops
import pytest
from fontTools import subset
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

from fontvertx import contours as contours_module
from fontvertx.contours import (
    CorrectContoursError,
    correct_cff_contours,
    correct_glyf_contours,
    simplify_path,
)
from fontvertx.qu2cu import quadratics_to_cubics


def square(pen: Any, x: int, y: int, size: int = 200) -> None:
    pen.moveTo((x, y))
    pen.lineTo((x, y + size))
    pen.lineTo((x + size, y + size))
    pen.lineTo((x + size, y))
    pen.closePath()


def overlapping_path() -> pathops.Path:
    path = pathops.Path()
    pen = path.getPen()
    square(pen, 0, 0)
    square(pen, 100, 100)
    return path


def subset_font(fonts_dir: Path, name: str) -> TTFont:
    font = TTFont(fonts_dir / name)
    options = subset.Options()
    options.layout_features = []
    subsetter = subset.Subsetter(options)
    subsetter.populate(text="AB.")
    subsetter.subset(font)
    return font


@pytest.fixture
def ttf(fonts_dir: Path) -> TTFont:
    return subset_font(fonts_dir, "IBMPlexSans-Regular.ttf")


@pytest.fixture
def otf(fonts_dir: Path) -> TTFont:
    return subset_font(fonts_dir, "IBMPlexSans-Regular.otf")


def test_simplify_path_merges_overlaps() -> None:
    simplified = simplify_path(overlapping_path(), "overlap", clockwise=True)

    assert len(list(simplified.contours)) == 1


def test_simplify_path_retries_with_unrounded_path_then_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fail(path: pathops.Path, **kwargs: Any) -> pathops.Path:
        calls.append(path)
        raise pathops.PathOpsError("boom")

    monkeypatch.setattr(contours_module.pathops, "simplify", fail)

    with pytest.raises(CorrectContoursError, match="'bad'"):
        simplify_path(overlapping_path(), "bad", clockwise=True)
    assert len(calls) == 2


def test_simplify_path_recovers_on_second_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    real_simplify = pathops.simplify
    attempts = []

    def flaky(path: pathops.Path, **kwargs: Any) -> pathops.Path:
        attempts.append(path)
        if len(attempts) == 1:
            raise pathops.PathOpsError("first")
        return real_simplify(path, **kwargs)

    monkeypatch.setattr(contours_module.pathops, "simplify", flaky)

    assert len(list(simplify_path(overlapping_path(), "ok", clockwise=True).contours)) == 1


def test_path_helpers_round_compare_and_drop_tiny_contours() -> None:
    path = pathops.Path()
    pen = path.getPen()
    square(pen, 0, 0, 100)
    square(pen, 500, 500, 2)

    cleaned = contours_module._remove_tiny_paths(path, min_area=25)
    assert len(list(cleaned.contours)) == 1
    assert not contours_module._same_path(path, cleaned)
    assert contours_module._same_path(cleaned, cleaned)

    fractional = pathops.Path()
    fractional.moveTo(0.4, 0.6)
    fractional.lineTo(10.5, 0.4)
    fractional.lineTo(10.4, 10.6)
    fractional.close()
    rounded = contours_module._round_path(fractional)
    assert list(rounded)[0][1] == ((0, 1),)


def test_correct_glyf_contours_removes_overlaps_and_composite_overlaps(ttf: TTFont) -> None:
    glyf = ttf["glyf"]
    pen = TTGlyphPen(None)
    square(pen, 0, 0)
    square(pen, 100, 100)
    glyf["period"] = pen.glyph()

    composite_pen = TTGlyphPen(ttf.getGlyphSet())
    composite_pen.addComponent("period", (1, 0, 0, 1, 0, 0))
    composite_pen.addComponent("period", (1, 0, 0, 1, 50, 0))
    glyf["A"] = composite_pen.glyph()

    modified = correct_glyf_contours(ttf, remove_hinting=True, ignore_errors=False)

    assert "period" in modified
    assert glyf["period"].numberOfContours == 1
    assert "A" in modified
    assert not glyf["A"].isComposite()


def test_correct_glyf_contours_ignores_or_raises_errors(
    ttf: TTFont, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(**kwargs: Any) -> bool:
        raise CorrectContoursError("bad glyph")

    monkeypatch.setattr(contours_module, "_correct_tt_glyph_contours", fail)

    assert correct_glyf_contours(ttf, remove_hinting=False, ignore_errors=True) == set()
    with pytest.raises(CorrectContoursError, match="bad glyph"):
        correct_glyf_contours(ttf, remove_hinting=False, ignore_errors=False)


def test_correct_cff_contours_removes_overlaps(otf: TTFont) -> None:
    cff = otf["CFF "].cff
    charstrings = cff[0].CharStrings
    old = charstrings["period"]
    pen = T2CharStringPen(otf.getGlyphSet()["period"].width, None)
    square(pen, 0, 0)
    square(pen, 100, 100)
    new = pen.getCharString(old.private, old.globalSubrs)
    charstrings["period"] = new

    modified = correct_cff_contours(otf, remove_hinting=True, ignore_errors=False)

    assert "period" in modified


def test_correct_cff_contours_returns_empty_when_nothing_changes(otf: TTFont) -> None:
    modified = correct_cff_contours(otf, remove_hinting=True, ignore_errors=False, min_area=0)
    assert modified == set() or "period" not in modified


def test_correct_cff_contours_wraps_errors(otf: TTFont, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> pathops.Path:
        raise RuntimeError("boom")

    monkeypatch.setattr(contours_module, "simplify_path", fail)

    assert correct_cff_contours(otf, remove_hinting=False, ignore_errors=True) == set()
    with pytest.raises(CorrectContoursError, match="Failed to correct contours"):
        correct_cff_contours(otf, remove_hinting=False, ignore_errors=False)


def test_ttf_composite_overlap_requires_composite_glyph(ttf: TTFont) -> None:
    glyph = ttf["glyf"]["period"]
    with pytest.raises(ValueError, match="composite"):
        contours_module._ttf_components_overlap(glyph, ttf.getGlyphSet())


def test_quadratics_to_cubics_converts_every_glyph(ttf: TTFont) -> None:
    charstrings = quadratics_to_cubics(ttf, tolerance=1.0)

    assert set(charstrings) == set(ttf.getGlyphOrder())
    assert all(charstring.program for charstring in charstrings.values())


def test_quadratics_to_cubics_merges_only_when_optimizing(
    ttf: TTFont, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    monkeypatch.setattr(
        "fontvertx.qu2cu.merge_cubic_segments",
        lambda path, **kwargs: calls.append(kwargs) or path,
    )

    quadratics_to_cubics(ttf, tolerance=1.0)
    assert not calls

    quadratics_to_cubics(ttf, tolerance=2.0, simplify=3)
    assert calls
    assert calls[0] == {"tolerance": 6.0, "min_extremum_distance": 2.0}


class _OncurveLessGlyph:
    """A glyph whose only contour is made of off-curve points (TrueType convention)."""

    width = 500

    def draw(self, pen: Any) -> None:
        pen.qCurveTo((100, 0), (200, 100), (100, 200), (0, 100), None)
        pen.closePath()


class _FakeFont:
    def getGlyphSet(self) -> dict[str, Any]:
        return {"circle": _OncurveLessGlyph()}


def test_quadratics_to_cubics_handles_oncurve_less_contours(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="fontvertx.qu2cu"):
        charstrings = quadratics_to_cubics(_FakeFont(), tolerance=1.0)  # type: ignore[arg-type]

    program = charstrings["circle"].program
    assert any(isinstance(op, str) and op.endswith("curveto") for op in program)
    assert "Glyphs with oncurve-less contours: circle" in caplog.text


def test_quadratics_to_cubics_decomposes_composite_glyphs(fonts_dir: Path) -> None:
    ttf = TTFont(fonts_dir / "IBMPlexSans-Regular.ttf")
    composites = [name for name in ttf.getGlyphOrder() if ttf["glyf"][name].isComposite()]
    assert composites

    charstrings = quadratics_to_cubics(ttf, tolerance=1.0)

    for name in composites:
        assert any(
            isinstance(op, str) and op.endswith(("lineto", "curveto"))
            for op in charstrings[name].program
        ), f"composite glyph {name} produced an empty charstring"
