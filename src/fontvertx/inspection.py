"""Font metadata inspection and conversion compatibility checks."""

import logging
from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTFont

from fontvertx.constants import PS_SFNT_VERSION, T_FVAR, T_HEAD, T_NAME
from fontvertx.finder import FinderOptions, FontFinder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AxisInfo:
    tag: str
    minimum: float
    default: float
    maximum: float


@dataclass(frozen=True)
class NamedInstanceInfo:
    name: str
    coordinates: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class FontInfo:
    path: Path
    format: str
    outlines: str
    upm: int | None
    variable: bool = False
    collection: bool = False
    num_fonts: int = 1
    axes: tuple[AxisInfo, ...] = ()
    instances: tuple[NamedInstanceInfo, ...] = ()
    family: str = ""
    style: str = ""


def incompatibility(info: FontInfo, conversion: str) -> str | None:
    """Return why the font cannot be used with the profile, or ``None`` if it can."""
    if conversion == "ttc2sfnt":
        return None if info.collection else "Not a font collection"
    if info.collection:
        return "Font collections require the Collection (TTC/OTC) → TTF / OTF profile"
    if conversion == "var2static":
        return None if info.variable else "Not a variable font"
    if conversion == "ttf2otf":
        if info.outlines != "TrueType":
            return "Not a TrueType font"
        if info.variable:
            return "Variable fonts are not supported"
    elif conversion == "otf2ttf":
        if info.outlines != "PostScript":
            return "Not a PostScript font"
        if info.variable:
            return "Variable fonts are not supported"
    elif conversion == "ft2wf":
        if info.format in ("WOFF", "WOFF2"):
            return "Already a web font"
    elif conversion in ("woff2ft", "woff22ft"):
        required = "WOFF" if conversion == "woff2ft" else "WOFF2"
        if info.format not in ("WOFF", "WOFF2"):
            return "Not a web font"
        if info.format != required:
            return f"Not a {required} font"
    return None


_cache: dict[tuple[Path, int, int], FontInfo | None] = {}


def inspect_font(path: Path) -> FontInfo | None:
    """Return the font metadata, or ``None`` if the file is not a readable font."""
    try:
        stat = path.stat()
    except OSError as error:
        logger.debug("Cannot stat %s: %s", path, error)
        return None
    key = (path.resolve(), stat.st_mtime_ns, stat.st_size)
    if key not in _cache:
        _cache[key] = _read_font_info(path)
    return _cache[key]


def _font_names(ttfont: TTFont) -> tuple[str, str]:
    name_table = ttfont.get(T_NAME)
    if name_table is None:
        return "", ""
    return name_table.getBestFamilyName() or "", name_table.getBestSubFamilyName() or ""


def _read_font_info(path: Path) -> FontInfo | None:
    try:
        for font in FontFinder(path, options=FinderOptions(lazy=True)).generate_fonts():
            with font:
                if font.is_woff2:
                    format_ = "WOFF2"
                elif font.is_woff:
                    format_ = "WOFF"
                elif font.is_ps:
                    format_ = "OTF"
                else:
                    format_ = "TTF"
                outlines = "PostScript" if font.is_ps else "TrueType"
                family, style = _font_names(font.ttfont)
                axes: tuple[AxisInfo, ...] = ()
                instances: tuple[NamedInstanceInfo, ...] = ()
                if font.is_variable:
                    fvar = font.ttfont[T_FVAR]
                    axes = tuple(
                        AxisInfo(a.axisTag, a.minValue, a.defaultValue, a.maxValue)
                        for a in fvar.axes
                    )
                    name_table = font.ttfont[T_NAME]
                    instances = tuple(
                        NamedInstanceInfo(
                            name_table.getDebugName(i.subfamilyNameID) or "Unnamed",
                            tuple(i.coordinates.items()),
                        )
                        for i in fvar.instances
                    )
                return FontInfo(
                    path,
                    format_,
                    outlines,
                    font.units_per_em,
                    font.is_variable,
                    axes=axes,
                    instances=instances,
                    family=family,
                    style=style,
                )
    except Exception as error:
        logger.debug("Cannot read font info from %s: %s", path, error)
        return None
    return _read_collection_info(path)


def _read_collection_info(path: Path) -> FontInfo | None:
    try:
        for collection in FontFinder(path, options=FinderOptions(lazy=True)).generate_collections():
            try:
                members = collection.fonts
                if not members:
                    return None
                outlines = {
                    "PostScript" if ttfont.sfntVersion == PS_SFNT_VERSION else "TrueType"
                    for ttfont in members
                }
                upms = {int(ttfont[T_HEAD].unitsPerEm) for ttfont in members}
                names = [_font_names(ttfont) for ttfont in members]
                families = {family for family, _ in names}
                styles = {style for _, style in names}
                return FontInfo(
                    path,
                    "TTC",
                    outlines.pop() if len(outlines) == 1 else "Mixed",
                    upms.pop() if len(upms) == 1 else None,
                    any(ttfont.get(T_FVAR) is not None for ttfont in members),
                    collection=True,
                    num_fonts=len(members),
                    family=families.pop() if len(families) == 1 else "Mixed",
                    style=styles.pop() if len(styles) == 1 else "Mixed",
                )
            finally:
                collection.close()
    except Exception as error:
        logger.debug("Cannot read collection info from %s: %s", path, error)
        return None
    return None
