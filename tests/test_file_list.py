import gc
import weakref
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from fontvertx.gui.file_list import (
    FontBadgeDelegate,
    FontFileList,
    FontFilterProxyModel,
    FontNameDelegate,
    FontTableModel,
)
from fontvertx.gui.scanner import Source
from fontvertx.gui.styles import LIGHT
from fontvertx.gui.widgets import FileTable
from fontvertx.inspection import FontInfo, inspect_font

TTF_PROFILE = ("ttf2otf", False)
HIDING_PROFILE = ("ttf2otf", True)
WEB_PROFILE = ("woff2ft", False)


def ttf_info(path: str = "a.ttf", upm: int | None = 1000) -> FontInfo:
    return FontInfo(Path(path), "SFNT", "TrueType", upm)


def otf_info(path: str = "b.otf") -> FontInfo:
    return FontInfo(Path(path), "SFNT", "PostScript", 1000)


def ttc_info() -> FontInfo:
    return FontInfo(Path("c.ttc"), "SFNT", "TrueType", None, collection=True, num_fonts=2)


@pytest.fixture
def file_list(qapp: QApplication) -> Iterator[FontFileList]:
    # The FileTable is a top-level widget (the FontFileList is its child): the autouse
    # cleanup in conftest.py deletes both once the scan threads are stopped here.
    files = FontFileList(FileTable(), lambda: TTF_PROFILE)
    yield files
    files.shutdown()


def fill(file_list: FontFileList) -> None:
    for info in (ttf_info("b.ttf", 2048), otf_info("a.otf"), ttc_info()):
        file_list.add_font(info.path, info.path.name, info, True)


def test_model_exposes_row_data_roles(file_list: FontFileList) -> None:
    fill(file_list)
    model = file_list.model

    def index(row: int, column: int = 0) -> QModelIndex:
        return model.index(row, column)

    assert model.rowCount() == 3
    assert model.rowCount(index(0)) == 0
    assert model.columnCount() == 6
    assert model.columnCount(index(0)) == 0
    assert model.HEADERS == ("Name", "Format", "Outlines", "UPM", "Family", "Style")
    assert model.headerData(1, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Format"
    assert model.headerData(0, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole) is None
    assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.TextAlignmentRole) == (
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )
    centered = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    assert (
        model.headerData(3, Qt.Orientation.Horizontal, Qt.ItemDataRole.TextAlignmentRole)
        == centered
    )
    assert model.data(index(0, 3), Qt.ItemDataRole.TextAlignmentRole) == centered
    assert model.data(index(0, 0), Qt.ItemDataRole.TextAlignmentRole) is None

    assert model.data(QModelIndex()) is None
    assert [model.data(index(0, c), Qt.ItemDataRole.DisplayRole) for c in range(4)] == [
        "b.ttf",
        "SFNT",
        "TrueType",
        "2048",
    ]
    assert model.data(index(2, 1), Qt.ItemDataRole.DisplayRole) == "TTC (2)"
    assert model.data(index(2, 3), Qt.ItemDataRole.DisplayRole) == "Mixed"

    assert model.data(index(0), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    assert model.data(index(1), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    assert model.data(index(0, 1), Qt.ItemDataRole.CheckStateRole) is None
    assert model.data(index(1), Qt.ItemDataRole.UserRole + 1) == "Not a TrueType font"
    assert model.data(index(0), Qt.ItemDataRole.UserRole) == str(Path("b.ttf"))
    assert model.data(index(0), Qt.ItemDataRole.UserRole + 2).path == Path("b.ttf")
    tooltip = Qt.ItemDataRole.ToolTipRole
    # Column 0: the path (plus the reason), never the name already shown in the cell.
    assert model.data(index(0), tooltip) == str(Path("b.ttf"))
    assert model.data(index(1), tooltip) == f"{model.rows[1].path}\nNot a TrueType font"
    for row in range(model.rowCount()):
        data = model.rows[row]
        tip = model.data(index(row), tooltip)
        assert tip.split("\n")[0] == str(data.path)
        # A long reason may wrap: compare the words.
        expected = f"{data.path} {data.reason or ''}"
        assert " ".join(tip.split()) == " ".join(expected.split())
    # Only the name column has a tooltip; the other cells show everything already.
    for row in range(model.rowCount()):
        for column in range(1, model.columnCount()):
            assert model.data(index(row, column), tooltip) is None
    assert model.data(index(0), Qt.ItemDataRole.ForegroundRole) is None
    assert (
        model.data(index(1), Qt.ItemDataRole.ForegroundRole).color().name() == LIGHT.text_disabled
    )
    assert model.data(index(0), Qt.ItemDataRole.DecorationRole) is None


def test_model_flags_depend_on_compatibility(file_list: FontFileList) -> None:
    fill(file_list)
    model = file_list.model

    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags
    assert model.flags(model.index(0, 0)) & Qt.ItemFlag.ItemIsUserCheckable
    assert model.flags(model.index(1, 0)) & Qt.ItemFlag.ItemIsEnabled
    assert not model.flags(model.index(1, 0)) & Qt.ItemFlag.ItemIsUserCheckable
    assert model.flags(model.index(1, 1)) & Qt.ItemFlag.ItemIsEnabled
    assert not model.flags(model.index(0, 1)) & Qt.ItemFlag.ItemIsUserCheckable


def test_set_data_toggles_only_compatible_checkbox(file_list: FontFileList) -> None:
    fill(file_list)
    model = file_list.model
    changes: list[object] = []
    model.dataChanged.connect(lambda *args: changes.append(args))
    check_role = Qt.ItemDataRole.CheckStateRole

    assert model.setData(model.index(0, 0), Qt.CheckState.Unchecked, check_role)
    assert not model.rows[0].checked
    assert len(changes) == 1
    assert model.setData(model.index(0, 0), Qt.CheckState.Unchecked, check_role)
    assert len(changes) == 1
    assert model.setData(model.index(0, 0), Qt.CheckState.Checked.value, check_role)
    assert model.rows[0].checked

    assert not model.setData(model.index(1, 0), Qt.CheckState.Checked, check_role)
    assert not model.setData(model.index(0, 1), Qt.CheckState.Checked, check_role)
    assert not model.setData(model.index(0, 0), "x", Qt.ItemDataRole.EditRole)
    assert not model.setData(QModelIndex(), Qt.CheckState.Checked, check_role)


def test_set_checks_skips_incompatible_and_unchanged_rows(file_list: FontFileList) -> None:
    fill(file_list)
    model = file_list.model
    changes: list[object] = []
    model.dataChanged.connect(lambda *args: changes.append(args))

    model.set_checks([0, 1], True)
    assert changes == []
    model.set_checks([0, 1, 2], False)
    assert [row.checked for row in model.rows] == [False, True, True]
    assert len(changes) == 1


def test_update_compatibility_recomputes_reasons(file_list: FontFileList) -> None:
    fill(file_list)
    model = file_list.model
    model.update_compatibility(WEB_PROFILE)

    assert all(row.reason is not None for row in model.rows)
    assert model.rows[0].reason == "Not a web font"

    model.clear()
    model.update_compatibility(WEB_PROFILE)
    assert model.rowCount() == 0


def test_proxy_filters_and_sorts_rows(file_list: FontFileList) -> None:
    fill(file_list)
    proxy = file_list.proxy

    assert proxy.rowCount() == 3
    assert [proxy.index(r, 0).data() for r in range(3)] == ["a.otf", "b.ttf", "c.ttc"]

    proxy.setFilterFixedString("postscript")
    assert [proxy.index(r, 0).data() for r in range(proxy.rowCount())] == ["a.otf"]
    proxy.setFilterFixedString("2048")
    assert [proxy.index(r, 0).data() for r in range(proxy.rowCount())] == ["b.ttf"]
    proxy.setFilterFixedString("")

    proxy.sort(3, Qt.SortOrder.AscendingOrder)
    assert [proxy.index(r, 3).data() for r in range(2)] == ["1000", "2048"]

    file_list.apply_compatibility()
    assert proxy.rowCount() == 3

    file_list.profile = lambda: HIDING_PROFILE
    file_list.apply_compatibility()
    assert [proxy.index(r, 0).data() for r in range(proxy.rowCount())] == ["b.ttf"]
    assert file_list.is_visible(Path("b.ttf"))
    assert not file_list.is_visible(Path("a.otf"))
    assert file_list.index_for_path(Path("missing")) == QModelIndex()


def test_name_delegate_draws_reason_only_when_space_permits(
    file_list: FontFileList, monkeypatch: pytest.MonkeyPatch
) -> None:
    fill(file_list)
    delegate = file_list.view.itemDelegateForColumn(0)
    assert isinstance(delegate, FontNameDelegate)
    option = QStyleOptionViewItem()
    option.initFrom(file_list.view)
    option.widget = file_list.view
    image = QImage(800, 40, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    drawn: list[tuple[QRect, str, QColor]] = []
    original = QPainter.drawText

    def capture(self: QPainter, rect: QRect, flags: int, text: str) -> None:
        drawn.append((rect, text, self.pen().color()))
        original(self, rect, flags, text)

    monkeypatch.setattr(QPainter, "drawText", capture)
    incompatible = file_list.index_for_path(Path("a.otf"))
    compatible = file_list.index_for_path(Path("b.ttf"))
    option.rect = QRect(0, 0, 500, 35)
    delegate.paint(painter, option, compatible)
    assert not drawn
    delegate.paint(painter, option, incompatible)
    assert drawn[-1][1] == "Not a TrueType font"
    assert drawn[-1][0].width() >= 60
    assert drawn[-1][2].name() == LIGHT.text_muted
    drawn.clear()
    option.rect = QRect(0, 0, 170, 35)
    delegate.paint(painter, option, incompatible)
    assert drawn and drawn[-1][1].endswith("…")
    drawn.clear()
    option.rect = QRect(0, 0, 100, 35)
    delegate.paint(painter, option, incompatible)
    assert not drawn
    long_name = otf_info("a-very-long-font-name-that-does-not-fit.otf")
    file_list.add_font(long_name.path, long_name.path.name, long_name, True)
    option.rect = QRect(0, 0, 170, 35)
    delegate.paint(painter, option, file_list.index_for_path(long_name.path))
    assert not drawn
    painter.end()


def test_format_and_outline_badges_use_token_colors(file_list: FontFileList) -> None:
    info = FontInfo(Path("a.otf"), "OTF", "PostScript", 1000)
    file_list.add_font(info.path, info.path.name, info, True)
    model = file_list.model
    numeric_font = model.data(model.index(0, 3), Qt.ItemDataRole.FontRole)
    assert numeric_font.family() == "Inter"
    assert not numeric_font.fixedPitch()
    assert numeric_font.featureValue(QFont.Tag.fromString("tnum")) == 1
    assert model.data(model.index(0, 3), Qt.ItemDataRole.TextAlignmentRole) == (
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    )
    assert model.headerData(3, Qt.Orientation.Horizontal, Qt.ItemDataRole.TextAlignmentRole) == (
        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
    )

    view = file_list.view
    option = QStyleOptionViewItem()
    option.initFrom(view)
    option.widget = view
    option.rect = QRect(0, 0, 100, 30)
    # Format and outline chips: an accent-tint pill with accent text, on the row
    # background. A single pixel at the center may fall on a letter (text metrics differ
    # between systems), so look at all painted pixels except the row background (the
    # corner color, which the pill never reaches): the pill covers more area than the text.
    for column in (1, 2):
        image = QImage(100, 30, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        delegate = view.itemDelegateForColumn(column)
        assert isinstance(delegate, FontBadgeDelegate)
        delegate.paint(painter, option, model.index(0, column))
        painter.end()
        row_background = image.pixelColor(0, 0).name()
        colors = Counter(
            color.name()
            for x in range(image.width())
            for y in range(image.height())
            if (color := image.pixelColor(x, y)).alpha() == 255 and color.name() != row_background
        )
        assert colors.most_common(1)[0][0] == LIGHT.accent_tint, column
        # The accent text is antialiased: its darkest pixels are close to the accent,
        # not necessarily equal to it (FreeType renders no exact match).
        accent = QColor(LIGHT.accent)
        assert any(
            max(
                abs(color.red() - accent.red()),
                abs(color.green() - accent.green()),
                abs(color.blue() - accent.blue()),
            )
            <= 16
            for color in map(QColor, colors)
        ), column


def test_proxy_sorts_upm_numerically(qapp: QApplication) -> None:
    model = FontTableModel()
    for path, upm in (("a.ttf", 1000), ("b.ttf", 2048), ("c.ttf", 16)):
        info = ttf_info(path, upm)
        model.add_font(info.path, path, info, True, TTF_PROFILE)
    proxy = FontFilterProxyModel()
    proxy.setSourceModel(model)

    proxy.sort(3, Qt.SortOrder.AscendingOrder)
    assert [proxy.index(r, 3).data() for r in range(3)] == ["16", "1000", "2048"]
    proxy.sort(0, Qt.SortOrder.DescendingOrder)
    assert [proxy.index(r, 0).data() for r in range(3)] == ["c.ttf", "b.ttf", "a.ttf"]


def test_optional_columns_filter_and_sort_even_when_hidden(file_list: FontFileList) -> None:
    for path, family, style in (
        ("a.ttf", "Zulu", "Light"),
        ("b.ttf", "alpha", "Regular"),
        ("c.ttf", "Beta", "Bold"),
    ):
        info = FontInfo(Path(path), "TTF", "TrueType", 1000, family=family, style=style)
        file_list.add_font(info.path, path, info, True)
    proxy = file_list.proxy
    assert file_list.view.isColumnHidden(4) and file_list.view.isColumnHidden(5)
    assert file_list.model.index(0, 4).data() == "Zulu"
    assert file_list.model.index(0, 5).data() == "Light"
    for text, expected in (("ALPHA", "b.ttf"), ("bold", "c.ttf")):
        proxy.setFilterFixedString(text)
        assert proxy.rowCount() == 1
        assert proxy.index(0, 0).data() == expected
    proxy.setFilterFixedString("")
    proxy.sort(4, Qt.SortOrder.AscendingOrder)
    assert [proxy.index(r, 0).data() for r in range(3)] == ["b.ttf", "c.ttf", "a.ttf"]
    proxy.sort(5, Qt.SortOrder.DescendingOrder)
    assert [proxy.index(r, 0).data() for r in range(3)] == ["b.ttf", "a.ttf", "c.ttf"]


def test_selection_helpers(file_list: FontFileList) -> None:
    fill(file_list)

    assert file_list.row_count == 3
    assert file_list.compatible_count() == 1
    assert file_list.selected_paths() == [Path("b.ttf")]
    assert file_list.remember_checks() == {
        Path("b.ttf"): True,
        Path("a.otf"): True,
        Path("c.ttc"): True,
    }
    assert [row.path.name for row in file_list.rows()] == ["b.ttf", "a.otf", "c.ttc"]
    assert file_list.path_for_index(file_list.proxy.index(0, 0)) == Path("a.otf")

    assert file_list.visible_check_state() == Qt.CheckState.Checked
    file_list.set_visible_checks(False)
    assert file_list.visible_check_state() == Qt.CheckState.Unchecked
    assert file_list.selected_paths() == []


def test_visible_check_state_reports_partial_and_none(file_list: FontFileList) -> None:
    assert file_list.visible_check_state() is None

    file_list.add_font(Path("a.ttf"), "a.ttf", ttf_info("a.ttf"), True)
    file_list.add_font(Path("b.ttf"), "b.ttf", ttf_info("b.ttf"), False)
    assert file_list.visible_check_state() == Qt.CheckState.PartiallyChecked

    file_list.clear()
    assert file_list.row_count == 0


def test_scan_reports_progress_fonts_and_finish(
    file_list: FontFileList, fonts_dir: Path, qtbot_wait: Callable[..., None]
) -> None:
    found: list[Path] = []
    progress: list[tuple[int, int]] = []
    finished: list[bool] = []
    file_list.font_found.connect(lambda path, info: found.append(path))
    file_list.progress.connect(lambda done, total: progress.append((done, total)))
    file_list.scan_finished.connect(lambda: finished.append(True))

    file_list.start([Source(fonts_dir), Source(fonts_dir / "IBMPlexSans.ttc")])
    assert file_list.scanning
    qtbot_wait(lambda: bool(finished))

    assert not file_list.scanning
    assert {path.name for path in found} == {
        "IBMPlexSans-Regular.ttf",
        "IBMPlexSans-Regular.otf",
        "IBMPlexSans-Regular-Latin1.woff",
        "IBMPlexSans-Regular-Latin1.woff2",
        "IBMPlexSans.ttc",
        "TestVF.ttf",
    }
    assert len(found) == 6
    assert progress[0] == (0, 0)
    assert progress[-1][0] == progress[-1][1]
    file_list.shutdown()


def test_stopped_and_shut_down_scans_release_their_workers(
    file_list: FontFileList, fonts_dir: Path, qtbot_wait: Callable[..., None]
) -> None:
    # A worker must not be left in a reference cycle with its connected lambdas: the
    # garbage collector could then destroy the QThread later, from another thread.
    # Stopped workers are released by the queued finished signal (_on_finished
    # disconnects the lambdas), on the next pass of the event loop: no collector needed.
    gc.disable()
    try:
        finished: list[bool] = []
        file_list.scan_finished.connect(lambda: finished.append(True))
        file_list.start([Source(fonts_dir)])
        first = weakref.ref(file_list._worker)
        qtbot_wait(lambda: bool(finished))
        assert first() is None  # released by _on_finished

        # Stopped after its thread ended but before its finished signal was handled.
        file_list.start([Source(fonts_dir)])
        worker = file_list._worker
        assert worker is not None
        worker.wait()
        second = weakref.ref(worker)
        del worker
        file_list.stop()

        # Stopped while running, then released by shutdown().
        file_list.start([Source(fonts_dir)])
        third = weakref.ref(file_list._worker)
        file_list.stop()
        file_list.shutdown()
        assert file_list._retired_workers == []
        QApplication.processEvents()  # pending queued calls may still hold a worker
        assert second() is None
        assert third() is None
    finally:
        gc.enable()


def test_stop_ignores_results_from_retired_scan(
    file_list: FontFileList,
    fonts_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan_started = Event()
    resume_scan = Event()

    def blocked_inspect(path: Path) -> FontInfo | None:
        scan_started.set()
        resume_scan.wait()
        return inspect_font(path)

    monkeypatch.setattr("fontvertx.gui.scanner.inspect_font", blocked_inspect)
    file_list.stop()
    file_list.cancel()

    file_list.start([Source(fonts_dir, True)])
    worker = file_list._worker
    assert worker is not None
    try:
        assert scan_started.wait(timeout=5)
        file_list.cancel()
        assert worker.isInterruptionRequested()
        file_list.stop()
        assert not file_list.scanning
    finally:
        resume_scan.set()
    file_list.shutdown()

    info = inspect_font(fonts_dir / "IBMPlexSans-Regular.ttf")
    assert info is not None
    stale: list[Path] = []
    file_list.font_found.connect(lambda path, _: stale.append(path))
    file_list._on_font_found(worker, info.path, info)
    file_list._on_progress(worker, 1, 1)
    assert stale == []
