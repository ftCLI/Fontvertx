"""Interface-independent request and result types for font conversions."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar, Literal, TypeAlias

ConversionKind: TypeAlias = Literal[
    "ttf2otf", "otf2ttf", "ft2wf", "woff2ft", "woff22ft", "ttc2sfnt", "var2static"
]
WebFormat: TypeAlias = Literal["woff", "woff2"]


@dataclass(frozen=True)
class ConversionOptions:
    recursive: bool = False
    output_dir: Path | None = None
    overwrite: bool = False
    recalc_bboxes: bool = True
    recalc_timestamp: bool = False
    reorder_tables: bool = True
    organization_levels: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class TtfToOtfOptions(ConversionOptions):
    tolerance: float = 1.0
    target_upm: int | None = None
    subroutinize: bool = True
    simplify: int = 0


@dataclass(frozen=True)
class OtfToTtfOptions(ConversionOptions):
    tolerance: float = 1.0
    target_upm: int | None = None
    autohint: bool = True


@dataclass(frozen=True)
class SfntToWebOptions(ConversionOptions):
    format: WebFormat | None = None
    obfuscate_names: bool = False
    remove_unused_glyphs: bool = False
    remove_non_windows_names: bool = False
    css_kit: bool = False
    remove_dsig: bool = False  # WOFF only: WOFF2 does not support the DSIG table


@dataclass(frozen=True)
class WebToSfntOptions(ConversionOptions):
    format: ClassVar[WebFormat | None] = None


@dataclass(frozen=True)
class WoffToSfntOptions(WebToSfntOptions):
    format: ClassVar[WebFormat | None] = "woff"


@dataclass(frozen=True)
class Woff2ToSfntOptions(WebToSfntOptions):
    format: ClassVar[WebFormat | None] = "woff2"


@dataclass(frozen=True)
class TtcToSfntOptions(ConversionOptions):
    pass


@dataclass(frozen=True)
class InstanceSpec:
    """A location in the design space; ``name`` is set for instances defined in the fvar table."""

    coordinates: tuple[tuple[str, float], ...]
    name: str | None = None


@dataclass(frozen=True)
class VarToStaticOptions(ConversionOptions):
    # Instances to export for each input font; a font without an entry exports its default.
    instances: tuple[tuple[Path, tuple[InstanceSpec, ...]], ...] = ()
    target_upm: int | None = None
    autohint: bool = True  # TrueType outlines only
    subroutinize: bool = True  # PostScript outlines only


ConversionSettings: TypeAlias = (
    TtfToOtfOptions
    | OtfToTtfOptions
    | SfntToWebOptions
    | WebToSfntOptions
    | TtcToSfntOptions
    | VarToStaticOptions
)

_CONVERSION_BY_SETTINGS: dict[type[ConversionOptions], ConversionKind] = {
    VarToStaticOptions: "var2static",
    TtfToOtfOptions: "ttf2otf",
    OtfToTtfOptions: "otf2ttf",
    SfntToWebOptions: "ft2wf",
    WoffToSfntOptions: "woff2ft",
    Woff2ToSfntOptions: "woff22ft",
    TtcToSfntOptions: "ttc2sfnt",
}


@dataclass(frozen=True)
class ConversionRequest:
    input_paths: tuple[Path, ...]
    settings: ConversionSettings

    @property
    def conversion(self) -> ConversionKind:
        return _CONVERSION_BY_SETTINGS[type(self.settings)]


class FontOutcomeKind(Enum):
    CONVERTED = "converted"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class FontOutcome:
    """Outcome for one font; a collection can produce multiple outcomes per input path."""

    input_path: Path
    kind: FontOutcomeKind
    output_paths: tuple[Path, ...] = ()
    error: str | None = None
    elapsed: float = 0.0


@dataclass(frozen=True)
class ConversionProgress:
    """Batch progress measured in fonts, including each member of a collection."""

    done: int
    total: int


ProgressCallback: TypeAlias = Callable[[ConversionProgress], None]
OutcomeCallback: TypeAlias = Callable[[FontOutcome], None]
FontStartCallback: TypeAlias = Callable[[Path], None]
CancellationCheck: TypeAlias = Callable[[], bool]
LogCallback: TypeAlias = Callable[[str], None]
PauseWait: TypeAlias = Callable[[], None]


@dataclass(frozen=True)
class ConversionResult:
    """Structured batch result, independent of CLI output and GUI presentation."""

    outcomes: tuple[FontOutcome, ...] = ()
    error: str | None = None
    cancelled: bool = False

    @property
    def elapsed(self) -> float:
        """Total conversion time in seconds: the sum of per-font times, so pauses are excluded."""
        return sum(outcome.elapsed for outcome in self.outcomes)

    @property
    def converted_count(self) -> int:
        return sum(outcome.kind is FontOutcomeKind.CONVERTED for outcome in self.outcomes)

    @property
    def skipped_count(self) -> int:
        return sum(outcome.kind is FontOutcomeKind.SKIPPED for outcome in self.outcomes)

    @property
    def failed_count(self) -> int:
        return sum(outcome.kind is FontOutcomeKind.FAILED for outcome in self.outcomes)

    @property
    def saved_files(self) -> list[Path]:
        return [
            path
            for outcome in self.outcomes
            if outcome.kind is FontOutcomeKind.CONVERTED
            for path in outcome.output_paths
        ]

    @property
    def ok(self) -> bool:
        return self.error is None and self.failed_count == 0
