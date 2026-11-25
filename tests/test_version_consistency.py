"""Every copy of the version agrees with pyproject.toml (bump-my-version keeps them in step)."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

with (ROOT / "pyproject.toml").open("rb") as _f:
    PYPROJECT = tomllib.load(_f)
VERSION = PYPROJECT["project"]["version"]

# Links pinned to a release tag: raw.githubusercontent.com/ftCLI/Fontvertx/v<X>/…
# and github.com/ftCLI/Fontvertx/blob/v<X>/…
README_LINK = re.compile(r"Fontvertx/(?:blob/)?v(\d[^/\s)\"']*)/")
MANUAL_LINE = re.compile(r"^Version (\S+) ·", re.MULTILINE)


def test_readme_links_point_to_the_project_version():
    found = README_LINK.findall((ROOT / "README.md").read_text(encoding="utf-8"))
    assert found, (
        "README.md: no link pinned to a release tag (Fontvertx/v<X>/ or Fontvertx/blob/v<X>/)"
    )
    wrong = sorted({v for v in found if v != VERSION})
    assert not wrong, (
        f"README.md: links point to v{', v'.join(wrong)}, but the project version is {VERSION}"
    )


def test_manual_version_line_matches_the_project_version():
    found = MANUAL_LINE.findall((ROOT / "docs" / "manual.md").read_text(encoding="utf-8"))
    assert found, "docs/manual.md: no 'Version <X> ·' line"
    wrong = [v for v in found if v != VERSION]
    assert not wrong, (
        f"docs/manual.md: version line says {wrong[0]}, but the project version is {VERSION}"
    )


def test_bumpversion_current_version_matches_the_project_version():
    current = PYPROJECT["tool"]["bumpversion"]["current_version"]
    assert current == VERSION, (
        f"pyproject.toml: [tool.bumpversion].current_version is {current}, "
        f"but the project version is {VERSION}"
    )
