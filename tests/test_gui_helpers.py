import json
import logging
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontInfo,
    QIcon,
    QImage,
    QPainter,
    QPixmap,
    QTextLayout,
)
from PySide6.QtWidgets import QApplication, QLabel, QStyleOptionViewItem, QTreeWidgetItem

from fontvertx import __main__ as main_module
from fontvertx.gui import scanner as scanner_module
from fontvertx.gui.app_style import AppStyle
from fontvertx.gui.instance_tree import InstanceTree
from fontvertx.gui.logs import LogEntry
from fontvertx.gui.organization_dialog import OrganizationDialog
from fontvertx.gui.profiles import CONVERSION_GROUP_HEADINGS, CONVERSIONS
from fontvertx.gui.scanner import ScanWorker, Source
from fontvertx.gui.styles import UI_FONT_FAMILY, mono_family, stylesheet
from fontvertx.gui.widgets import ConversionSelector, FileTable


def test_log_entry_formats_display_and_json() -> None:
    entry = LogEntry.create(
        "WARNING",
        "font_skipped",
        "Font non supportato",
        {"input": "èxample.ttf", "attempt": 2},
    )

    assert datetime.fromisoformat(entry.timestamp).tzinfo is not None
    assert entry.display_text().endswith("WARNING [font_skipped] [èxample.ttf] Font non supportato")
    assert json.loads(entry.to_json()) == {
        "timestamp": entry.timestamp,
        "level": "WARNING",
        "event": "font_skipped",
        "message": "Font non supportato",
        "context": {"input": "èxample.ttf", "attempt": 2},
    }


def test_log_entry_omits_non_string_input_from_display() -> None:
    entry = LogEntry.create("ERROR", "conversion_failed", "Failed", {"input": 42})

    assert entry.display_text().endswith("ERROR [conversion_failed] Failed")


def test_scan_worker_deduplicates_files_and_reports_batches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "fonts"
    nested = root / "nested"
    nested.mkdir(parents=True)
    paths = [root / f"font{i:02}.ttf" for i in range(20)]
    paths.append(nested / "font20.ttf")
    for path in paths:
        path.touch()
    duplicate_source = paths[0]
    monkeypatch.setattr(
        scanner_module,
        "inspect_font",
        lambda path: path.name if path != paths[1] else None,
    )
    worker = ScanWorker([Source(root, True), Source(duplicate_source)])
    progress: list[tuple[int, int]] = []
    found: list[tuple[Path, object]] = []
    worker.progress.connect(lambda done, total: progress.append((done, total)))
    worker.font_found.connect(lambda path, info: found.append((path, info)))

    worker.run()

    assert progress == [(0, 0), (0, 21), (20, 21), (21, 21)]
    assert len(found) == 20
    assert len({path for path, _ in found}) == 20
    assert all(path != paths[1] for path, _ in found)


def test_scan_worker_stops_when_interrupted_during_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "fonts"
    root.mkdir()
    for name in ("a.ttf", "b.ttf"):
        (root / name).touch()
    worker = ScanWorker([Source(root)])
    calls = 0

    def interrupted() -> bool:
        nonlocal calls
        calls += 1
        return calls == 1

    monkeypatch.setattr(worker, "isInterruptionRequested", interrupted)
    progress: list[tuple[int, int]] = []
    worker.progress.connect(lambda done, total: progress.append((done, total)))

    worker.run()

    assert progress == [(0, 0)]


def test_scan_worker_emits_failed_on_unexpected_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_iter(sources: object, recursive: bool) -> Iterator[Path]:
        raise RuntimeError("boom")
        yield  # pragma: no cover

    monkeypatch.setattr(scanner_module, "iter_files", broken_iter)
    worker = ScanWorker([Source(tmp_path)])
    failures: list[str] = []
    worker.failed.connect(failures.append)

    worker.run()

    assert failures == ["RuntimeError: boom"]


def test_material_icon_renders_tinted_pixmaps(qapp: QApplication) -> None:
    from fontvertx.gui.icons import SvgIconEngine, material_icon

    icon = material_icon("visibility", "#123456", 18, disabled_color="#abcdef")
    assert not icon.isNull()
    # Rendered from the SVG at the requested device pixel ratio, not scaled from 1x / 2x.
    for ratio in (1.0, 1.5, 2.0):
        pixmap = icon.pixmap(QSize(18, 18), ratio)
        assert pixmap.devicePixelRatio() == ratio
        assert pixmap.width() == round(18 * ratio)
    image = icon.pixmap(QSize(18, 18), 2.0).toImage()

    def opaque_colors(image: QImage) -> set[str]:
        return {
            image.pixelColor(x, y).name()
            for x in range(image.width())
            for y in range(image.height())
            if image.pixelColor(x, y).alpha() == 255
        }

    assert opaque_colors(image) == {"#123456"}
    disabled = icon.pixmap(QSize(18, 18), 2.0, QIcon.Mode.Disabled).toImage()
    assert opaque_colors(disabled) == {"#abcdef"}
    # Without a disabled color the glyph is faded, not recolored.
    plain = material_icon("visibility", "#123456")
    faded = plain.pixmap(QSize(18, 18), 1.0, QIcon.Mode.Disabled).toImage()
    assert max(faded.pixelColor(x, y).alpha() for x in range(18) for y in range(18)) < 255
    # paint() honors the target device's ratio; pixmaps are cached.
    target = QImage(36, 36, QImage.Format.Format_ARGB32_Premultiplied)
    target.setDevicePixelRatio(2.0)
    target.fill(0)
    painter = QPainter(target)
    icon.paint(painter, QRect(0, 0, 18, 18))
    painter.end()
    assert "#123456" in opaque_colors(target)
    assert icon.pixmap(QSize(18, 18), 2.0).cacheKey() == icon.pixmap(QSize(18, 18), 2.0).cacheKey()
    assert icon.actualSize(QSize(24, 24)) == QSize(24, 24)
    assert not QIcon(icon).isNull()

    engine = SvgIconEngine("visibility", "#123456", None)
    normal, off = QIcon.Mode.Normal, QIcon.State.Off
    assert engine.pixmap(QSize(18, 18), normal, off).devicePixelRatio() == 1.0
    assert engine.actualSize(QSize(20, 20), normal, off) == QSize(20, 20)
    copy = engine.clone()
    assert isinstance(copy, SvgIconEngine) and copy.key() == engine.key() == "SvgIconEngine"

    assert material_icon("does_not_exist", "#000000").isNull()


def test_main_configures_application_and_shows_window(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, Any]] = []

    class FakeApplication:
        def __init__(self, argv: list[str]) -> None:
            calls.append(("argv", argv))

        def setOrganizationName(self, value: str) -> None:
            calls.append(("organization", value))

        def setStyle(self, value: str) -> None:
            calls.append(("style", value))

        def styleHints(self) -> "FakeApplication":
            return self

        def setColorScheme(self, value: object) -> None:
            calls.append(("color_scheme", value))

        def setApplicationName(self, value: str) -> None:
            calls.append(("application", value))

        def setWindowIcon(self, value: object) -> None:
            calls.append(("icon", value))

        def setFont(self, value: object) -> None:
            calls.append(("font", value))

        def installEventFilter(self, value: object) -> None:
            calls.append(("event_filter", type(value).__name__))

        def exec(self) -> int:
            calls.append(("exec", None))
            return 7

    class FakeWindow:
        def __init__(self) -> None:
            calls.append(("window", None))

        def showMaximized(self) -> None:
            calls.append(("show", None))

    argv = ["fontvertx-gui", "--test"]
    monkeypatch.setattr(main_module.sys, "argv", argv)
    monkeypatch.setattr(main_module, "QApplication", FakeApplication)
    monkeypatch.setattr(main_module, "_app_font", lambda: "inter-font")
    monkeypatch.setattr(main_module, "_mono_family", lambda: "monospace")
    monkeypatch.setattr(main_module, "set_mono_family", lambda _family: None)
    monkeypatch.setattr(main_module, "ConverterWindow", FakeWindow)
    monkeypatch.setattr(main_module, "_set_windows_app_id", lambda: calls.append(("app_id", None)))

    assert main_module.main() == 7
    assert [name for name, _ in calls] == [
        "app_id",
        "argv",
        "style",
        "color_scheme",
        "organization",
        "application",
        "icon",
        "font",
        "window",
        "show",
        "exec",
    ]
    assert calls[2][0] == "style"
    style = calls[2][1]
    assert isinstance(style, AppStyle)
    assert style.baseStyle().name().casefold() == "fusion"
    assert calls[3][1] == main_module.Qt.ColorScheme.Light
    assert isinstance(calls[6][1], QIcon)
    assert calls[7] == ("font", "inter-font")


def test_app_font_loads_inter_and_applies_stylistic_set(qapp: QApplication) -> None:
    font = main_module._app_font()
    tag = QFont.Tag.fromString("ss02")
    assert font.family() == "Inter"
    assert font.weight() == QFont.Weight.Medium
    assert font.featureValue(tag) == 1
    assert (
        font.pointSizeF()
        == QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).pointSizeF()
    )

    def glyphs(text_font: QFont) -> list[int]:
        layout = QTextLayout("Il0", text_font)
        layout.beginLayout()
        layout.createLine()
        layout.endLayout()
        return [glyph for run in layout.glyphRuns() for glyph in run.glyphIndexes()]

    original_font = qapp.font()
    try:
        qapp.setFont(font)
        default_label = QLabel("Il0")
        default_label.ensurePolished()
        assert default_label.font().weight() == QFont.Weight.Medium
        assert QFontInfo(default_label.font()).styleName() == "Medium"
        for weight, style in ((400, "Regular"), (500, "Medium"), (600, "SemiBold"), (700, "Bold")):
            label = QLabel("Il0")
            label.setStyleSheet(f"QLabel {{ font-size: 13pt; font-weight: {weight}; }}")
            label.ensurePolished()
            assert label.font().family() == "Inter"
            assert label.font().featureValue(tag) == 1
            assert QFontInfo(label.font()).styleName() == style
            default_font = QFont(label.font())
            default_font.setFeature(tag, 0)
            assert glyphs(label.font()) != glyphs(default_font)
    finally:
        qapp.setFont(original_font)


def test_organization_headings_enable_capital_features(qapp: QApplication) -> None:
    original_font = qapp.font()
    try:
        qapp.setFont(main_module._app_font())
        dialog = OrganizationDialog("ttf2otf", (), {"family": "Family"}, ".otf")
        dialog.setStyleSheet(stylesheet())
        dialog.show()
        qapp.processEvents()
        headings = dialog.findChildren(QLabel, "organizationSection")
        assert [heading.text() for heading in headings] == [
            "Folder levels",
            "Example",
        ]
        for heading in headings:
            font = heading.font()
            assert font.family() == "Inter"
            assert font.capitalization() == QFont.Capitalization.AllUppercase
            assert font.featureValue(QFont.Tag.fromString("case")) == 1
            assert font.featureValue(QFont.Tag.fromString("cpsp")) == 1
            assert font.isFeatureSet(QFont.Tag.fromString("ss02"))
            assert font.featureValue(QFont.Tag.fromString("ss02")) == 0
        assert dialog.empty_hint.font().featureValue(QFont.Tag.fromString("ss02")) == 1
        dialog.close()
    finally:
        qapp.setFont(original_font)


def test_conversion_headings_use_uppercase_without_ss02(qapp: QApplication) -> None:
    original_font = qapp.font()
    try:
        qapp.setFont(main_module._app_font())
        selector = ConversionSelector(CONVERSIONS, group_headings=CONVERSION_GROUP_HEADINGS)
        selector.setStyleSheet(stylesheet())
        selector.show()
        qapp.processEvents()
        assert selector.combo.count() == len(CONVERSIONS) + 3
        assert selector.combo.itemText(0) == "Outlines"
    finally:
        qapp.setFont(original_font)


def test_font_list_and_instance_tree_use_regular_inter(qapp: QApplication) -> None:
    original_font = qapp.font()
    try:
        qapp.setFont(main_module._app_font())
        table = FileTable()
        tree = InstanceTree()
        for view in (table, tree):
            view.setStyleSheet(stylesheet())
            view.ensurePolished()
            assert view.font().family() == "Inter"
            assert view.font().weight() == QFont.Weight.Normal
            assert QFontInfo(view.font()).styleName() == "Regular"
            assert view.font().featureValue(QFont.Tag.fromString("ss02")) == 1
            assert view.font().kerning()
        table.horizontalHeader().ensurePolished()
        tree.header().ensurePolished()
        assert table.horizontalHeader().font().weight() == QFont.Weight.DemiBold
        assert tree.header().font().weight() == QFont.Weight.DemiBold
        parent = QTreeWidgetItem(tree, ["Font"])
        child = QTreeWidgetItem(parent, ["Instance"])
        for item in (parent, child):
            index = tree.indexFromItem(item)
            option = QStyleOptionViewItem()
            tree.initViewItemOption(option)
            tree.itemDelegate().initStyleOption(option, index)
            assert option.font.weight() == QFont.Weight.Normal
    finally:
        qapp.setFont(original_font)


@pytest.mark.parametrize("families", [None, []])
def test_app_font_falls_back_when_font_cannot_be_loaded(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    families: list[str] | None,
) -> None:
    monkeypatch.setattr(
        QFontDatabase, "addApplicationFont", lambda _path: -1 if families is None else 0
    )
    monkeypatch.setattr(QFontDatabase, "applicationFontFamilies", lambda _id: families or [])
    with caplog.at_level(logging.WARNING):
        font = main_module._app_font()
    assert font == QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont)
    assert "Could not load UI font" in caplog.text


def test_mono_family_loads_jetbrains_mono(qapp: QApplication) -> None:
    assert main_module._mono_family() == "JetBrains Mono"


@pytest.mark.parametrize("families", [None, []])
def test_mono_family_falls_back_to_fixed_font(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    families: list[str] | None,
) -> None:
    monkeypatch.setattr(
        QFontDatabase, "addApplicationFont", lambda _path: -1 if families is None else 0
    )
    monkeypatch.setattr(QFontDatabase, "applicationFontFamilies", lambda _id: families or [])
    with caplog.at_level(logging.WARNING):
        family = main_module._mono_family()
    assert family == QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    assert "Could not load monospaced font" in caplog.text


def test_monospaced_font_is_applied_to_paths_log_counters_badges_and_chips() -> None:
    sheet = stylesheet()
    for selector in (
        "QLabel#pathLabel",
        "QLabel#filenamePreview",
        "QLineEdit#destinationEdit",
        "QListWidget#conversionLog",
        "QLabel#runCounter",
        "QLabel#runFile",
        "QLabel#formatChip",
        "QLabel#modifiedChip",
        'QLabel#stepHint[mono="true"]',
        "QLabel#organizationLevelNumber,\nQLabel#cardNumber",
    ):
        # Anchored at a line start: "QFrame#dropZone QLabel#formatChip {" also matches.
        block = sheet[sheet.index(f"\n{selector} {{") :].split("}", 1)[0]
        assert f'font-family: "{mono_family()}"' in block, selector
    root = sheet[: sheet.index("}")]
    assert f'font-family: "{UI_FONT_FAMILY}"' in root


def test_app_icon_assets_are_bundled() -> None:
    assets = Path(main_module.__file__).parent / "assets"
    expected = [f"fontvertx-{size}.png" for size in main_module.APP_ICON_SIZES]
    expected += ["fontvertx.ico", "fontvertx.svg", "fontvertx-small.svg"]
    assert [name for name in expected if not (assets / name).is_file()] == []


def test_app_icon_loads_bundled_pngs(qapp: QApplication) -> None:
    icon = main_module._app_icon()
    assert not icon.isNull()
    assert icon.availableSizes() == [QSize(size, size) for size in main_module.APP_ICON_SIZES]


def _write_png(path: Path, size: int) -> None:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("#2F5DA8"))
    assert pixmap.save(str(path), "PNG")


def test_app_icon_builds_all_png_sizes(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    for size in main_module.APP_ICON_SIZES:
        _write_png(assets / f"fontvertx-{size}.png", size)
    monkeypatch.setattr(main_module, "__file__", str(tmp_path / "__main__.py"))
    icon = main_module._app_icon()
    assert icon.availableSizes() == [QSize(size, size) for size in main_module.APP_ICON_SIZES]


def test_app_icon_falls_back_to_ico(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets = tmp_path / "assets"
    assets.mkdir()
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor("#2F5DA8"))
    assert pixmap.save(str(assets / "fontvertx.ico"), "ICO")
    monkeypatch.setattr(main_module, "__file__", str(tmp_path / "__main__.py"))
    icon = main_module._app_icon()
    assert not icon.isNull()


def test_app_icon_missing_warns(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(main_module, "__file__", str(tmp_path / "__main__.py"))
    assert main_module._app_icon().isNull()
    assert "Application icon not found" in caplog.text


def test_windows_app_id_called_only_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    windll = SimpleNamespace(
        shell32=SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=calls.append)
    )
    monkeypatch.setattr(main_module.ctypes, "windll", windll, raising=False)
    monkeypatch.setattr(main_module.sys, "platform", "linux")
    main_module._set_windows_app_id()
    assert not calls
    monkeypatch.setattr(main_module.sys, "platform", "win32")
    main_module._set_windows_app_id()
    assert calls == ["Fontvertx.Fontvertx"]


@pytest.mark.parametrize("error", [AttributeError("missing"), OSError("unavailable")])
def test_windows_app_id_failure_is_nonfatal(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    def fail(_value: str) -> None:
        raise error

    monkeypatch.setattr(main_module.sys, "platform", "win32")
    monkeypatch.setattr(
        main_module.ctypes,
        "windll",
        SimpleNamespace(shell32=SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=fail)),
        raising=False,
    )
    with caplog.at_level(logging.WARNING):
        main_module._set_windows_app_id()
    assert "Could not set Windows application ID" in caplog.text
