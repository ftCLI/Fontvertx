"""Generate the CSS (``@font-face`` rules and feature classes) for converted web fonts."""

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote as url_quote

CSS_FILE_NAME = "fonts.css"
_FORMAT_ORDER = {"woff2": 0, "woff": 1}


@dataclass(frozen=True)
class WebFontEntry:
    file: Path
    format: str
    family: str
    weight: int = 400
    italic: bool = False
    features: tuple[str, ...] = ()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-") or "font"


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _url(value: str) -> str:
    # Percent-encode the file name: reserved characters such as "#" would otherwise be
    # parsed as a fragment identifier and break the font request.
    return f'"{url_quote(value, safe="")}"'


def build_css(entries: Iterable[WebFontEntry]) -> str:
    """Return the CSS with one ``@font-face`` per font and one class per family and feature."""
    entries = sorted(entries, key=lambda e: (e.family, e.weight, e.italic, e.file.name))
    # The formats of the same font share one rule, with the most efficient format first.
    faces: dict[tuple[str, int, bool, str], list[WebFontEntry]] = {}
    for entry in entries:
        faces.setdefault((entry.family, entry.weight, entry.italic, entry.file.stem), []).append(
            entry
        )
    blocks: list[str] = []
    for (family, weight, italic, _), sources in faces.items():
        sources.sort(key=lambda e: _FORMAT_ORDER.get(e.format, len(_FORMAT_ORDER)))
        src = ",\n       ".join(
            f"url({_url(source.file.name)}) format({_quote(source.format)})" for source in sources
        )
        blocks.append(
            "@font-face {\n"
            f"  font-family: {_quote(family)};\n"
            f"  src: {src};\n"
            f"  font-weight: {weight};\n"
            f"  font-style: {'italic' if italic else 'normal'};\n"
            "  font-display: swap;\n"
            "}"
        )
    for family in sorted({entry.family for entry in entries}):
        # Generic fallback so text stays readable if the web font fails to load.
        blocks.append(f".family-{_slug(family)} {{ font-family: {_quote(family)}, sans-serif; }}")
    features = sorted({tag for entry in entries for tag in entry.features})
    for tag in features:
        blocks.append(f'.ft-{_slug(tag)} {{ font-feature-settings: "{tag}" 1; }}')
    return "\n\n".join(blocks) + "\n"


def write_css_kits(entries: Iterable[WebFontEntry], overwrite: bool = True) -> list[Path]:
    """Write one CSS file in each folder that contains converted web fonts."""
    by_folder: dict[Path, list[WebFontEntry]] = defaultdict(list)
    for entry in entries:
        by_folder[entry.file.parent].append(entry)
    written: list[Path] = []
    for folder, folder_entries in by_folder.items():
        path = folder / CSS_FILE_NAME
        counter = 1
        while not overwrite and path.exists():
            path = folder / f"{Path(CSS_FILE_NAME).stem}#{counter}.css"
            counter += 1
        path.write_text(build_css(folder_entries), encoding="utf-8")
        written.append(path)
    return written
