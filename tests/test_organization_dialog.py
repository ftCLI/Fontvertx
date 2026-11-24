import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QLabel, QPushButton, QWidget
from shiboken6 import isValid

from fontvertx.gui import organization_dialog
from fontvertx.gui.organization_dialog import OrganizationDialog
from fontvertx.gui.styles import LIGHT, stylesheet

VALUES = {
    "family": "Sample Family",
    "format": "woff",
    "outline": "tt",
    "upm": "100",
    "tolerance": "1.5",
    "simplify": "2",
}


def test_reorder_levels_animate_highlight_follow_focus_and_close_cleanly(
    qapp: QApplication,
) -> None:
    dialog = OrganizationDialog(
        "ttf2otf",
        (("family",), ("format",), ("outline",)),
        VALUES,
        ".otf",
    )
    dialog.show()
    QApplication.processEvents()
    moved = dialog._rows[0]
    final_y = dialog._rows[1].widget.y()

    moved.move_down.setFocus()
    QTest.keyClick(moved.move_down, Qt.Key.Key_Space)

    assert dialog.levels == (("format",), ("family",), ("outline",))
    assert dialog.preview.plain_path() == "woff/Sample Family/tt/font.otf"
    assert dialog._swap_animation is not None
    assert dialog._swap_animation.running()
    assert moved.widget.highlight_color.alpha() == 255
    QTest.qWait(50)
    assert 0 < moved.widget.highlight_color.alpha() < 255
    assert 0 < moved.widget.y() < final_y
    assert dialog.focusWidget() is moved.move_down

    dialog.reject()
    assert dialog._swap_animation is None
    assert moved.widget.y() == final_y


def test_reorder_criteria_uses_same_move_animation_and_rapid_clicks(
    qapp: QApplication,
) -> None:
    dialog = OrganizationDialog(
        "ttf2otf",
        (("family", "format", "outline"),),
        VALUES,
        ".otf",
    )
    dialog.show()
    QApplication.processEvents()
    row = dialog._rows[0]
    moved = row.combos[0]
    original_x = moved.parentWidget().x()
    move_right = row.criterion_moves[moved][1]
    move_left = row.criterion_moves[moved][0]

    move_right.setFocus()
    QTest.keyClick(move_right, Qt.Key.Key_Space)
    assert dialog.levels == (("format", "family", "outline"),)
    assert dialog.focusWidget() is move_right
    assert dialog._swap_animation is not None
    QTest.qWait(80)
    assert moved.parentWidget().x() > original_x

    for _ in range(10):
        button = move_right if move_right.isEnabled() else move_left
        button.setFocus()
        QTest.keyClick(button, Qt.Key.Key_Space)

    assert dialog.levels == (("format", "family", "outline"),)
    assert dialog._swap_animation is not None
    assert dialog.focusWidget() in (move_left, move_right)


@pytest.mark.parametrize("kind", ["level", "criterion", "defaults"])
@pytest.mark.parametrize("completed", [False, True])
def test_removing_items_finishes_swap_before_deletion(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, kind: str, completed: bool
) -> None:
    monkeypatch.setattr(organization_dialog, "_animations_enabled", lambda: True)
    levels = (("family", "format"),) if kind == "criterion" else (("family",), ("format",))
    dialog = OrganizationDialog("ttf2otf", levels, VALUES, ".otf")
    dialog.show()
    QApplication.processEvents()
    row = dialog._rows[0]
    if kind == "criterion":
        combo = row.combos[0]
        removed = combo.parentWidget()
        row.criterion_moves[combo][1].click()
    else:
        removed = row.widget
        row.move_down.click()

    animation = dialog._swap_animation
    assert animation is not None
    assert animation.group is not None
    if completed:
        animation.group.setCurrentTime(animation.group.duration())
    if kind == "criterion":
        dialog._remove_criterion(row, combo)
    elif kind == "level":
        dialog._remove_level(row)
    else:
        dialog._restore_defaults()

    assert dialog._swap_animation is None
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert removed is not None and not isValid(removed)
    dialog.reject()
    assert not dialog.isVisible()


@pytest.mark.parametrize("deleted_index", [0, 1])
@pytest.mark.parametrize("completed", [False, True])
def test_swap_finish_tolerates_deleted_widget(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    deleted_index: int,
    completed: bool,
) -> None:
    monkeypatch.setattr(organization_dialog, "_animations_enabled", lambda: True)
    dialog = OrganizationDialog("ttf2otf", (("family",), ("format",)), VALUES, ".otf")
    dialog.show()
    QApplication.processEvents()
    dialog._rows[0].move_down.click()
    animation = dialog._swap_animation
    assert animation is not None and animation.group is not None
    if completed:
        animation.group.setCurrentTime(animation.group.duration())
    deleted = animation.widgets[deleted_index]
    deleted.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(deleted)

    animation.finish()
    animation.finish()
    assert animation.group is None
    assert "Traceback" not in capsys.readouterr().err
    dialog.reject()
    assert not dialog.isVisible()


def test_reorder_respects_animations_setting(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(organization_dialog, "ANIMATIONS_ENABLED", False)
    dialog = OrganizationDialog(
        "ttf2otf",
        (("family",), ("format",)),
        VALUES,
        ".otf",
    )
    dialog.show()
    QApplication.processEvents()

    moved = dialog._rows[0]
    moved.move_down.click()

    assert dialog.levels == (("format",), ("family",))
    assert dialog._swap_animation is None


def test_organization_dialog_orders_levels_and_previews_path(qapp: object) -> None:
    dialog = OrganizationDialog(
        "ttf2otf",
        (("family", "format"), ("outline", "upm")),
        {
            "family": "Sample Family",
            "format": "woff",
            "outline": "tt",
            "upm": "100",
            "tolerance": "1.5",
            "simplify": "2",
        },
        ".woff",
    )

    assert dialog.empty_hint.isHidden()
    assert dialog.preview.plain_path() == "Sample Family_woff/tt_upm_100/font.woff"
    dialog._rows[1].move_up.click()
    assert dialog.levels == (("outline", "upm"), ("family", "format"))
    assert dialog.preview.plain_path() == "tt_upm_100/Sample Family_woff/font.woff"

    dialog.add_level_button.click()
    assert dialog.levels[-1] == ("tolerance",)


def test_empty_state_and_preview_escape(qapp: object) -> None:
    dialog = OrganizationDialog(
        "ttf2otf", (), {"family": "Family & <Name>", "format": "opentype"}, ".otf"
    )
    assert not dialog.empty_hint.isHidden()
    assert dialog.preview.plain_path() == "font.otf"
    assert not dialog.preview_section.isHidden()

    dialog.add_level_button.click()
    assert dialog.empty_hint.isHidden()
    assert dialog.preview.plain_path() == "Family & Name/font.otf"
    assert not dialog.preview_section.isHidden()
    assert dialog.preview.toolTip() == dialog.preview.plain_path()

    row = dialog._rows[0]
    dialog._remove_criterion(row, row.combos[0])
    assert dialog.levels == ()
    assert not dialog.empty_hint.isHidden()
    assert dialog.preview.plain_path() == "font.otf"
    assert not dialog.preview_section.isHidden()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_preview_is_shared_selectable_and_always_visible(qapp: QApplication) -> None:
    dialog = OrganizationDialog("ttf2otf", (), VALUES, ".otf")
    dialog.preview_section.setMaximumWidth(220)
    dialog.setStyleSheet(stylesheet())
    dialog.show()
    QTest.qWait(30)
    layout = dialog.layout()
    assert layout is not None
    item = layout.itemAt(layout.indexOf(dialog.preview_section))
    assert item is not None and not item.isEmpty()
    assert dialog.preview.plain_path() == "font.otf"
    dialog._add_level(("family", "format", "outline"))
    dialog._add_level(("upm", "tolerance", "simplify"))
    QTest.qWait(50)
    assert not item.isEmpty()
    assert dialog.preview.objectName() == "examplePath"
    assert dialog.preview.toolTip() == dialog.preview.plain_path()
    assert dialog.preview.cursor().shape() == Qt.CursorShape.ArrowCursor
    document = QTextDocument()
    document.setHtml(dialog.preview.text())
    block = document.begin()
    assert block.next().isValid()
    assert block.text().endswith("/\u200b")
    assert block.next().blockFormat().leftMargin() == 0
    assert f"color:{LIGHT.header_group}" in dialog.preview.text()
    preview = dialog.preview
    QTest.mousePress(preview, Qt.MouseButton.LeftButton, pos=QPoint(12, 10))
    QTest.mouseMove(preview, QPoint(preview.width() - 3, preview.height() - 5), 20)
    QTest.mouseRelease(
        preview, Qt.MouseButton.LeftButton, pos=QPoint(preview.width() - 3, preview.height() - 5)
    )
    QTest.keyClick(preview, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert qapp.clipboard().text() == preview.plain_path()
    dialog._restore_defaults()
    assert not dialog.preview_section.isHidden()
    assert not item.isEmpty()
    assert dialog.preview.plain_path() == "font.otf"
    dialog.close()


def test_preview_layout_spacing_and_order(qapp: QApplication) -> None:
    dialog = OrganizationDialog("ttf2otf", (("family",), ("format",)), VALUES, ".otf")
    dialog.setStyleSheet(stylesheet())
    dialog.show()
    QTest.qWait(50)
    section = dialog.preview_section
    heading = section.findChild(QLabel, "organizationSection")
    hint = section.findChild(QLabel, "exampleHint")
    assert heading is not None and hint is not None
    assert heading.text() == "Example"
    assert heading.y() + heading.height() + 6 == hint.y()
    assert hint.y() + hint.height() + 6 == dialog.preview.y()
    assert (
        dialog._rows[-1].widget.y() + dialog._rows[-1].widget.height() + 8
        == dialog.add_level_button.y()
    )
    assert (
        dialog.add_level_button.y() + dialog.add_level_button.height() + 18
        == section.y() + heading.y()
    )
    assert section.y() + dialog.preview.y() + dialog.preview.height() + 16 <= dialog.buttons.y()
    dialog.close()


def _assert_criteria_fit(dialog: OrganizationDialog) -> None:
    for row in dialog._rows:
        for combo in row.combos:
            wrapper = combo.parentWidget()
            assert wrapper is not None
            for widget in (combo, *row.criterion_moves[combo], row.criterion_removes[combo]):
                assert wrapper.rect().contains(widget.geometry())


@pytest.mark.parametrize("initial_levels", [(), (("family", "format", "outline"),)])
def test_criteria_fit_after_layout_changes(
    qapp: QApplication, initial_levels: tuple[tuple[str, ...], ...]
) -> None:
    dialog = OrganizationDialog(
        "ttf2otf",
        initial_levels,
        {
            "family": "Sample Family",
            "format": "opentype",
            "outline": "ps",
            "upm": "1000",
            "tolerance": "1",
            "simplify": "0",
        },
        ".otf",
    )
    dialog.setStyleSheet("QComboBox { border: 1px solid; padding: 6px 10px; min-height: 20px; }")
    dialog.show()
    QApplication.processEvents()
    _assert_criteria_fit(dialog)

    if not initial_levels:
        dialog.add_level_button.click()
    row = dialog._rows[0]
    while row.add_criterion.isEnabled():
        row.add_criterion.click()
        QTest.qWait(10)
        _assert_criteria_fit(dialog)

    dialog.resize(1000, dialog.height() + 100)
    QApplication.processEvents()
    user_height = dialog.height()
    dialog._remove_criterion(row, row.combos[-1])
    QApplication.processEvents()
    assert dialog.height() == user_height
    dialog.resize(680, dialog.height())
    QApplication.processEvents()
    _assert_criteria_fit(dialog)
    dialog.resize(dialog.width(), dialog.minimumHeight())
    QTest.qWait(10)
    _assert_criteria_fit(dialog)


def test_criteria_fit_when_adding_folder_levels(qapp: QApplication) -> None:
    dialog = OrganizationDialog(
        "ttf2otf",
        (),
        {
            "family": "Family",
            "format": "opentype",
            "outline": "ps",
            "upm": "1000",
            "tolerance": "1",
            "simplify": "0",
        },
        ".otf",
    )
    dialog.show()
    QApplication.processEvents()
    while dialog.add_level_button.isEnabled():
        dialog.add_level_button.click()
        QTest.qWait(10)
        _assert_criteria_fit(dialog)


@pytest.mark.parametrize(
    "key",
    [Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter],
)
def test_add_level_button_activates_with_space_and_enter(qapp: QApplication, key: Qt.Key) -> None:
    dialog = OrganizationDialog("ft2wf", (), {"family": "Family"}, ".woff")
    dialog.show()
    dialog.add_level_button.setFocus()
    QApplication.processEvents()

    QTest.keyClick(dialog.add_level_button, key)

    assert len(dialog._rows) == 1
    assert dialog.isVisible()


def test_reorder_criteria_updates_preview_and_preserves_levels(qapp: object) -> None:
    dialog = OrganizationDialog(
        "ttf2otf",
        (("family", "format", "outline"), ("upm",)),
        {"family": "Family", "format": "opentype", "outline": "ps", "upm": "1000"},
        ".otf",
    )
    row = dialog._rows[0]
    family, format_, outline = row.combos
    assert not row.criterion_moves[family][0].isEnabled()
    assert not row.criterion_moves[outline][1].isEnabled()
    assert all(
        not button.isEnabled()
        for button in dialog._rows[1].criterion_moves[dialog._rows[1].combos[0]]
    )

    row.criterion_moves[family][1].click()
    assert dialog.levels == (("format", "family", "outline"), ("upm",))
    assert dialog.preview.plain_path() == "opentype_Family_ps/upm_1000/font.otf"
    row.criterion_moves[outline][0].click()
    assert dialog.levels == (("format", "outline", "family"), ("upm",))
    assert dialog.preview.plain_path() == "opentype_ps_Family/upm_1000/font.otf"
    row.criterion_moves[format_][1].click()
    assert dialog.levels == (("outline", "format", "family"), ("upm",))
    assert dialog.preview.plain_path() == "ps_opentype_Family/upm_1000/font.otf"
    dialog.accept()
    reopened = OrganizationDialog("ttf2otf", dialog.levels, dialog._values, ".otf")
    assert reopened.levels == (("outline", "format", "family"), ("upm",))
    assert reopened.preview.plain_path() == dialog.preview.plain_path()

    dialog._remove_criterion(row, format_)
    assert dialog.levels == (("outline", "family"), ("upm",))
    assert not row.criterion_moves[outline][0].isEnabled()
    assert not row.criterion_moves[family][1].isEnabled()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_exhausted_criteria_disable_add_buttons_until_one_is_removed(qapp: object) -> None:
    dialog = OrganizationDialog(
        "ft2wf",
        (("family", "format"), ("outline",)),
        {"family": "Family", "format": "woff", "outline": "tt"},
        ".woff",
    )
    assert not dialog.criteria_exhausted_hint.isHidden()
    assert not dialog.add_level_button.isEnabled()
    assert all(not row.add_criterion.isEnabled() for row in dialog._rows)
    assert dialog.levels == (("family", "format"), ("outline",))

    row = dialog._rows[0]
    dialog._remove_criterion(row, row.combos[0])
    assert dialog.criteria_exhausted_hint.isHidden()
    assert dialog.add_level_button.isEnabled()
    assert all(row.add_criterion.isEnabled() for row in dialog._rows)
    dialog.add_level_button.click()
    assert not dialog.criteria_exhausted_hint.isHidden()
    assert not dialog.add_level_button.isEnabled()
    assert all(not row.add_criterion.isEnabled() for row in dialog._rows)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _assert_tab_order(dialog: OrganizationDialog, expected: list[QWidget]) -> None:
    expected[0].setFocus()
    QApplication.processEvents()
    assert dialog.focusWidget() is expected[0]
    for following in expected[1:]:
        QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Tab)
        assert dialog.focusWidget() is following
    QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Tab)
    assert dialog.focusWidget() is expected[0]
    QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
    assert dialog.focusWidget() is expected[-1]
    for previous in reversed(expected[:-1]):
        QTest.keyClick(dialog.focusWidget(), Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
        assert dialog.focusWidget() is previous


def test_tab_order_tracks_dynamic_levels_and_criteria(qapp: QApplication) -> None:
    dialog = OrganizationDialog(
        "ttf2otf",
        (),
        {
            "family": "Family",
            "format": "opentype",
            "outline": "ps",
            "upm": "1000",
            "tolerance": "1",
            "simplify": "0",
        },
        ".otf",
    )
    dialog.show()
    QApplication.processEvents()
    apply = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    cancel = dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel)
    restore = dialog.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
    assert apply is not None and cancel is not None and restore is not None
    assert not restore.isEnabled()  # no levels yet
    _assert_tab_order(dialog, [dialog.add_level_button, apply, cancel])

    QTest.keyClick(dialog.add_level_button, Qt.Key.Key_Space)
    first = dialog._rows[0]
    family = first.combos[0]
    assert dialog.focusWidget() is family
    _assert_tab_order(
        dialog,
        [
            first.remove_level,
            family,
            first.criterion_removes[family],
            first.add_criterion,
            dialog.add_level_button,
            restore,
            apply,
            cancel,
        ],
    )

    first.add_criterion.setFocus()
    QTest.keyClick(first.add_criterion, Qt.Key.Key_Space)
    format_ = first.combos[1]
    assert dialog.focusWidget() is format_
    dialog.add_level_button.setFocus()
    QTest.keyClick(dialog.add_level_button, Qt.Key.Key_Space)
    second = dialog._rows[1]
    outline = second.combos[0]
    assert dialog.focusWidget() is outline
    _assert_tab_order(
        dialog,
        [
            first.move_down,
            first.remove_level,
            family,
            first.criterion_moves[family][1],
            first.criterion_removes[family],
            format_,
            first.criterion_moves[format_][0],
            first.criterion_removes[format_],
            first.add_criterion,
            second.move_up,
            second.remove_level,
            outline,
            second.criterion_removes[outline],
            second.add_criterion,
            dialog.add_level_button,
            restore,
            apply,
            cancel,
        ],
    )

    first.criterion_moves[format_][0].setFocus()
    QTest.keyClick(first.criterion_moves[format_][0], Qt.Key.Key_Space)
    assert dialog.focusWidget() is first.criterion_moves[format_][1]
    second.move_up.setFocus()
    QTest.keyClick(second.move_up, Qt.Key.Key_Space)
    assert dialog.focusWidget() is second.move_down
    _assert_tab_order(
        dialog,
        [
            second.move_down,
            second.remove_level,
            outline,
            second.criterion_removes[outline],
            second.add_criterion,
            first.move_up,
            first.remove_level,
            format_,
            first.criterion_moves[format_][1],
            first.criterion_removes[format_],
            family,
            first.criterion_moves[family][0],
            first.criterion_removes[family],
            first.add_criterion,
            dialog.add_level_button,
            restore,
            apply,
            cancel,
        ],
    )
    first.criterion_removes[format_].setFocus()
    QTest.keyClick(first.criterion_removes[format_], Qt.Key.Key_Space)
    assert dialog.focusWidget() is family
    second.remove_level.setFocus()
    QTest.keyClick(second.remove_level, Qt.Key.Key_Space)
    assert dialog.focusWidget() is family
    _assert_tab_order(
        dialog,
        [
            first.remove_level,
            family,
            first.criterion_removes[family],
            first.add_criterion,
            dialog.add_level_button,
            restore,
            apply,
            cancel,
        ],
    )
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_tab_focus_when_all_criteria_used_and_final_level_removed(qapp: QApplication) -> None:
    dialog = OrganizationDialog(
        "ft2wf",
        (("family", "format"),),
        {"family": "Family", "format": "woff", "outline": "tt"},
        ".woff",
    )
    dialog.show()
    QApplication.processEvents()
    row = dialog._rows[0]
    row.add_criterion.setFocus()
    QTest.keyClick(row.add_criterion, Qt.Key.Key_Space)
    outline = row.combos[2]
    assert dialog.focusWidget() is outline
    assert not row.add_criterion.isEnabled()
    assert not dialog.add_level_button.isEnabled()
    apply = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    cancel = dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel)
    restore = dialog.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
    assert apply is not None and cancel is not None and restore is not None
    family, format_, _ = row.combos
    _assert_tab_order(
        dialog,
        [
            row.remove_level,
            family,
            row.criterion_moves[family][1],
            row.criterion_removes[family],
            format_,
            *row.criterion_moves[format_],
            row.criterion_removes[format_],
            outline,
            row.criterion_moves[outline][0],
            row.criterion_removes[outline],
            restore,
            apply,
            cancel,
        ],
    )
    row.remove_level.setFocus()
    QTest.keyClick(row.remove_level, Qt.Key.Key_Space)
    assert dialog.focusWidget() is dialog.add_level_button
    _assert_tab_order(dialog, [dialog.add_level_button, apply, cancel])
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_restore_defaults_clears_all_levels(qapp: QApplication) -> None:
    dialog = OrganizationDialog(
        "ttf2otf",
        (("family", "format"), ("outline",)),
        {
            "family": "Family",
            "format": "opentype",
            "outline": "ps",
            "upm": "1000",
            "tolerance": "1",
            "simplify": "0",
        },
        ".otf",
    )
    dialog.show()
    QApplication.processEvents()
    restore = dialog.buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
    assert restore is not None and restore.isEnabled()

    restore.setFocus()
    restore.click()

    assert dialog.levels == ()
    assert not dialog.empty_hint.isHidden()
    assert not restore.isEnabled()
    assert dialog.preview.plain_path() == "font.otf"
    assert not dialog.preview_section.isHidden()
    assert dialog.focusWidget() is dialog.add_level_button
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_dialog_title_tooltips_and_names(qapp: object) -> None:
    dialog = OrganizationDialog("ttf2otf", (("family",), ("format",)), VALUES, ".otf")
    assert dialog.windowTitle() == "Organize output"
    expected = {
        "Move this folder level up",
        "Move this folder level down",
        "Move this criterion earlier in the folder name.",
        "Move this criterion later in the folder name.",
        "Remove this criterion; removing the last one also removes the level.",
    }
    buttons = [
        button
        for button in dialog.findChildren(QPushButton)
        if button.objectName() in ("organizationIconButton", "organizationRemoveCriterionButton")
    ]
    assert {button.toolTip() for button in buttons} == expected
    assert all(button.accessibleName() for button in buttons)
    assert all(not button.icon().isNull() and not button.text() for button in buttons)
