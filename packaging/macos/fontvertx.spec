# PyInstaller spec for the macOS (Apple Silicon, arm64) build of Fontvertx (onedir + .app, no UPX).
#
# Fontvertx.app/Contents/MacOS/ holds two executables that share one set of libraries:
#   Fontvertx      GUI, the bundle's main executable  (fontvertx.__main__:main)
#   fontvertx-cli  CLI                                 (fontvertx.cli:main)
#
# The launch scripts are shared with the Windows build (packaging/windows/).
# Build with packaging/macos/build.sh from the repository root: it first generates
# build/macos/fontvertx.icns, which this spec uses as the app icon.
import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).parents[1]
LAUNCHERS = ROOT / "packaging" / "windows"
ICON = ROOT / "build" / "macos" / "fontvertx.icns"
TARGET_ARCH = "arm64"

if not ICON.is_file():
    raise SystemExit(f"Missing {ICON}: run packaging/macos/build.sh, which generates it.")

_init = (ROOT / "src" / "fontvertx" / "__init__.py").read_text(encoding="utf-8")
_match = re.search(r'^__version__\s*=\s*"([^"]+)"', _init, re.MULTILINE)
if _match is None:
    raise SystemExit("Could not read __version__ from src/fontvertx/__init__.py")
VERSION = _match.group(1)

# Package data: icons, SVG/PNG/ICO assets and the bundled Inter / JetBrains Mono fonts.
datas = collect_data_files("fontvertx")
binaries = []
hiddenimports = []

# cffsubr runs its bundled `tx` and ttfautohint-py its bundled `ttfautohint` as a child
# process, locating them with importlib.resources next to the package's __init__.py (not
# through sys.executable). Their macOS wheels ship universal2 (x86_64 + arm64) executables.
for package in ("cffsubr", "ttfautohint"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

EXCLUDES = ["tkinter", "_tkinter", "pytest", "_pytest", "mypy", "ruff"]


def make_analysis(script: str) -> Analysis:
    return Analysis(
        [str(LAUNCHERS / script)],
        pathex=[str(ROOT / "src")],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        hookspath=[],
        runtime_hooks=[],
        excludes=EXCLUDES,
        noarchive=False,
    )


gui_a = make_analysis("launch_gui.py")
cli_a = make_analysis("launch_cli.py")

gui_pyz = PYZ(gui_a.pure)
cli_pyz = PYZ(cli_a.pure)

gui_exe = EXE(
    gui_pyz,
    gui_a.scripts,
    [],
    exclude_binaries=True,
    name="Fontvertx",
    console=False,
    target_arch=TARGET_ARCH,
    upx=False,
    debug=False,
    strip=False,
)

cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    [],
    exclude_binaries=True,
    name="fontvertx-cli",
    console=True,
    target_arch=TARGET_ARCH,
    upx=False,
    debug=False,
    strip=False,
)

# The GUI executable comes first: BUNDLE uses the first executable as CFBundleExecutable.
coll = COLLECT(
    gui_exe,
    gui_a.binaries,
    gui_a.datas,
    cli_exe,
    cli_a.binaries,
    cli_a.datas,
    name="Fontvertx",
    upx=False,
    strip=False,
)

app = BUNDLE(
    coll,
    name="Fontvertx.app",
    icon=str(ICON),
    bundle_identifier="io.github.ftcli.fontvertx",
    version=VERSION,
    info_plist={
        "CFBundleName": "Fontvertx",
        "CFBundleDisplayName": "Fontvertx",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "14.4",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.graphics-design",
    },
)
