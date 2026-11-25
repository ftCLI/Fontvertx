import tomllib
from importlib.metadata import version
from pathlib import Path

import fontvertx

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_version_comes_from_package_metadata():
    assert fontvertx.__version__ == version("fontvertx")


def test_version_matches_pyproject():
    with PYPROJECT.open("rb") as f:
        project_version = tomllib.load(f)["project"]["version"]
    assert fontvertx.__version__ == project_version
