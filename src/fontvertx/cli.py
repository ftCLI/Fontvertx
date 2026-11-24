"""Command-line interface for converting fonts."""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import click

from fontvertx import __version__
from fontvertx.constants import MAX_UPM, MIN_UPM
from fontvertx.finder import iter_files
from fontvertx.inspection import inspect_font
from fontvertx.logging_setup import setup_logging
from fontvertx.models import (
    ConversionProgress,
    ConversionRequest,
    ConversionResult,
    ConversionSettings,
    FontOutcome,
    FontOutcomeKind,
    InstanceSpec,
    OtfToTtfOptions,
    SfntToWebOptions,
    TtcToSfntOptions,
    TtfToOtfOptions,
    VarToStaticOptions,
    Woff2ToSfntOptions,
    WoffToSfntOptions,
)
from fontvertx.service import ConverterService

GENERAL_PANEL = "General options"
TTF_TO_OTF_PANEL = "TTF to OTF options"
OTF_TO_TTF_PANEL = "OTF to TTF options"
SFNT_TO_WEB_PANEL = "TTF/OTF to WOFF options"
VAR_TO_STATIC_PANEL = "Variable to static options"

_F = TypeVar("_F", bound=Callable[..., Any])


class GroupedOption(click.Option):
    """An option rendered under a named section in the command help."""

    def __init__(self, *args: Any, group: str | None = None, **kwargs: Any) -> None:
        self.group = group
        super().__init__(*args, **kwargs)


class _CliProgress:
    """In-place progress line rewritten with ``\\r`` on stderr.

    Any other stderr output (log messages, outcomes, logging records) must
    close the pending line first, or it would be glued to the progress text.
    """

    def __init__(self) -> None:
        self.pending = False

    def update(self, progress: ConversionProgress) -> None:
        click.echo(f"\rProgress: {progress.done}/{progress.total}", err=True, nl=False)
        self.pending = True

    def finish_line(self) -> None:
        if self.pending:
            click.echo(err=True)
            self.pending = False

    def message(self, text: str) -> None:
        self.finish_line()
        click.echo(text, err=True)


_progress = _CliProgress()


def grouped_option(*param_decls: str, group: str, **kwargs: Any) -> Callable[[_F], _F]:
    """Like ``click.option``, but the option is shown under the ``group`` help panel."""
    return click.option(*param_decls, cls=GroupedOption, group=group, **kwargs)


class GroupedCommand(click.Command):
    """Command whose options are grouped under named help panels."""

    def format_arguments(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        # Same rendering as the base class, under a shorter section title.
        arguments = [
            record
            for param in self.params
            if isinstance(param, click.Argument) and (record := param.get_help_record(ctx))
        ]
        if arguments:
            with formatter.section("Arguments"):
                formatter.write_dl(arguments)

    def format_options(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        groups: dict[str, list[click.Option]] = {}
        for param in self.params:
            if isinstance(param, click.Option):
                groups.setdefault(getattr(param, "group", None) or "Options", []).append(param)
        help_option = self.get_help_option(ctx)
        if help_option is not None:
            groups.setdefault("Options", []).append(help_option)
        for title, options in groups.items():
            records = [record for param in options if (record := param.get_help_record(ctx))]
            if records:
                with formatter.section(title):
                    formatter.write_dl(records)


def _general_options(func: _F) -> _F:
    """Attach the options shared by every profile (applied in reverse display order)."""
    for option in (
        grouped_option(
            "--reorder-tables/--no-reorder-tables",
            default=True,
            show_default=True,
            help="Reorder tables when saving fonts.",
            group=GENERAL_PANEL,
        ),
        grouped_option(
            "--recalc-timestamp/--no-recalc-timestamp",
            default=False,
            show_default=True,
            help="Set a fresh modified timestamp on output fonts.",
            group=GENERAL_PANEL,
        ),
        grouped_option(
            "--recalc-bboxes/--no-recalc-bboxes",
            default=True,
            show_default=True,
            help="Recalculate glyph bounding boxes.",
            group=GENERAL_PANEL,
        ),
        grouped_option(
            "--overwrite/--no-overwrite",
            default=False,
            show_default=True,
            help="Replace existing output files (default: keep existing files with "
            "numbered copies).",
            group=GENERAL_PANEL,
        ),
        grouped_option(
            "--recursive/--no-recursive",
            default=False,
            show_default=True,
            help="Scan input folders recursively.",
            group=GENERAL_PANEL,
        ),
        grouped_option(
            "--output-dir",
            type=click.Path(path_type=Path, file_okay=False),
            default=None,
            help="Folder for converted files (defaults to each input folder).",
            group=GENERAL_PANEL,
        ),
    ):
        func = option(func)
    return func


_inputs_argument = click.argument(
    "inputs",
    nargs=-1,
    required=True,
    type=click.Path(path_type=Path),
    metavar="INPUTS...",
    help="Input font files or folders. Folder scans are non-recursive by default.",
)

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


@click.group(
    no_args_is_help=True,
    context_settings=CONTEXT_SETTINGS,
    help="Convert font files from the command line.",
)
@click.version_option(
    __version__, "-V", "--version", prog_name="Fontvertx", message="%(prog)s %(version)s"
)
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default="WARNING",
    show_default=True,
    help="Console log level. The log file always records everything.",
)
def app(log_level: str) -> None:
    """Convert font files from the command line."""
    log_file = setup_logging(console_level=log_level.upper(), before_write=_progress.finish_line)
    logging.getLogger(__name__).debug("Log file: %s", log_file or "unavailable")


def _input_files(inputs: tuple[Path, ...], recursive: bool) -> list[Path]:
    files: dict[Path, None] = {}
    for path in iter_files(inputs, recursive):
        files[path.resolve()] = None
    return list(files)


def _named_instances(
    inputs: tuple[Path, ...], recursive: bool
) -> tuple[tuple[tuple[Path, tuple[InstanceSpec, ...]], ...], frozenset[Path]]:
    selected: list[tuple[Path, tuple[InstanceSpec, ...]]] = []
    default_paths: set[Path] = set()
    for path in _input_files(inputs, recursive):
        info = inspect_font(path)
        if info is None or not info.variable or info.collection:
            continue
        specs = tuple(
            InstanceSpec(instance.coordinates, instance.name) for instance in info.instances
        )
        if specs:
            selected.append((path, specs))
        else:
            selected.append((path, (InstanceSpec(()),)))
            default_paths.add(path)
            click.echo(
                f"Warning: {path.name} has no named instances; exporting its default instance.",
                err=True,
            )
    return tuple(selected), frozenset(default_paths)


def _report_outcome(outcome: FontOutcome, default_paths: frozenset[Path]) -> None:
    if outcome.kind is FontOutcomeKind.CONVERTED:
        for output in outcome.output_paths:
            click.echo(f"Converted: {outcome.input_path} -> {output}", err=True)
    elif outcome.kind is FontOutcomeKind.SKIPPED:
        reason = f": {outcome.error}" if outcome.error else ""
        click.echo(f"Skipped: {outcome.input_path}{reason}", err=True)
    elif outcome.kind is FontOutcomeKind.FAILED:
        click.echo(f"Failed: {outcome.input_path}: {outcome.error}", err=True)
        if outcome.input_path.resolve() in default_paths:
            click.echo(
                "The default instance could not be exported; continuing with the next font.",
                err=True,
            )


def _run(
    conversion: str,
    inputs: tuple[Path, ...],
    output_dir: Path | None,
    recursive: bool,
    overwrite: bool,
    recalc_bboxes: bool,
    recalc_timestamp: bool,
    reorder_tables: bool,
    settings_type: type[ConversionSettings],
    **profile_options: Any,
) -> None:
    input_paths = tuple(path.resolve() for path in inputs)
    if output_dir is not None:
        output_dir = output_dir.resolve()
    common: dict[str, Any] = {
        "output_dir": output_dir,
        "recursive": recursive,
        "overwrite": overwrite,
        "recalc_bboxes": recalc_bboxes,
        "recalc_timestamp": recalc_timestamp,
        "reorder_tables": reorder_tables,
    }
    default_paths: frozenset[Path] = frozenset()
    if conversion == "var2static":
        instances, default_paths = _named_instances(input_paths, recursive)
        profile_options["instances"] = instances

    settings = settings_type(**common, **profile_options)
    request = ConversionRequest(input_paths, settings)

    def report_outcome(outcome: FontOutcome) -> None:
        _progress.finish_line()
        _report_outcome(outcome, default_paths)

    click.echo(f"Starting {conversion} conversion for {len(input_paths)} input(s).", err=True)
    try:
        result: ConversionResult = ConverterService().convert(
            request,
            on_log=_progress.message,
            on_outcome=report_outcome,
            on_progress=_progress.update,
        )
    except Exception as error:
        _progress.finish_line()
        click.echo(f"Error: {error}", err=True)
        raise click.exceptions.Exit(code=1) from None
    _progress.finish_line()
    if result.error:
        click.echo(f"Error: {result.error}", err=True)
    click.echo(
        f"Summary: {result.converted_count} converted, {result.skipped_count} skipped, "
        f"{result.failed_count} failed.",
    )
    if not result.ok:
        raise click.exceptions.Exit(code=1)


@app.command("ttf2otf", cls=GroupedCommand)
@_inputs_argument
@grouped_option(
    "--tolerance",
    type=click.FloatRange(0.1, 3),
    default=1.0,
    show_default=True,
    help="Curve-conversion tolerance (minimum 0.1).",
    group=TTF_TO_OTF_PANEL,
)
@grouped_option(
    "--simplify",
    type=click.IntRange(0, 3),
    default=0,
    show_default=True,
    help="Contour simplification level (0 disables it).",
    group=TTF_TO_OTF_PANEL,
)
@grouped_option(
    "--target-upm",
    type=click.IntRange(MIN_UPM, MAX_UPM),
    default=None,
    help="Scale output fonts to this units-per-em value.",
    group=TTF_TO_OTF_PANEL,
)
@grouped_option(
    "--subroutinize/--no-subroutinize",
    default=True,
    show_default=True,
    help="Subroutinize CFF outlines.",
    group=TTF_TO_OTF_PANEL,
)
@_general_options
def ttf2otf(
    inputs: tuple[Path, ...],
    tolerance: float,
    simplify: int,
    target_upm: int | None,
    subroutinize: bool,
    output_dir: Path | None,
    recursive: bool,
    overwrite: bool,
    recalc_bboxes: bool,
    recalc_timestamp: bool,
    reorder_tables: bool,
) -> None:
    """Convert static TrueType outlines to PostScript outlines (TTF to OTF)."""
    _run(
        "ttf2otf",
        inputs,
        output_dir,
        recursive,
        overwrite,
        recalc_bboxes,
        recalc_timestamp,
        reorder_tables,
        TtfToOtfOptions,
        tolerance=tolerance,
        simplify=simplify,
        target_upm=target_upm,
        subroutinize=subroutinize,
    )


@app.command("otf2ttf", cls=GroupedCommand)
@_inputs_argument
@grouped_option(
    "--tolerance",
    type=click.FloatRange(0, 3),
    default=1.0,
    show_default=True,
    help="Curve-conversion tolerance.",
    group=OTF_TO_TTF_PANEL,
)
@grouped_option(
    "--target-upm",
    type=click.IntRange(MIN_UPM, MAX_UPM),
    default=None,
    help="Scale output fonts to this units-per-em value.",
    group=OTF_TO_TTF_PANEL,
)
@grouped_option(
    "--autohint/--no-autohint",
    default=True,
    show_default=True,
    help="Add TrueType hinting instructions.",
    group=OTF_TO_TTF_PANEL,
)
@_general_options
def otf2ttf(
    inputs: tuple[Path, ...],
    tolerance: float,
    target_upm: int | None,
    autohint: bool,
    output_dir: Path | None,
    recursive: bool,
    overwrite: bool,
    recalc_bboxes: bool,
    recalc_timestamp: bool,
    reorder_tables: bool,
) -> None:
    """Convert static PostScript outlines to TrueType outlines (OTF to TTF)."""
    _run(
        "otf2ttf",
        inputs,
        output_dir,
        recursive,
        overwrite,
        recalc_bboxes,
        recalc_timestamp,
        reorder_tables,
        OtfToTtfOptions,
        tolerance=tolerance,
        target_upm=target_upm,
        autohint=autohint,
    )


@app.command("ft2wf", cls=GroupedCommand)
@_inputs_argument
@grouped_option(
    "--woff/--no-woff",
    default=True,
    show_default=True,
    help="Create WOFF output.",
    group=SFNT_TO_WEB_PANEL,
)
@grouped_option(
    "--woff2/--no-woff2",
    default=True,
    show_default=True,
    help="Create WOFF2 output.",
    group=SFNT_TO_WEB_PANEL,
)
@grouped_option(
    "--obfuscate-names/--no-obfuscate-names",
    default=False,
    show_default=True,
    help="Replace identifying font names with hashes.",
    group=SFNT_TO_WEB_PANEL,
)
@grouped_option(
    "--remove-unused-glyphs/--no-remove-unused-glyphs",
    default=False,
    show_default=True,
    help="Remove glyphs unused by the cmap and OpenType features.",
    group=SFNT_TO_WEB_PANEL,
)
@grouped_option(
    "--remove-non-windows-names/--no-remove-non-windows-names",
    default=False,
    show_default=True,
    help="Remove name records whose platform ID is not Windows.",
    group=SFNT_TO_WEB_PANEL,
)
@grouped_option(
    "--remove-dsig/--no-remove-dsig",
    default=False,
    show_default=True,
    help="Remove the DSIG table from WOFF output.",
    group=SFNT_TO_WEB_PANEL,
)
@grouped_option(
    "--css-kit/--no-css-kit",
    default=False,
    show_default=True,
    help="Generate fonts.css.",
    group=SFNT_TO_WEB_PANEL,
)
@_general_options
def ft2wf(
    inputs: tuple[Path, ...],
    woff: bool,
    woff2: bool,
    obfuscate_names: bool,
    remove_unused_glyphs: bool,
    remove_non_windows_names: bool,
    remove_dsig: bool,
    css_kit: bool,
    output_dir: Path | None,
    recursive: bool,
    overwrite: bool,
    recalc_bboxes: bool,
    recalc_timestamp: bool,
    reorder_tables: bool,
) -> None:
    """Convert TTF or OTF fonts to WOFF and/or WOFF2."""
    if not woff and not woff2:
        raise click.BadParameter("Select at least one output format with --woff or --woff2.")
    _run(
        "ft2wf",
        inputs,
        output_dir,
        recursive,
        overwrite,
        recalc_bboxes,
        recalc_timestamp,
        reorder_tables,
        SfntToWebOptions,
        format="woff" if woff and not woff2 else "woff2" if woff2 and not woff else None,
        obfuscate_names=obfuscate_names,
        remove_unused_glyphs=remove_unused_glyphs,
        remove_non_windows_names=remove_non_windows_names,
        remove_dsig=remove_dsig,
        css_kit=css_kit,
    )


@app.command("woff2ft", cls=GroupedCommand)
@_inputs_argument
@_general_options
def woff2ft(
    inputs: tuple[Path, ...],
    output_dir: Path | None,
    recursive: bool,
    overwrite: bool,
    recalc_bboxes: bool,
    recalc_timestamp: bool,
    reorder_tables: bool,
) -> None:
    """Convert WOFF fonts back to TTF or OTF."""
    _run(
        "woff2ft",
        inputs,
        output_dir,
        recursive,
        overwrite,
        recalc_bboxes,
        recalc_timestamp,
        reorder_tables,
        WoffToSfntOptions,
    )


@app.command("woff22ft", cls=GroupedCommand)
@_inputs_argument
@_general_options
def woff22ft(
    inputs: tuple[Path, ...],
    output_dir: Path | None,
    recursive: bool,
    overwrite: bool,
    recalc_bboxes: bool,
    recalc_timestamp: bool,
    reorder_tables: bool,
) -> None:
    """Convert WOFF2 fonts back to TTF or OTF."""
    _run(
        "woff22ft",
        inputs,
        output_dir,
        recursive,
        overwrite,
        recalc_bboxes,
        recalc_timestamp,
        reorder_tables,
        Woff2ToSfntOptions,
    )


@app.command("ttc2sfnt", cls=GroupedCommand)
@_inputs_argument
@_general_options
def ttc2sfnt(
    inputs: tuple[Path, ...],
    output_dir: Path | None,
    recursive: bool,
    overwrite: bool,
    recalc_bboxes: bool,
    recalc_timestamp: bool,
    reorder_tables: bool,
) -> None:
    """Extract each font from TrueType Collections (TTC/OTC) as a separate TTF or OTF font."""
    _run(
        "ttc2sfnt",
        inputs,
        output_dir,
        recursive,
        overwrite,
        recalc_bboxes,
        recalc_timestamp,
        reorder_tables,
        TtcToSfntOptions,
    )


@app.command("var2static", cls=GroupedCommand)
@_inputs_argument
@grouped_option(
    "--target-upm",
    type=click.IntRange(MIN_UPM, MAX_UPM),
    default=None,
    help="Scale output fonts to this units-per-em value.",
    group=VAR_TO_STATIC_PANEL,
)
@grouped_option(
    "--autohint/--no-autohint",
    default=True,
    show_default=True,
    help="Autohint TrueType instances.",
    group=VAR_TO_STATIC_PANEL,
)
@grouped_option(
    "--subroutinize/--no-subroutinize",
    default=True,
    show_default=True,
    help="Subroutinize PostScript instances.",
    group=VAR_TO_STATIC_PANEL,
)
@_general_options
def var2static(
    inputs: tuple[Path, ...],
    target_upm: int | None,
    autohint: bool,
    subroutinize: bool,
    output_dir: Path | None,
    recursive: bool,
    overwrite: bool,
    recalc_bboxes: bool,
    recalc_timestamp: bool,
    reorder_tables: bool,
) -> None:
    """Export all named instances from variable fonts as static fonts."""
    _run(
        "var2static",
        inputs,
        output_dir,
        recursive,
        overwrite,
        recalc_bboxes,
        recalc_timestamp,
        reorder_tables,
        VarToStaticOptions,
        target_upm=target_upm,
        autohint=autohint,
        subroutinize=subroutinize,
    )


def main() -> None:
    """Run the font converter command-line application."""
    app()


if __name__ == "__main__":
    main()
