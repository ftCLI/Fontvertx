# PyInstaller spec for the Windows build of Fontvertx (onedir, no UPX).
#
# Two executables share one folder of libraries:
#   Fontvertx.exe      GUI, no console  (fontvertx.__main__:main)
#   fontvertx-cli.exe  CLI, console     (fontvertx.cli:main)
#
# Build with packaging/windows/build.ps1 from the repository root.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).parents[1]
HERE = Path(SPECPATH)
ICON = str(ROOT / "src" / "fontvertx" / "assets" / "fontvertx.ico")

# Package data: icons, SVG/PNG/ICO assets and the bundled Inter / JetBrains Mono fonts.
datas = collect_data_files("fontvertx")
binaries = []
hiddenimports = []

# cffsubr runs its bundled tx.exe and ttfautohint-py its bundled ttfautohint.exe as a
# child process, locating them with importlib.resources next to the package's
# __init__.py (not through sys.executable). collect_all copies those executables into
# <dist>/_internal/cffsubr and <dist>/_internal/ttfautohint.
for package in ("cffsubr", "ttfautohint"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

EXCLUDES = ["tkinter", "_tkinter", "pytest", "_pytest", "mypy", "ruff"]


def make_analysis(script: str) -> Analysis:
    return Analysis(
        [str(HERE / script)],
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
    icon=ICON,
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
    icon=ICON,
    upx=False,
    debug=False,
    strip=False,
)

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
