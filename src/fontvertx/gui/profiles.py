"""Metadata registry for the converter's supported conversion profiles."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    """Everything the GUI needs to know about a conversion profile."""

    label: str
    heading: str | None = None
    criteria: tuple[str, ...] = ("family", "format", "outline")
    outline: str = "tt"
    extension: str = ".ttf"


PROFILES: dict[str, Profile] = {
    "ttf2otf": Profile(
        "TTF → OTF (TrueType → PostScript)",
        heading="Outlines",
        criteria=("family", "format", "outline", "upm", "tolerance", "simplify"),
        outline="ps",
        extension=".otf",
    ),
    "otf2ttf": Profile(
        "OTF → TTF (PostScript → TrueType)",
        criteria=("family", "format", "outline", "upm", "tolerance"),
    ),
    "ft2wf": Profile(
        "TTF / OTF → WOFF / WOFF2",
        heading="Web fonts",
        extension=".{format}",
    ),
    "woff2ft": Profile("WOFF → TTF / OTF"),
    "woff22ft": Profile("WOFF2 → TTF / OTF"),
    "var2static": Profile(
        "TTFV / OTFV → TTF / OTF (Variable → Static)",
        heading="Other",
        criteria=("family", "format", "outline", "upm"),
    ),
    "ttc2sfnt": Profile("TTC / OTC → TTF / OTF (Collection → Singles)"),
}

CONVERSIONS: dict[str, str] = {key: profile.label for key, profile in PROFILES.items()}

CONVERSION_GROUP_HEADINGS: dict[str, str] = {
    key: profile.heading for key, profile in PROFILES.items() if profile.heading is not None
}


def available_organization_criteria(conversion: str) -> tuple[str, ...]:
    profile = PROFILES.get(conversion)
    return profile.criteria if profile is not None else Profile("").criteria
