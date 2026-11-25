from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("fontvertx")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "0+unknown"

from fontvertx.finder import FontFinder
from fontvertx.font import Font

__all__ = ["Font", "FontFinder", "__version__"]
