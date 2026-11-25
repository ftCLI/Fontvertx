from __future__ import annotations

from collections.abc import Iterator

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QMessageBox,
    QProxyStyle,
    QStyle,
    QStyleFactory,
)

from fontvertx.gui import tooltips
from fontvertx.gui.app_style import AppStyle
from fontvertx.gui.organization_dialog import OrganizationDialog

HINT = QStyle.StyleHint


class ThemeIconsStyle(QProxyStyle):
    """Fusion as on a Linux desktop whose theme puts icons on dialog buttons."""

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == HINT.SH_DialogButtonBox_ButtonsHaveIcons:
            return 1
        return super().styleHint(hint, option, widget, returnData)


@pytest.fixture
def linux_like_style(qapp: QApplication) -> Iterator[None]:
    qapp.setStyle(AppStyle(ThemeIconsStyle(QStyleFactory.create("Fusion"))))
    yield
    qapp.setStyle("Fusion")


def test_app_style_slows_tooltips_down(qapp: QApplication) -> None:
    style = AppStyle(QStyleFactory.create("Fusion"))
    assert style.styleHint(HINT.SH_ToolTip_WakeUpDelay) == tooltips.TOOLTIP_WAKE_UP_MS == 1200
    assert style.styleHint(HINT.SH_ToolTip_FallAsleepDelay) == tooltips.TOOLTIP_FALL_ASLEEP_MS
    assert tooltips.TOOLTIP_FALL_ASLEEP_MS == 300
    # Every other hint comes from the wrapped style.
    fusion = QStyleFactory.create("Fusion")
    assert style.styleHint(HINT.SH_ItemView_ActivateItemOnSingleClick) == fusion.styleHint(
        HINT.SH_ItemView_ActivateItemOnSingleClick
    )


def test_theme_icons_style_would_put_icons_on_dialog_buttons(qapp: QApplication) -> None:
    # Control for the tests below: without AppStyle, standard buttons get icons.
    qapp.setStyle(ThemeIconsStyle(QStyleFactory.create("Fusion")))
    try:
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        assert not box.button(QDialogButtonBox.StandardButton.Cancel).icon().isNull()
    finally:
        qapp.setStyle("Fusion")


def test_app_style_turns_dialog_button_icons_off(linux_like_style: None) -> None:
    style = QApplication.style()
    assert style.styleHint(HINT.SH_DialogButtonBox_ButtonsHaveIcons) == 0


def test_organization_dialog_buttons_have_no_icons(linux_like_style: None) -> None:
    dialog = OrganizationDialog("ttf2otf", (), {}, ".ttf")
    try:
        buttons = dialog.buttons.buttons()
        assert buttons
        assert all(button.icon().isNull() for button in buttons)
    finally:
        dialog.close()
        dialog.deleteLater()


def test_message_box_buttons_have_no_icons(linux_like_style: None) -> None:
    box = QMessageBox(
        QMessageBox.Icon.Question,
        "Title",
        "Text",
        QMessageBox.StandardButton.Ok
        | QMessageBox.StandardButton.Cancel
        | QMessageBox.StandardButton.Yes
        | QMessageBox.StandardButton.No,
    )
    try:
        assert len(box.buttons()) == 4
        assert all(button.icon().isNull() for button in box.buttons())
    finally:
        box.deleteLater()
