"""Typed access to the user preferences persisted in ``QSettings``."""

import json
from collections.abc import Mapping
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings

INPUT_DIR_KEY = "last_input_dir"
OUTPUT_DIR_KEY = "last_output_dir"
LOG_DIR_KEY = "last_log_dir"
MODIFY_RIGHTS_KEY = "modify_rights_confirmed"
PROFILE_KEY = "conversion_profile"
GEOMETRY_KEY = "window/geometry"
ORGANIZATION_LEVELS_KEY = "organization/levels"  # JSON: {profile: [[criterion, ...], ...]}
PROFILE_OPTIONS_KEY = "profile_options"  # JSON: {profile: {option: value}}

# Factory values of the global checkboxes; the panel builders read them from here.
OPTION_DEFAULTS: dict[str, bool] = {
    "overwrite": False,
    "hide_incompatible": False,
}

# Checkable options persisted between sessions: attribute name on the window → key.
OPTION_KEYS = {
    "hide_incompatible": "options/hide_incompatible",
}

FONT_COLUMN_KEYS = {4: "font_columns/family", 5: "font_columns/style"}

# Optional font-table columns: column index → (menu label, settings key).
OPTIONAL_FONT_COLUMNS = {
    column: (name, FONT_COLUMN_KEYS[column]) for column, name in ((4, "Family"), (5, "Style"))
}


class SettingsStore:
    """Thin typed wrapper over ``QSettings``; all keys live here, nowhere else."""

    def __init__(self, settings: QSettings) -> None:
        self._settings = settings

    @property
    def raw(self) -> QSettings:
        return self._settings

    def saved_dir(self, key: str) -> str:
        """Return the persisted directory for ``key``, or "" if missing or gone."""
        value = self._settings.value(key, "")
        return value if isinstance(value, str) and Path(value).is_dir() else ""

    def set_dir(self, key: str, value: str) -> None:
        self._settings.setValue(key, value)

    def get_bool(self, key: str, default: bool = False) -> bool:
        return bool(self._settings.value(key, default, type=bool))

    def set_bool(self, key: str, value: bool) -> None:
        self._settings.setValue(key, value)

    def contains(self, key: str) -> bool:
        return self._settings.contains(key)

    @property
    def profile(self) -> str | None:
        value = self._settings.value(PROFILE_KEY, "")
        return value if isinstance(value, str) and value else None

    def set_profile(self, value: str | None) -> None:
        self._settings.setValue(PROFILE_KEY, value or "")

    @property
    def geometry(self) -> QByteArray | None:
        value = self._settings.value(GEOMETRY_KEY)
        return value if isinstance(value, QByteArray) else None

    def set_geometry(self, value: QByteArray) -> None:
        self._settings.setValue(GEOMETRY_KEY, value)

    def _read_json_dict(self, key: str) -> dict[str, object]:
        raw = self._settings.value(key, "")
        if not isinstance(raw, str) or not raw:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def organization_levels_for(self, profile: str) -> tuple[tuple[str, ...], ...]:
        levels = self._read_json_dict(ORGANIZATION_LEVELS_KEY).get(profile)
        if not isinstance(levels, list):
            return ()
        return tuple(
            tuple(str(key) for key in level) for level in levels if isinstance(level, list)
        )

    def set_organization_levels(self, profile: str, levels: tuple[tuple[str, ...], ...]) -> None:
        data = self._read_json_dict(ORGANIZATION_LEVELS_KEY)
        data[profile] = [list(level) for level in levels]
        self._settings.setValue(ORGANIZATION_LEVELS_KEY, json.dumps(data))

    def profile_options(self, profile: str) -> dict[str, object]:
        values = self._read_json_dict(PROFILE_OPTIONS_KEY).get(profile)
        return dict(values) if isinstance(values, dict) else {}

    def set_profile_options(self, profile: str, values: Mapping[str, object]) -> None:
        data = self._read_json_dict(PROFILE_OPTIONS_KEY)
        data[profile] = dict(values)
        self._settings.setValue(PROFILE_OPTIONS_KEY, json.dumps(data))

    def clear_profile_options(self, profile: str) -> None:
        """Forget the per-profile options; organization levels are kept."""
        data = self._read_json_dict(PROFILE_OPTIONS_KEY)
        if data.pop(profile, None) is not None:
            self._settings.setValue(PROFILE_OPTIONS_KEY, json.dumps(data))
