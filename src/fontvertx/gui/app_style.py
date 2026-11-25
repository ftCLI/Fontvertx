"""The application-wide proxy style, wrapped around Fusion in ``__main__``.

It changes only a few style hints; everything else comes from the wrapped style.
"""

from PySide6.QtWidgets import QProxyStyle, QStyle

from fontvertx.gui.tooltips import TOOLTIP_FALL_ASLEEP_MS, TOOLTIP_WAKE_UP_MS


class AppStyle(QProxyStyle):
    """Calmer tooltip timing, and no theme icons on dialog and message box buttons.

    On Linux, Fusion takes icons for the standard buttons (OK, Cancel, Apply...) from the
    desktop theme; on Windows there are none, and the app's design does not use them.
    Buttons the app gives an icon on purpose keep it.
    """

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_ToolTip_WakeUpDelay:
            return TOOLTIP_WAKE_UP_MS
        if hint == QStyle.StyleHint.SH_ToolTip_FallAsleepDelay:
            return TOOLTIP_FALL_ASLEEP_MS
        if hint == QStyle.StyleHint.SH_DialogButtonBox_ButtonsHaveIcons:
            return 0
        return super().styleHint(hint, option, widget, returnData)
