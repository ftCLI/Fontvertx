from __future__ import annotations

from PySide6.QtGui import QFontMetrics, QPalette, Qt
from PySide6.QtWidgets import QApplication, QToolTip

from fontvertx.gui import tooltips
from fontvertx.gui.styles import LIGHT, UI_FONT_FAMILY

BACKSLASH = chr(92)


def test_tooltip_theme_is_applied(qapp: QApplication) -> None:
    tooltips.install_tooltip_theme(qapp)
    palette = QToolTip.palette()
    group = QPalette.ColorGroup.Active
    assert palette.color(group, QPalette.ColorRole.ToolTipBase) == LIGHT.tooltip_bg
    assert palette.color(group, QPalette.ColorRole.ToolTipText) == LIGHT.tooltip_text
    assert QToolTip.font().family() == UI_FONT_FAMILY


# Short enough for one line even with the wider fallback font of the offscreen test platform
# (the Geist path with a "static" folder: ~225 px in Inter, but 420 px there).
SHORT_PATH = BACKSLASH.join(["D:", "fonts", "Geist", "Geist-Black.ttf"])
TOLERANCE = (
    "Higher values allow larger curve deviations and usually produce fewer points; "
    "lower values preserve more detail. "
    "Tolerance is in thousandths of an em; actual deviation scales with UPM."
)
SEPARATORS = (BACKSLASH, "/", "_", "-")


def _width(text: str) -> int:
    return QFontMetrics(tooltips.tooltip_font()).horizontalAdvance(text)


def test_wrap_tip_leaves_short_text_on_one_line(qapp: QApplication) -> None:
    assert _width(SHORT_PATH) <= tooltips.TOOLTIP_WRAP_WIDTH
    assert tooltips.wrap_tip(SHORT_PATH) == SHORT_PATH
    assert "\n" not in tooltips.wrap_tip(SHORT_PATH)


def test_wrap_tip_wraps_long_text_at_spaces(qapp: QApplication) -> None:
    lines = tooltips.wrap_tip(TOLERANCE).split("\n")
    assert len(lines) > 1
    assert all(_width(line) <= tooltips.TOOLTIP_WRAP_WIDTH for line in lines)
    assert " ".join(lines).split() == TOLERANCE.split()


def test_wrap_tip_breaks_long_paths_after_separators(qapp: QApplication) -> None:
    folders = [f"Very long folder name {n}" for n in range(8)]
    path = BACKSLASH.join(["D:", *folders, "Type_Foundry/Family-Name-Bold.ttf"])
    path = path.replace(" ", "_")  # one word, wider than the limit
    assert _width(path) > tooltips.TOOLTIP_WRAP_WIDTH
    lines = tooltips.wrap_tip(path).split("\n")
    assert len(lines) > 1
    assert all(line.endswith(SEPARATORS) for line in lines[:-1])
    assert all(_width(line) <= tooltips.TOOLTIP_WRAP_WIDTH for line in lines)
    assert "".join(lines) == path


def test_wrap_tip_keeps_folder_names_with_spaces_whole(qapp: QApplication) -> None:
    folders = [f"Very long folder name {n}" for n in range(8)]
    path = BACKSLASH.join(["D:", *folders, "Family Name-Bold.ttf"])
    lines = tooltips.wrap_tip(f"{path}\nNot a TrueType font").split("\n")
    assert lines[-1] == "Not a TrueType font"
    path_lines = lines[:-1]
    assert len(path_lines) > 1
    assert all(line.endswith(SEPARATORS) for line in path_lines[:-1])
    assert all(_width(line) <= tooltips.TOOLTIP_WRAP_WIDTH for line in path_lines)
    assert "".join(path_lines) == path


def test_wrap_tip_breaks_between_characters_only_as_a_last_resort(qapp: QApplication) -> None:
    word = "W" * 200
    lines = tooltips.wrap_tip(word).split("\n")
    assert len(lines) > 1
    assert "".join(lines) == word
    assert all(_width(line) <= tooltips.TOOLTIP_WRAP_WIDTH for line in lines)


def test_wrap_tip_keeps_existing_line_breaks_and_stays_plain(qapp: QApplication) -> None:
    text = f"{SHORT_PATH}\nNot a TrueType font"
    assert tooltips.wrap_tip(text) == text
    for sample in (text, TOLERANCE):
        assert not Qt.mightBeRichText(tooltips.wrap_tip(sample))
