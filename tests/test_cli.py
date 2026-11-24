from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner
from fontTools.ttLib import TTFont

from fontvertx.cli import _named_instances, app
from fontvertx.models import InstanceSpec

runner = CliRunner()


def _option_names(profile: str) -> set[str]:
    command = app.commands[profile]
    return {option for param in command.params for option in (*param.opts, *param.secondary_opts)}


def test_cli_help_lists_conversion_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "ttf2otf" in result.output
    assert "var2static" in result.output


def test_cli_profile_help_lists_common_and_profile_options() -> None:
    result = runner.invoke(app, ["ft2wf", "--help"], color=False)

    assert result.exit_code == 0
    assert "General options" in result.output
    assert "TTF/OTF to WOFF options" in result.output
    assert {"--output-dir", "--recalc-bboxes", "--woff", "--css-kit"} <= _option_names("ft2wf")


@pytest.mark.parametrize(
    ("profile", "panel", "options"),
    [
        (
            "ttf2otf",
            "TTF to OTF options",
            (
                "--tolerance",
                "--simplify",
                "--target-upm",
                "--subroutinize",
            ),
        ),
        (
            "otf2ttf",
            "OTF to TTF options",
            ("--tolerance", "--target-upm", "--autohint"),
        ),
        (
            "ft2wf",
            "TTF/OTF to WOFF options",
            (
                "--woff",
                "--woff2",
                "--obfuscate-names",
                "--remove-unused-glyphs",
                "--remove-non-windows-names",
                "--remove-dsig",
                "--css-kit",
            ),
        ),
        ("woff2ft", "General options", ("--output-dir",)),
        ("woff22ft", "General options", ("--output-dir",)),
        ("ttc2sfnt", "General options", ("--output-dir",)),
        (
            "var2static",
            "Variable to static options",
            ("--target-upm", "--autohint", "--subroutinize"),
        ),
    ],
)
def test_cli_profile_help_lists_profile_options(
    profile: str, panel: str, options: tuple[str, ...]
) -> None:
    result = runner.invoke(app, [profile, "--help"], color=False)

    assert result.exit_code == 0
    assert "General options" in result.output
    assert panel in result.output
    assert "Profile options" not in result.output
    if panel != "General options":
        assert result.output.index(panel) < result.output.index("General options")
    assert set(options) <= _option_names(profile)
    command = app.commands[profile]
    if panel != "General options":
        profile_panel_options = [
            option
            for param in command.params
            if getattr(param, "group", None) == panel
            for option in (*param.opts, *param.secondary_opts)
        ]
        assert not any(
            len(option) == 2 and option.startswith("-") for option in profile_panel_options
        )


def test_ttf2otf_simplify_follows_tolerance() -> None:
    command = app.commands["ttf2otf"]
    option_order = [
        option
        for param in command.params
        for option in param.opts
        if option in {"--tolerance", "--simplify", "--target-upm"}
    ]

    assert option_order == ["--tolerance", "--simplify", "--target-upm"]
    assert "--optimize-contours" not in _option_names("ttf2otf")


@pytest.mark.parametrize(
    ("profile", "description"),
    [
        ("ft2wf", "Convert TTF or OTF fonts to WOFF and/or WOFF2."),
        ("woff2ft", "Convert WOFF fonts back to TTF or OTF."),
        ("woff22ft", "Convert WOFF2 fonts back to TTF or OTF."),
        (
            "ttc2sfnt",
            "Extract each font from TrueType Collections (TTC/OTC) as a separate TTF or OTF font.",
        ),
    ],
)
def test_cli_profile_help_describes_font_formats(profile: str, description: str) -> None:
    result = runner.invoke(app, [profile, "--help"], color=False)

    assert result.exit_code == 0
    assert description in " ".join(result.output.split())


def test_cli_sfnt_to_woff_respects_output_folder(ttf_path: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    result = runner.invoke(
        app,
        ["ft2wf", str(ttf_path), "--output-dir", str(output_dir), "--no-woff2"],
    )

    assert result.exit_code == 0, result.output
    assert (output_dir / "test.woff").is_file()
    assert "1 converted" in result.output


@pytest.mark.parametrize(
    "profile", ["ttf2otf", "otf2ttf", "ft2wf", "woff2ft", "woff22ft", "ttc2sfnt", "var2static"]
)
def test_cli_overwrite_is_opt_in_for_every_profile(profile: str) -> None:
    command = app.commands[profile]
    option = next(param for param in command.params if "--overwrite" in param.opts)
    assert option.default is False


def test_cli_preserves_outputs_by_default_and_overwrites_explicitly(
    ttf_path: Path, tmp_path: Path
) -> None:
    output_dir = tmp_path / "output"
    args = ["ft2wf", str(ttf_path), "--output-dir", str(output_dir), "--no-woff2"]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    original = output_dir / "test.woff"
    first_bytes = original.read_bytes()
    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.output
    assert original.read_bytes() == first_bytes
    assert (output_dir / "test#1.woff").is_file()
    original.write_bytes(b"existing output")
    explicit = runner.invoke(app, [*args, "--overwrite"])
    assert explicit.exit_code == 0, explicit.output
    assert original.read_bytes() != b"existing output"
    assert not (output_dir / "test#2.woff").exists()


def test_cli_general_options_have_no_short_aliases() -> None:
    command = app.commands["ft2wf"]

    assert not any(
        len(option) == 2 and option.startswith("-")
        for param in command.params
        for option in (*param.opts, *param.secondary_opts)
    )


def test_cli_requires_at_least_one_web_format(ttf_path: Path) -> None:
    result = runner.invoke(app, ["ft2wf", str(ttf_path), "--no-woff", "--no-woff2"])

    assert result.exit_code == 2
    assert "Select at least one output format" in result.output


def test_ttf_to_otf_rejects_zero_tolerance(ttf_path: Path) -> None:
    result = runner.invoke(app, ["ttf2otf", str(ttf_path), "--tolerance", "0"])

    assert result.exit_code == 2
    assert "0.1<=x<=3" in result.output


def test_cli_explains_incompatible_files(fonts_dir: Path) -> None:
    result = runner.invoke(app, ["ttf2otf", str(fonts_dir / "TestVF.ttf")])

    assert result.exit_code == 1, result.output
    # The README promises that incompatible fonts are explained, not silently skipped.
    assert "Skipped:" in result.output
    assert "TestVF.ttf" in result.output
    assert "1 skipped" in result.output


def test_cli_log_level_option(ttf_path: Path) -> None:
    result = runner.invoke(app, ["--log-level", "DEBUG", "ttf2otf", str(ttf_path)])

    assert result.exit_code == 0, result.output
    assert "Log file:" in result.output
    assert "Converting" in result.output


def test_cli_rejects_unknown_log_level(ttf_path: Path) -> None:
    result = runner.invoke(app, ["--log-level", "CHATTERBOX", "ttf2otf", str(ttf_path)])

    assert result.exit_code == 2
    assert "Invalid value for '--log-level'" in result.output


def test_progress_lines_are_not_glued_to_messages(fonts_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["ttf2otf", str(fonts_dir), "--output-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    progress_lines = [line for line in result.output.splitlines() if "Progress:" in line]
    assert progress_lines
    assert all(re.fullmatch(r"\s*Progress: \d+/\d+", line) for line in progress_lines)


def test_var2static_uses_default_and_warns_without_named_instances(
    fonts_dir: Path, tmp_path: Path
) -> None:
    variable_path = tmp_path / "no-named-instances.ttf"
    shutil.copy(fonts_dir / "TestVF.ttf", variable_path)
    with TTFont(variable_path) as font:
        font["fvar"].instances.clear()
        font.save(variable_path)

    output_dir = tmp_path / "output"
    result = runner.invoke(
        app,
        ["var2static", str(variable_path), "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0, result.output
    assert "has no named instances; exporting its default instance" in result.output
    assert len(list(output_dir.glob("*.ttf"))) == 1


def test_named_instance_discovery_selects_each_instance(fonts_dir: Path, tmp_path: Path) -> None:
    variable_path = tmp_path / "variable.ttf"
    shutil.copy(fonts_dir / "TestVF.ttf", variable_path)

    selections, defaults = _named_instances((variable_path,), recursive=False)

    with TTFont(variable_path) as font:
        expected_count = len(font["fvar"].instances)
    assert variable_path.resolve() not in defaults
    assert selections
    assert all(spec.name for spec in selections[0][1])
    assert len(selections[0][1]) == expected_count


def test_named_instance_discovery_uses_default_if_none_are_named(
    fonts_dir: Path, tmp_path: Path
) -> None:
    variable_path = tmp_path / "no-named-instances.ttf"
    shutil.copy(fonts_dir / "TestVF.ttf", variable_path)
    with TTFont(variable_path) as font:
        font["fvar"].instances.clear()
        font.save(variable_path)

    selections, defaults = _named_instances((variable_path,), recursive=False)

    assert defaults == {variable_path.resolve()}
    assert selections == ((variable_path.resolve(), (InstanceSpec(()),)),)
