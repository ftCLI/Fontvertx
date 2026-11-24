from pathlib import Path

import pytest

from fontvertx import models


@pytest.mark.parametrize(
    ("settings", "conversion"),
    [
        (models.TtfToOtfOptions(), "ttf2otf"),
        (models.OtfToTtfOptions(), "otf2ttf"),
        (models.SfntToWebOptions(), "ft2wf"),
        (models.WoffToSfntOptions(), "woff2ft"),
        (models.Woff2ToSfntOptions(), "woff22ft"),
        (models.TtcToSfntOptions(), "ttc2sfnt"),
        (models.VarToStaticOptions(), "var2static"),
    ],
)
def test_request_conversion(settings: models.ConversionSettings, conversion: str) -> None:
    assert models.ConversionRequest((), settings).conversion == conversion


def test_result_properties() -> None:
    output = Path("converted.otf")
    result = models.ConversionResult(
        (
            models.FontOutcome(
                Path("a.ttf"), models.FontOutcomeKind.CONVERTED, (output,), elapsed=1
            ),
            models.FontOutcome(Path("b.ttf"), models.FontOutcomeKind.SKIPPED, elapsed=2),
            models.FontOutcome(Path("c.ttf"), models.FontOutcomeKind.FAILED, elapsed=3),
        )
    )
    assert result.elapsed == 6
    assert (result.converted_count, result.skipped_count, result.failed_count) == (1, 1, 1)
    assert result.saved_files == [output]
    assert not result.ok
