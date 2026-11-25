# Changelog

## 1.1.0

- The conversion now runs in the footer of the main window: progress, the file being
  converted, and Pause / Resume and Cancel in place of Convert. Afterwards the footer shows
  the outcome with View log, Open output folder and Convert. When the cards are stacked
  (narrow window), View log and Open output folder become icon buttons.
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
- Linux: the Format, Outlines and UPM columns of the font list and the instance list are
  no longer cut off ("1…0") with larger desktop fonts or display scaling. Their width now
  follows the font size, and they are recomputed when it changes.
- Linux: the buttons of dialogs and message boxes (OK, Cancel, Apply...) no longer show
  icons from the desktop theme, as on Windows and macOS.

## 1.0.0

- Initial release.
