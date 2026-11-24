from __future__ import annotations

import hashlib
import logging
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from types import TracebackType
from typing import Any

import cffsubr
import ttfautohint as ttfautohint_module
from cffsubr import subroutinize
from fontTools import subset
from fontTools.misc.cliTools import makeOutputFileName
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.scaleUpem import scale_upem
from fontTools.varLib import instancer
from ttfautohint import ttfautohint

from fontvertx import constants as const
from fontvertx.contours import correct_cff_contours, correct_glyf_contours
from fontvertx.otf_builder import build_otf
from fontvertx.qu2cu import quadratics_to_cubics
from fontvertx.ttf_builder import build_ttf

__all__ = ["Font", "FontConversionError", "FontError"]


_CREATE_NO_WINDOW = 0x08000000

logger = logging.getLogger(__name__)


def _rename_glyph_refs(obj: object, old: str, new: str, seen: set[int]) -> None:
    """Replace glyph name ``old`` with ``new`` throughout an OpenType layout object tree."""
    if id(obj) in seen:
        return
    seen.add(id(obj))
    if isinstance(obj, dict):
        if old in obj:
            obj[new] = obj.pop(old)
        for key, value in list(obj.items()):
            if value == old:
                obj[key] = new
            elif not isinstance(value, str):
                _rename_glyph_refs(value, old, new, seen)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            if value == old:
                obj[i] = new
            elif not isinstance(value, str):
                _rename_glyph_refs(value, old, new, seen)
    elif hasattr(obj, "__dict__"):
        _rename_glyph_refs(vars(obj), old, new, seen)


def _hide_console_windows() -> None:
    """Keep the bundled command-line tools from opening a console window on Windows.

    cffsubr runs the AFDKO ``tx`` program and ttfautohint runs ``ttfautohint`` as a
    separate process for each font. A GUI app on Windows has no console, so every
    call opens a console window that closes immediately but takes focus, making
    the UI hard to use during a batch conversion.

    The fix wraps the function each library uses to start the process and adds
    ``CREATE_NO_WINDOW`` to the subprocess flags:

    - ``cffsubr._run_embedded_tx`` (private: re-check it when upgrading cffsubr;
      tested with 0.4.0);
    - ``ttfautohint.run`` (public; tested with ttfautohint-py 0.6.1).

    If a name is renamed, the attribute lookup fails at import time instead of
    silently doing nothing.

    Only Windows needs this: POSIX systems do not create a console window for
    child processes, so the function does nothing elsewhere.

    The alternative to cffsubr, compreffor, subroutinizes in-process and needs no
    patch, but it measured 3-5x slower with ~1-2% smaller output, so cffsubr was
    kept.
    """
    if sys.platform != "win32":
        return

    def without_console(original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("creationflags", _CREATE_NO_WINDOW)
            return original(*args, **kwargs)

        return wrapper

    cffsubr._run_embedded_tx = without_console(cffsubr._run_embedded_tx)
    ttfautohint_module.run = without_console(ttfautohint_module.run)


_hide_console_windows()


@contextmanager
def restore_flavor(font: TTFont) -> Iterator[None]:
    """Temporarily set the flavor to None (needed to subroutinize WOFF/WOFF2 fonts)."""
    original_flavor = font.flavor
    font.flavor = None
    try:
        yield
    finally:
        font.flavor = original_flavor


class FontError(Exception):
    """Raised for font-related errors."""


class FontConversionError(Exception):
    """Raised when a font cannot be converted."""


class Font:
    """A thin wrapper around ``TTFont`` providing the operations needed by the converter."""

    def __init__(
        self,
        font_source: str | Path | BytesIO | TTFont,
        lazy: bool | None = None,
        recalc_bboxes: bool = True,
        recalc_timestamp: bool = False,
    ) -> None:
        self._file: Path | None = None
        self._bytesio: BytesIO | None = None
        if isinstance(font_source, (str, Path)):
            self._file = Path(font_source).resolve()
            self._ttfont = TTFont(
                font_source,
                lazy=lazy,
                recalcBBoxes=recalc_bboxes,
                recalcTimestamp=recalc_timestamp,
            )
            return
        if isinstance(font_source, TTFont):
            buffer = BytesIO()
            font_source.save(buffer, reorderTables=False)
            buffer.seek(0)
            font_source = buffer
        if isinstance(font_source, BytesIO):
            self._bytesio = font_source
            self._ttfont = TTFont(
                font_source,
                lazy=lazy,
                recalcBBoxes=recalc_bboxes,
                recalcTimestamp=recalc_timestamp,
            )
            return
        raise FontError(
            f"Invalid source type {type(font_source)}. Expected str, Path, BytesIO, or TTFont."
        )

    def __enter__(self) -> Font:
        return self

    def __exit__(
        self,
        exc_type: type | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<Font: ttfont={self.ttfont}, file={self.file}, bytesio={self.bytesio}>"

    @property
    def file(self) -> Path | None:
        return self._file

    @property
    def bytesio(self) -> BytesIO | None:
        return self._bytesio

    @property
    def ttfont(self) -> TTFont:
        return self._ttfont

    @property
    def units_per_em(self) -> int:
        return int(self.ttfont[const.T_HEAD].unitsPerEm)

    @property
    def is_ps(self) -> bool:
        return self.ttfont.sfntVersion == const.PS_SFNT_VERSION

    @property
    def is_tt(self) -> bool:
        return self.ttfont.sfntVersion in (const.TT_SFNT_VERSION, const.TRUE_SFNT_VERSION)

    @property
    def is_woff(self) -> bool:
        return self.ttfont.flavor == const.WOFF_FLAVOR

    @property
    def is_woff2(self) -> bool:
        return self.ttfont.flavor == const.WOFF2_FLAVOR

    @property
    def is_sfnt(self) -> bool:
        return self.ttfont.flavor is None

    @property
    def is_static(self) -> bool:
        return self.ttfont.get(const.T_FVAR) is None

    @property
    def is_variable(self) -> bool:
        return self.ttfont.get(const.T_FVAR) is not None

    def save(self, file: str | Path | BytesIO, reorder_tables: bool | None = True) -> None:
        """Save the font. ``reorder_tables=None`` reorders by table dependency (fastest)."""
        self.ttfont.save(file, reorderTables=reorder_tables)

    def close(self) -> None:
        self.ttfont.close()
        if self.bytesio:
            self.bytesio.close()

    def get_file_ext(self) -> str:
        """Return the real extension of the font (WOFF and WOFF2 are checked first)."""
        if self.is_woff:
            return const.WOFF_EXTENSION
        if self.is_woff2:
            return const.WOFF2_EXTENSION
        if self.is_ps:
            return const.OTF_EXTENSION
        if self.is_tt:
            return const.TTF_EXTENSION
        raise ValueError("Unknown font type.")

    def get_file_path(
        self,
        file: Path | None = None,
        output_dir: Path | None = None,
        overwrite: bool = True,
        extension: str | None = None,
    ) -> Path:
        """
        Build the output path. If the file exists and ``overwrite`` is ``False``, a number
        preceded by '#' is added to the name until it is unique.
        """
        file = file or self.file
        if file is None:
            raise ValueError(
                "Cannot get output file for a BytesIO object without providing a file name."
            )

        out_dir = output_dir or file.parent
        extension = extension or self.get_file_ext()
        # The extension is appended so that makeOutputFileName only strips it, keeping any dots
        # that belong to the file name.
        return Path(
            makeOutputFileName(
                input=file.stem + extension,
                outputDir=out_dir,
                extension=extension,
                overWrite=overwrite,
            )
        )

    def ensure_postscript_name(self) -> None:
        """Build the PostScript name (name ID 6) from family and subfamily if it is missing."""
        name_table = self.ttfont[const.T_NAME]
        if name_table.getDebugName(6):
            return
        try:
            family = name_table.getBestFamilyName()
            if not family:
                raise FontConversionError(
                    "Cannot build the PostScript name: the font has no family name."
                )
            subfamily = name_table.getBestSubFamilyName() or "Regular"
            ps_name = f"{family}-{subfamily}".replace(" ", "").replace(".", "_")
            logger.debug("Built missing PostScript name %r from the name table", ps_name)
            name_table.removeNames(nameID=6)
            name_table.addMultilingualName(
                {"en": ps_name}, ttFont=self.ttfont, nameID=6, windows=True, mac=True
            )
        except Exception as error:
            raise FontConversionError(
                "An error occurred while building the PostScript name from the family and "
                "subfamily names."
            ) from error

    def get_postscript_name(self) -> str:
        return self.ttfont[const.T_NAME].getDebugName(6) or ""

    def to_woff(self) -> None:
        if self.is_woff:
            raise FontConversionError("Font is already a WOFF font.")
        self.ttfont.flavor = const.WOFF_FLAVOR

    def to_woff2(self) -> None:
        if self.is_woff2:
            raise FontConversionError("Font is already a WOFF2 font.")
        self.ttfont.flavor = const.WOFF2_FLAVOR

    def to_sfnt(self) -> None:
        if self.is_sfnt:
            raise FontConversionError("Font is already a TTF or OTF font.")
        self.ttfont.flavor = None

    def remove_unused_glyphs(self) -> int:
        """
        Drop the glyphs that are not reachable from the cmap or from layout features.

        All the mapped characters and the OpenType features are kept. Return the number of
        glyphs removed.
        """
        before = len(self.ttfont.getGlyphOrder())
        options = subset.Options()
        options.layout_features = ["*"]
        options.name_IDs = ["*"]
        options.name_languages = ["*"]
        options.notdef_outline = True
        options.glyph_names = True
        options.legacy_kern = True
        options.hinting = True
        options.layout_closure = True
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(unicodes=list(self.ttfont.getBestCmap() or {}))
        subsetter.subset(self.ttfont)
        return before - len(self.ttfont.getGlyphOrder())

    def obfuscate_names(self) -> tuple[str, str]:
        """
        Replace the family, full, unique and PostScript names with hashes.

        The style name (name ID 2) is kept and the other records (copyright, license...) are not
        touched. Return the obfuscated family name and PostScript name.
        """
        name_table = self.ttfont[const.T_NAME]
        family = str(name_table.getBestFamilyName() or "")
        original_ps = str(name_table.getDebugName(6) or family)
        subfamily = str(name_table.getDebugName(2) or "Regular")

        def digest(value: str, length: int) -> str:
            return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]

        new_family = f"f{digest(family, 10)}"
        new_ps = f"{new_family}-{digest(original_ps, 8)}"
        for name_id in (1, 2, 3, 4, 6, 16, 17, 21, 22, 25):
            name_table.removeNames(nameID=name_id)
        entries = {1: new_family, 2: subfamily, 3: new_ps, 4: new_ps, 6: new_ps}
        for name_id, value in entries.items():
            name_table.setName(value, name_id, *const.WINDOWS_EN_US)
            name_table.setName(value, name_id, *const.MAC_ROMAN_ENGLISH)
        if "CFF " in self.ttfont:
            cff = self.ttfont["CFF "].cff
            cff.fontNames = [new_ps]
            top_dict = cff.topDictIndex[0]
            top_dict.FullName = new_ps
            top_dict.FamilyName = new_family
        return new_family, new_ps

    def remove_non_windows_names(self) -> int:
        """Remove the name records whose platform ID is not 3 (Windows); return how many."""
        name_table = self.ttfont[const.T_NAME]
        before = len(name_table.names)
        name_table.names = [record for record in name_table.names if record.platformID == 3]
        return before - len(name_table.names)

    def remove_dsig(self) -> bool:
        """Remove the DSIG table; return whether it was present."""
        if const.T_DSIG not in self.ttfont:
            return False
        del self.ttfont[const.T_DSIG]
        return True

    def get_features(self) -> tuple[str, ...]:
        """Return the sorted OpenType feature tags defined in GSUB and GPOS."""
        tags: set[str] = set()
        for table_tag in ("GSUB", "GPOS"):
            if table_tag not in self.ttfont:
                continue
            feature_list = self.ttfont[table_tag].table.FeatureList
            if feature_list is not None:
                tags.update(record.FeatureTag for record in feature_list.FeatureRecord)
        return tuple(sorted(tags))

    def to_ttf(self, max_err: float = 1.0, reverse_direction: bool = True) -> None:
        """Convert a PostScript font to TrueType, removing overlaps and fixing contour direction."""
        if self.is_tt:
            raise FontConversionError("Font is already a TrueType font.")
        if self.is_variable:
            raise FontConversionError("Conversion to TrueType is not supported for variable fonts.")

        build_ttf(font=self.ttfont, max_err=max_err, reverse_direction=reverse_direction)
        correct_glyf_contours(self.ttfont, remove_hinting=True, ignore_errors=False)

    def to_otf(self, tolerance: float = 1.0, simplify: int = 0) -> None:
        """
        Convert a TrueType font to PostScript. If the font has no PostScript name (name ID 6),
        it is built from the family and subfamily names.
        """
        if self.is_ps:
            raise FontConversionError("Font is already a PostScript font.")
        if self.is_variable:
            raise FontConversionError(
                "Conversion to PostScript is not supported for variable fonts."
            )
        self.ensure_postscript_name()
        self._ensure_notdef_first()
        self._decompose_composite_glyphs()

        charstrings = quadratics_to_cubics(font=self.ttfont, tolerance=tolerance, simplify=simplify)
        build_otf(font=self.ttfont, charstrings_dict=charstrings)

        self.ttfont[const.T_OS_2].recalcAvgCharWidth(ttFont=self.ttfont)

    def _ensure_notdef_first(self) -> None:
        """
        CFF requires glyph 0 to be named ``.notdef``, while TrueType fonts may name it freely.
        Rename glyph 0 (and every reference to it) when needed.
        """
        order = list(self.ttfont.getGlyphOrder())
        old = order[0]
        if old == ".notdef":
            return
        if ".notdef" in order:
            raise FontConversionError("The .notdef glyph is not the first glyph of the font.")
        new = ".notdef"
        order[0] = new
        self.ttfont.setGlyphOrder(order)

        glyf = self.ttfont[const.T_GLYF]
        glyf.glyphOrder = order
        glyf.glyphs = {(new if k == old else k): v for k, v in glyf.glyphs.items()}
        for tag in ("hmtx", "vmtx"):
            if tag in self.ttfont:
                metrics = self.ttfont[tag].metrics
                if old in metrics:
                    metrics[new] = metrics.pop(old)
        if "cmap" in self.ttfont:
            for subtable in self.ttfont["cmap"].tables:
                for code, name in subtable.cmap.items():
                    if name == old:
                        subtable.cmap[code] = new
        for tag in ("GSUB", "GPOS", "GDEF"):
            if tag in self.ttfont:
                _rename_glyph_refs(self.ttfont[tag].table, old, new, set())

    def _decompose_composite_glyphs(self) -> None:
        glyf = self.ttfont[const.T_GLYF]
        glyph_set = self.ttfont.getGlyphSet()
        for glyph_name in self.ttfont.getGlyphOrder():
            if not glyf[glyph_name].isComposite():
                continue
            dc_pen = DecomposingRecordingPen(glyph_set)
            glyph_set[glyph_name].draw(dc_pen)
            tt_pen = TTGlyphPen(None)
            dc_pen.replay(tt_pen)
            glyf[glyph_name] = tt_pen.glyph()

    @property
    def axes(self) -> list[Any]:
        return list(self.ttfont[const.T_FVAR].axes) if self.is_variable else []

    def to_static(
        self,
        coordinates: dict[str, float] | None = None,
        name: str | None = None,
    ) -> str:
        """
        Replace the font with a static instance and return the string describing its location.

        Axes missing from ``coordinates`` are pinned to their default. For a named instance
        (``name`` given) the name table comes from the STAT table when possible; otherwise,
        and for custom instances, it is rebuilt from ``name`` or from the axis values.
        """
        if not self.is_variable:
            raise FontConversionError("Font is not a variable font.")
        location = {axis.axisTag: axis.defaultValue for axis in self.axes}
        location.update(coordinates or {})
        label = " ".join(f"{tag}{value:g}" for tag, value in location.items())
        flavor = self.ttfont.flavor
        names_updated = False
        instance = None
        if name is not None:
            try:
                instance = self._instantiate(location, update_names=True)
                names_updated = True
            except (ValueError, AttributeError, KeyError):
                # Incomplete STAT/name data (e.g. missing axis value names): rebuild names.
                logger.warning(
                    "Could not derive names for instance %r from the STAT table; "
                    "rebuilding them from the axis values",
                    name,
                )
        if instance is None:
            instance = self._instantiate(location, update_names=False)
        if not names_updated:
            self._write_instance_names(instance, name or label)
        self.ttfont.close()
        instance.flavor = flavor
        self._ttfont = instance
        return label

    def _instantiate(self, location: dict[str, float], update_names: bool) -> TTFont:
        return instancer.instantiateVariableFont(
            self.ttfont,
            dict(location),
            inplace=False,
            static=True,
            downgradeCFF2="CFF2" in self.ttfont,
            updateFontNames=update_names,
        )

    @staticmethod
    def _write_instance_names(font: TTFont, label: str) -> None:
        name_table = font[const.T_NAME]
        family = str(name_table.getBestFamilyName() or "")
        full = f"{family} {label}".strip()
        ps_name = f"{family}-{label}".replace(" ", "")
        unique_id = f"{full};{font[const.T_HEAD].fontRevision:.3f}"
        for name_id in (1, 2, 3, 4, 6, 16, 17, 25):
            name_table.removeNames(nameID=name_id)
        # Legacy RIBBI model: nameID 2 may only be Regular/Bold/Italic/Bold Italic; other
        # styles go to nameID 1 (fontTools.instancer does the same with updateFontNames).
        is_ribbi = label in ("Regular", "Bold", "Italic", "Bold Italic")
        entries = {
            1: family if is_ribbi else full,
            2: label if is_ribbi else "Regular",
            3: unique_id,
            4: full,
            6: ps_name,
            16: family,
            17: label,
        }
        for name_id, value in entries.items():
            name_table.setName(value, name_id, *const.WINDOWS_EN_US)
            name_table.setName(value, name_id, *const.MAC_ROMAN_ENGLISH)

    def scale_upm(self, target_upm: int) -> None:
        """Scale the font to ``target_upm`` units per em (16 to 16384)."""
        if target_upm < const.MIN_UPM or target_upm > const.MAX_UPM:
            raise ValueError(
                f"units_per_em must be in the range {const.MIN_UPM} to {const.MAX_UPM}."
            )
        if self.units_per_em == target_upm:
            return
        scale_upem(self.ttfont, new_upem=target_upm)

    def decompose_transformed(self) -> set[str]:
        """Decompose composite glyphs whose components are scaled, flipped or rotated."""
        glyf = self.ttfont[const.T_GLYF]
        glyph_set = self.ttfont.getGlyphSet()
        decomposed = set()
        for name in self.ttfont.getGlyphOrder():
            glyph = glyf[name]
            if not glyph.isComposite():
                continue
            if all(c.getComponentInfo()[1][0:4] == (1, 0, 0, 1) for c in glyph.components):
                continue
            recorder = DecomposingRecordingPen(glyph_set)
            glyph_set[name].draw(recorder)
            pen = TTGlyphPen(None)
            recorder.replay(pen)
            glyf[name] = pen.glyph()
            decomposed.add(name)
        return decomposed

    def correct_contours(self) -> set[str]:
        """Remove overlaps and fix the direction of the contours, dropping stale hinting."""
        if self.is_tt:
            self.decompose_transformed()
            return correct_glyf_contours(self.ttfont, remove_hinting=True, ignore_errors=False)
        return correct_cff_contours(self.ttfont, remove_hinting=True, ignore_errors=False)

    def subroutinize(self) -> bool:
        """Subroutinize the CFF table, also for WOFF and WOFF2 fonts."""
        if not self.is_ps:
            raise NotImplementedError("Not a PostScript font.")
        with restore_flavor(self.ttfont):
            subroutinize(self.ttfont)
            return True

    def ttf_autohint(self) -> bool:
        """Apply ttfautohint instructions to a TrueType font, also for WOFF and WOFF2 fonts."""
        if not self.is_tt:
            raise NotImplementedError("Not a TrueType font.")
        flavor = self.ttfont.flavor
        try:
            with BytesIO() as buffer:
                modified = self.ttfont[const.T_HEAD].modified
                self.ttfont.flavor = None
                self.save(buffer, reorder_tables=None)
                data = ttfautohint(in_buffer=buffer.getvalue(), no_info=True)
            hinted_font = TTFont(BytesIO(data), recalcTimestamp=False)
            hinted_font[const.T_HEAD].modified = modified
        except Exception as error:
            self.ttfont.flavor = flavor
            raise FontConversionError(f"Autohinting failed: {error}") from error
        self.ttfont.close()
        hinted_font.flavor = flavor
        self._ttfont = hinted_font
        return True
