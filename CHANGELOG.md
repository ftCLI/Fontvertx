# Changelog

## 1.1.0

- The conversion now runs in the footer of the main window: progress, the file being
  converted, and Pause / Resume and Cancel in place of Convert. Afterwards the footer shows
  the outcome with View log, Open output folder and Convert. In a narrow window, View log and
  Open output folder become icon buttons.
- The log of the last run opens in a separate, non-modal window (View log), which updates
  live during a run. The modal Conversion window is gone.
- During a run the cards stay visible but cannot be changed, and dropping fonts is disabled;
  the font list can still be scrolled.
- After Pause or Cancel the footer shows Pausing… / Cancelling… until the font being
  converted is done, and the log records the request.

- Python 3.12 or later is now required. PySide6 6.12 can abort on Python 3.11 (a reference
  counting bug, PYSIDE-3474); from Python 3.12 it is harmless. The ready-to-run apps include
  their own Python and are not affected.
- macOS: the app now appears in the Dock and in the Cmd+Tab switcher.

## 1.0.0

- Initial release.
