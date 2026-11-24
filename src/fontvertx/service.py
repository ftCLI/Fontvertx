"""Interface-independent orchestration of font conversions."""

import logging
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import TypeVar

from fontTools.misc.cliTools import makeOutputFileName
from fontTools.ttLib import TTFont, TTLibError
from fontTools.ttLib.ttCollection import TTCollection
from pathvalidate import sanitize_filename

from fontvertx import Font
from fontvertx import constants as const
from fontvertx.constants import WOFF2_FLAVOR, WOFF_FLAVOR
from fontvertx.css_kit import WebFontEntry, write_css_kits
from fontvertx.finder import iter_files
from fontvertx.inspection import incompatibility, inspect_font
from fontvertx.logging_setup import FontAdapter, font_logger
from fontvertx.models import (
    _CONVERSION_BY_SETTINGS,
    CancellationCheck,
    ConversionOptions,
    ConversionProgress,
    ConversionRequest,
    ConversionResult,
    ConversionSettings,
    FontOutcome,
    FontOutcomeKind,
    FontStartCallback,
    InstanceSpec,
    LogCallback,
    OtfToTtfOptions,
    OutcomeCallback,
    PauseWait,
    ProgressCallback,
    SfntToWebOptions,
    TtfToOtfOptions,
    VarToStaticOptions,
    WebToSfntOptions,
)

logger = logging.getLogger(__name__)


def _format_organization_number(value: float) -> str:
    return f"{value:g}"


def organization_level_name(criteria: tuple[str, ...], values: dict[str, str]) -> str:
    """Build a safe directory name from the selected organization criteria."""
    parts = []
    for criterion in criteria:
        if criterion not in values:
            raise ValueError(f"Organization criterion is not available: {criterion}")
        value = values[criterion]
        if criterion in ("upm", "tolerance", "simplify"):
            value = f"{criterion}_{value}"
        parts.append(value)
    if not parts:
        raise ValueError("Organization levels must contain at least one criterion.")
    return sanitize_filename("_".join(parts)).strip() or "Unknown"


def build_output_file_name(font: Font, output_dir: Path | None, overwrite: bool = True) -> Path:
    """Build the output name for a TrueType-to-PostScript conversion."""
    flavor = font.ttfont.flavor
    extension = font.get_file_ext() if flavor is not None else ".otf"
    return font.get_file_path(output_dir=output_dir, overwrite=overwrite, extension=extension)


_S = TypeVar("_S")


def instance_label(coordinates: tuple[tuple[str, float], ...]) -> str:
    """Describe an instance location from its axis values, e.g. ``opsz11 wght450``."""
    return " ".join(f"{tag}{value:g}" for tag, value in coordinates)


def instance_stem(input_path: Path, name: str | None, label: str) -> str:
    """File name (without extension) of an instance: named ones use the name, others the label."""
    suffix = re.sub(r"\s+", "", name) if name else label.replace(" ", "-")
    base_stem = re.sub(r"\[.*?\]", "", input_path.stem)
    return f"{base_stem}-{sanitize_filename(suffix)}"


def _expect_settings(settings: object, kind: type[_S]) -> _S:
    """Return settings as the expected type, or raise if the request is inconsistent."""
    if not isinstance(settings, kind):
        raise TypeError(f"Expected {kind.__name__}, got {type(settings).__name__}")
    return settings


class ConverterService:
    """Run font conversions without depending on Qt, Click, or CLI output."""

    def convert(
        self,
        request: ConversionRequest,
        on_progress: ProgressCallback | None = None,
        on_outcome: OutcomeCallback | None = None,
        on_log: LogCallback | None = None,
        should_cancel: CancellationCheck | None = None,
        on_font_start: FontStartCallback | None = None,
        wait_if_paused: PauseWait | None = None,
    ) -> ConversionResult:
        def stop_requested() -> bool:
            if wait_if_paused is not None:
                wait_if_paused()
            return should_cancel is not None and should_cancel()

        if not request.input_paths:
            logger.warning("Conversion requested without any input path")
            return ConversionResult(error="Select at least one input file or folder.")

        logger.info(
            "Starting %s conversion on %d input path(s)",
            request.conversion,
            len(request.input_paths),
        )
        try:
            if request.settings.output_dir is not None:
                request.settings.output_dir.mkdir(parents=True, exist_ok=True)
            candidates = self._find_candidates(request)
        except (OSError, ValueError, TTLibError) as error:
            logger.exception("Could not scan the input paths")
            return ConversionResult(error=f"{type(error).__name__}: {error}")
        if not candidates:
            logger.warning("No compatible fonts found in the selected inputs")
            return ConversionResult(error="No compatible fonts found in the selected inputs.")

        outcomes: list[FontOutcome] = []
        web_entries: list[WebFontEntry] = []
        has_compatible_fonts = any(compatible for _, _, compatible in candidates)
        logger.info(
            "Found %d candidate font(s), %d compatible",
            len(candidates),
            sum(1 for _, _, compatible in candidates if compatible),
        )
        progress = ConversionProgress(0, sum(weight for _, weight, _ in candidates))
        if on_progress is not None:
            on_progress(progress)

        for input_path, weight, compatible in candidates:
            log = font_logger(logger, input_path.name)
            if stop_requested():
                logger.info("Conversion cancelled before %s", input_path.name)
                self._write_css_kit(web_entries, request.settings, on_log)
                return ConversionResult(tuple(outcomes), cancelled=True)
            if not compatible:
                log.info("Skipped: incompatible with the %s conversion", request.conversion)
                outcome = FontOutcome(input_path, FontOutcomeKind.SKIPPED)
                outcomes.append(outcome)
                self._report(outcome, on_outcome)
                progress = ConversionProgress(progress.done + weight, progress.total)
                if on_progress is not None:
                    on_progress(progress)
                continue
            if request.conversion == "ttc2sfnt":
                try:
                    collection = TTCollection(input_path)
                except (OSError, TTLibError) as error:
                    log.exception("Could not open the font collection")
                    return ConversionResult(
                        tuple(outcomes), error=f"{type(error).__name__}: {error}"
                    )
                try:
                    members = collection.fonts
                    for index, member in enumerate(members):
                        if stop_requested():
                            logger.info("Conversion cancelled during %s", input_path.name)
                            return ConversionResult(tuple(outcomes), cancelled=True)
                        if on_font_start is not None:
                            on_font_start(input_path)
                        log.info("Extracting collection member %d/%d", index + 1, len(members))
                        outcome = self._extract_collection_member(
                            input_path, member, request.settings, log
                        )
                        outcomes.append(outcome)
                        self._report(outcome, on_outcome)
                        progress = ConversionProgress(progress.done + 1, progress.total)
                        if on_progress is not None:
                            on_progress(progress)
                finally:
                    collection.close()
                continue
            if request.conversion == "var2static":
                var_settings = _expect_settings(request.settings, VarToStaticOptions)
                used_stems: set[str] = set()
                for spec in self._instances_for(request.settings, input_path):
                    if stop_requested():
                        logger.info("Conversion cancelled during %s", input_path.name)
                        return ConversionResult(tuple(outcomes), cancelled=True)
                    if on_font_start is not None:
                        on_font_start(input_path)
                    outcome = self._convert_instance(
                        input_path, spec, var_settings, used_stems, on_log, log
                    )
                    outcomes.append(outcome)
                    self._report(outcome, on_outcome)
                    progress = ConversionProgress(progress.done + 1, progress.total)
                    if on_progress is not None:
                        on_progress(progress)
                continue

            # weight is 1 here: ttc2sfnt and var2static are handled above with continue.
            if stop_requested():
                logger.info("Conversion cancelled before %s", input_path.name)
                self._write_css_kit(web_entries, request.settings, on_log)
                return ConversionResult(tuple(outcomes), cancelled=True)
            if on_font_start is not None:
                on_font_start(input_path)
            log.info("Converting %s", input_path)
            started = time.perf_counter()
            try:
                font = Font(
                    input_path,
                    recalc_bboxes=request.settings.recalc_bboxes,
                    recalc_timestamp=request.settings.recalc_timestamp,
                )
                with font:
                    output_paths = self._convert_font(font, request.settings, on_log, web_entries)
                elapsed = time.perf_counter() - started
                log.info(
                    "Converted in %.1f s: %s",
                    elapsed,
                    ", ".join(path.name for path in output_paths),
                )
                outcome = FontOutcome(
                    input_path,
                    FontOutcomeKind.CONVERTED,
                    tuple(output_paths),
                    elapsed=elapsed,
                )
            except Exception as error:
                log.exception("Conversion failed")
                outcome = FontOutcome(
                    input_path,
                    FontOutcomeKind.FAILED,
                    error=f"{type(error).__name__}: {error}",
                    elapsed=time.perf_counter() - started,
                )
            outcomes.append(outcome)
            self._report(outcome, on_outcome)
            progress = ConversionProgress(progress.done + 1, progress.total)
            if on_progress is not None:
                on_progress(progress)

        self._write_css_kit(web_entries, request.settings, on_log)
        no_compatible_error = (
            None if has_compatible_fonts else "No compatible fonts found in the selected inputs."
        )
        result = ConversionResult(tuple(outcomes), error=no_compatible_error)
        logger.info(
            "Finished %s conversion: %d converted, %d skipped, %d failed",
            request.conversion,
            result.converted_count,
            result.skipped_count,
            result.failed_count,
        )
        return result

    @staticmethod
    def _write_css_kit(
        entries: list[WebFontEntry], settings: ConversionSettings, on_log: LogCallback | None
    ) -> None:
        if not entries or not isinstance(settings, SfntToWebOptions):
            return
        try:
            for path in write_css_kits(entries, overwrite=settings.overwrite):
                ConverterService._log(on_log, f"CSS saved to {path}")
        except OSError as error:
            logger.warning("Could not write the CSS kit: %s", error)
            ConverterService._log(on_log, f"Could not write the CSS: {error}")

    def _find_candidates(self, request: ConversionRequest) -> list[tuple[Path, int, bool]]:
        files: dict[Path, None] = {}
        for source in request.input_paths:
            if not source.exists():
                raise FileNotFoundError(f"Input path does not exist: {source}")
            for path in iter_files((source,), request.settings.recursive):
                files[path.resolve()] = None

        candidates: list[tuple[Path, int, bool]] = []
        for path in files:
            info = inspect_font(path)
            if info is None:
                continue
            if request.conversion == "ttc2sfnt":
                if info.collection:
                    candidates.append((path, info.num_fonts, True))
                continue
            compatible = incompatibility(info, request.conversion) is None
            weight = 1
            if compatible and request.conversion == "var2static":
                weight = len(self._instances_for(request.settings, path))
            candidates.append((path, weight, compatible))
        return candidates

    @staticmethod
    def _output_dir(
        font: Font,
        settings: ConversionOptions,
        flavor: str | None,
        is_tt: bool,
    ) -> Path | None:
        if not settings.organization_levels:
            return settings.output_dir
        base_dir = settings.output_dir or (font.file.parent if font.file is not None else None)
        if base_dir is None:
            raise ValueError("Cannot organize output without an output directory or input file.")
        output_dir = base_dir
        family = str(font.ttfont[const.T_NAME].getBestFamilyName() or "")
        format_name = {None: "opentype", "woff": "woff", "woff2": "woff2"}.get(flavor)
        if format_name is None:
            raise ValueError(f"Unsupported output font format: {flavor}")
        values = {
            "family": family or "Unknown family",
            "format": format_name,
            "outline": "tt" if is_tt else "ps",
            "upm": str(getattr(settings, "target_upm", None) or font.units_per_em),
        }
        if hasattr(settings, "tolerance"):
            values["tolerance"] = _format_organization_number(settings.tolerance)
        if hasattr(settings, "simplify"):
            values["simplify"] = str(settings.simplify)
        for level in settings.organization_levels:
            output_dir /= organization_level_name(level, values)
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _convert_font(
        self,
        font: Font,
        settings: ConversionSettings,
        on_log: LogCallback | None,
        web_entries: list[WebFontEntry] | None = None,
    ) -> list[Path]:
        conversion = _CONVERSION_BY_SETTINGS[type(settings)]
        if conversion == "ttf2otf":
            settings = _expect_settings(settings, TtfToOtfOptions)
            flavor = font.ttfont.flavor
            output_dir = self._output_dir(font, settings, flavor, is_tt=False)
            output = build_output_file_name(
                font,
                output_dir=output_dir,
                overwrite=settings.overwrite,
            )
            font.ttfont.flavor = None
            if settings.target_upm and font.units_per_em != settings.target_upm:
                self._log(on_log, f"Scaling UPM to {settings.target_upm}...")
                font.scale_upm(settings.target_upm)
            tolerance = settings.tolerance / 1000 * font.units_per_em
            self._log(on_log, "Converting to OTF...")
            font.to_otf(tolerance=tolerance, simplify=settings.simplify)
            if settings.subroutinize:
                self._log(on_log, "Subroutinizing...")
                font.subroutinize()
            font.ttfont.flavor = flavor
            font.save(output, reorder_tables=settings.reorder_tables)
            return [Path(output)]

        if conversion == "otf2ttf":
            settings = _expect_settings(settings, OtfToTtfOptions)
            flavor = font.ttfont.flavor
            output_dir = self._output_dir(font, settings, flavor, is_tt=True)
            extension = font.get_file_ext() if flavor is not None else ".ttf"
            output = font.get_file_path(
                output_dir=output_dir,
                overwrite=settings.overwrite,
                extension=extension,
            )
            tolerance = settings.tolerance / 1000 * font.units_per_em
            self._log(on_log, "Converting to TTF...")
            font.to_ttf(max_err=tolerance, reverse_direction=True)
            if settings.target_upm and font.units_per_em != settings.target_upm:
                self._log(on_log, f"Scaling UPM to {settings.target_upm}...")
                font.scale_upm(settings.target_upm)
            if settings.autohint:
                self._log(on_log, "Autohinting...")
                font.ttf_autohint()
            font.save(output, reorder_tables=settings.reorder_tables)
            return [Path(output)]

        if conversion in ("woff2ft", "woff22ft"):
            settings = _expect_settings(settings, WebToSfntOptions)
            output_dir = self._output_dir(font, settings, None, font.is_tt)
            output = font.get_file_path(
                output_dir=output_dir,
                overwrite=settings.overwrite,
                extension=".ttf" if font.is_tt else ".otf",
            )
            font.to_sfnt()
            font.save(output, reorder_tables=settings.reorder_tables)
            return [Path(output)]

        if conversion == "ft2wf":
            settings = _expect_settings(settings, SfntToWebOptions)
            formats = (settings.format,) if settings.format else (WOFF_FLAVOR, WOFF2_FLAVOR)
            if settings.remove_unused_glyphs:
                self._log(on_log, "Removing unused glyphs...")
                removed = font.remove_unused_glyphs()
                self._log(on_log, f"Removed {removed} unused glyphs")
            source_file = font.file
            family = ""
            if settings.obfuscate_names:
                self._log(on_log, "Obfuscating names...")
                family, ps_name = font.obfuscate_names()
                if source_file is not None:
                    source_file = source_file.with_name(ps_name)
            entry_data: tuple[str, int, bool, tuple[str, ...]] | None = None
            if settings.css_kit:
                family = family or str(font.ttfont[const.T_NAME].getBestFamilyName() or "")
                weight = int(getattr(font.ttfont.get(const.T_OS_2), "usWeightClass", 400))
                italic = bool(font.ttfont[const.T_HEAD].macStyle & const.MAC_STYLE_ITALIC)
                entry_data = (family, weight, italic, font.get_features())
            if settings.remove_non_windows_names:
                removed_names = font.remove_non_windows_names()
                self._log(on_log, f"Removed {removed_names} non-Windows name records")
            if settings.remove_dsig and font.remove_dsig():
                self._log(on_log, "Removed the DSIG table")
            outputs = []
            for format_ in formats:
                self._log(on_log, f"Converting to {format_.upper()}")
                if format_ == WOFF_FLAVOR:
                    font.to_woff()
                else:
                    font.to_woff2()
                output_dir = self._output_dir(font, settings, format_, font.is_tt)
                output = font.get_file_path(
                    file=source_file, output_dir=output_dir, overwrite=settings.overwrite
                )
                font.save(output, reorder_tables=settings.reorder_tables)
                outputs.append(Path(output))
                if entry_data is not None and web_entries is not None:
                    web_entries.append(WebFontEntry(Path(output), format_, *entry_data))
            return outputs
        raise ValueError(f"Unsupported conversion: {conversion}")

    @staticmethod
    def _instances_for(settings: ConversionSettings, path: Path) -> tuple[InstanceSpec, ...]:
        """Return the instances to export from a font; the default instance if none is given."""
        settings = _expect_settings(settings, VarToStaticOptions)
        for instance_path, specs in settings.instances:
            if instance_path.resolve() == path and specs:
                return specs
        return (InstanceSpec(()),)

    def _convert_instance(
        self,
        input_path: Path,
        spec: InstanceSpec,
        settings: VarToStaticOptions,
        used_stems: set[str],
        on_log: LogCallback | None,
        log: FontAdapter,
    ) -> FontOutcome:
        """Export one instance of a variable font."""
        started = time.perf_counter()
        try:
            with Font(
                input_path,
                recalc_bboxes=settings.recalc_bboxes,
                recalc_timestamp=settings.recalc_timestamp,
            ) as font:
                axis_tags = {axis.axisTag for axis in font.axes}
                coordinates = {tag: value for tag, value in spec.coordinates if tag in axis_tags}
                if spec.coordinates and not coordinates:
                    raise ValueError("The instance does not match the axes of this font.")
                flavor = font.ttfont.flavor
                label = font.to_static(coordinates, name=spec.name)
                self._log(on_log, f"Instancing {spec.name or label}...")
                if settings.target_upm and font.units_per_em != settings.target_upm:
                    self._log(on_log, f"Scaling UPM to {settings.target_upm}...")
                    font.scale_upm(settings.target_upm)
                self._log(on_log, "Correcting contours...")
                font.correct_contours()
                if font.is_tt and settings.autohint:
                    self._log(on_log, "Autohinting...")
                    font.ttf_autohint()
                elif font.is_ps and settings.subroutinize:
                    self._log(on_log, "Subroutinizing...")
                    font.subroutinize()
                stem = base_stem = instance_stem(input_path, spec.name, label)
                suffix = 2
                while stem in used_stems:
                    stem = f"{base_stem}-{suffix}"
                    suffix += 1
                used_stems.add(stem)
                output_dir = self._output_dir(font, settings, flavor, font.is_tt)
                extension = font.get_file_ext()
                output = font.get_file_path(
                    file=input_path.with_name(stem + extension),
                    output_dir=output_dir,
                    overwrite=settings.overwrite,
                    extension=extension,
                )
                font.save(output, reorder_tables=settings.reorder_tables)
            log.info("Instance %s saved to %s", spec.name or "default", output)
            return FontOutcome(
                input_path,
                FontOutcomeKind.CONVERTED,
                (Path(output),),
                elapsed=time.perf_counter() - started,
            )
        except Exception as error:
            log.exception("Instance export failed")
            return FontOutcome(
                input_path,
                FontOutcomeKind.FAILED,
                error=f"{type(error).__name__}: {error}",
                elapsed=time.perf_counter() - started,
            )

    def _extract_collection_member(
        self,
        input_path: Path,
        member: TTFont,
        settings: ConversionOptions,
        log: FontAdapter,
    ) -> FontOutcome:
        started = time.perf_counter()
        try:
            member.recalcBBoxes = settings.recalc_bboxes
            member.recalcTimestamp = settings.recalc_timestamp
            with Font(member) as font:
                font.ensure_postscript_name()
                name = sanitize_filename(font.get_postscript_name())
                extension = font.get_file_ext()
                member_settings = replace(
                    settings,
                    output_dir=settings.output_dir or input_path.parent,
                )
                output_dir = self._output_dir(font, member_settings, None, font.is_tt)
                output = makeOutputFileName(
                    name,
                    outputDir=output_dir or input_path.parent,
                    overWrite=member_settings.overwrite,
                    extension=extension,
                )
                font.save(output, reorder_tables=settings.reorder_tables)
            log.info("Member %s saved to %s", name, output)
            return FontOutcome(
                input_path,
                FontOutcomeKind.CONVERTED,
                (Path(output),),
                elapsed=time.perf_counter() - started,
            )
        except Exception as error:
            log.exception("Collection member extraction failed")
            return FontOutcome(
                input_path,
                FontOutcomeKind.FAILED,
                error=f"{type(error).__name__}: {error}",
                elapsed=time.perf_counter() - started,
            )

    @staticmethod
    def _report(
        outcome: FontOutcome,
        callback: OutcomeCallback | None,
    ) -> None:
        if callback is not None:
            callback(outcome)

    @staticmethod
    def _log(callback: LogCallback | None, message: str) -> None:
        logger.debug("%s", message)
        if callback is not None:
            callback(message)
