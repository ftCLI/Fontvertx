# Changelog

## 1.2.0

- The headers of the font table and of the instance list show thin dividers between
  columns.
- Column resizing is more natural: the divider follows the pointer, and the next
  resizable column to its right gives or takes the space, so no horizontal scrollbar
  appears. Format, Outlines and UPM have a fixed width that fits their content; Name
  (Font / instance) fills the remaining space; Family and Style are as wide as their
  content. Double-click a divider to fit the column to its content.
- A Show columns button at the right end of the font table header shows the Family and
  Style columns (right-clicking the header still works).
- Instance list: custom instances are marked with a Custom chip. The context menu shows
  only the actions that apply: Add custom instance… on a font, Edit and Remove on a custom
  instance, none on named instances. Enter expands or collapses a font and edits a custom
  instance.
- A paused conversion now shows its progress bar and icons in amber, like the rest of the
  paused footer, instead of grey. Warning colors use a single amber hue.
- Windows: drop-down lists no longer show black square corners for an instant when they
  open.
- The help tooltips that appeared anywhere over the font table and the instance list,
  empty space included, are gone; hovering a custom instance tells how to edit or remove
  it.

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
- The checkboxes of the Set options card (Subroutinize, Recalculate bounding boxes...) and
  the Tolerance and Simplify labels are only as wide as their text, so their tooltips no
  longer appear over the empty space to the right of it.
- When the cards are stacked (narrow window), the sidebar cards no longer show a second
  scrollbar of their own inside the page's: they are always as tall as their content,
  which they follow live (another profile, an output folder, the organization example),
  and only the page scrolls.

## 1.0.0

- Initial release.
