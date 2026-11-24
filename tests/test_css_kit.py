from pathlib import Path

from fontvertx.css_kit import WebFontEntry, build_css, write_css_kits


def entry(folder: Path, name: str, **kwargs: object) -> WebFontEntry:
    values: dict[str, object] = {"format": "woff2", "family": "Demo"}
    values.update(kwargs)
    return WebFontEntry(folder / name, **values)  # type: ignore[arg-type]


def test_build_css_has_font_faces_family_and_feature_classes(tmp_path: Path) -> None:
    css = build_css(
        [
            entry(tmp_path, "a.woff2", features=("liga", "ss01")),
            entry(tmp_path, "b.woff2", weight=700, italic=True, features=("kern", "liga")),
        ]
    )

    assert css.count("@font-face") == 2
    assert 'src: url("b.woff2") format("woff2");' in css
    assert "font-weight: 700;" in css
    assert "font-style: italic;" in css
    assert '.family-demo { font-family: "Demo", sans-serif; }' in css
    assert css.count(".ft-liga ") == 1
    assert '.ft-ss01 { font-feature-settings: "ss01" 1; }' in css
    assert '.ft-kern { font-feature-settings: "kern" 1; }' in css


def test_build_css_merges_formats_of_the_same_font_into_one_rule(tmp_path: Path) -> None:
    css = build_css(
        [
            entry(tmp_path, "a.woff", format="woff"),
            entry(tmp_path, "a.woff2", format="woff2"),
        ]
    )

    assert css.count("@font-face") == 1
    assert css.index('format("woff2")') < css.index('format("woff")')
    assert 'url("a.woff2") format("woff2"),\n       url("a.woff") format("woff");' in css


def test_build_css_percent_encodes_reserved_characters_in_urls(tmp_path: Path) -> None:
    css = build_css([entry(tmp_path, "a#1.woff2")])

    assert 'url("a%231.woff2")' in css
    assert 'url("a#1.woff2")' not in css


def test_write_css_kits_writes_one_file_per_folder(tmp_path: Path) -> None:
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()

    written = write_css_kits(
        [entry(first, "a.woff2"), entry(first, "b.woff"), entry(second, "c.woff2")]
    )

    assert sorted(written) == [first / "fonts.css", second / "fonts.css"]
    assert (first / "fonts.css").read_text(encoding="utf-8").count("@font-face") == 2


def test_write_css_kits_keeps_existing_file_without_overwrite(tmp_path: Path) -> None:
    (tmp_path / "fonts.css").write_text("old", encoding="utf-8")

    (written,) = write_css_kits([entry(tmp_path, "a.woff2")], overwrite=False)

    assert written.name == "fonts#1.css"
    assert (tmp_path / "fonts.css").read_text(encoding="utf-8") == "old"
