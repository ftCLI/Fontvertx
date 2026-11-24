#!/usr/bin/env bash
# Build the macOS (Apple Silicon, arm64) distribution of Fontvertx with PyInstaller.
#
# Output:
#   build/macos/dist/Fontvertx.app                 the app (GUI and CLI in Contents/MacOS/)
#   build/macos/dist/LICENSE, README.md            next to the app
#   build/macos/Fontvertx-<version>-macos-arm64.zip
#
# Usage (from any directory, on a Mac with Apple Silicon): ./packaging/macos/build.sh
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"

version="$(sed -nE 's/^__version__[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/p' src/fontvertx/__init__.py)"
if [[ -z "$version" ]]; then
    echo "Could not read __version__ from src/fontvertx/__init__.py" >&2
    exit 1
fi

# 1. App icon (.icns) from the PNGs in the package assets.
assets="src/fontvertx/assets"
iconset="build/macos/Fontvertx.iconset"
rm -rf "$iconset"
mkdir -p "$iconset"
cp "$assets/fontvertx-16.png"  "$iconset/icon_16x16.png"
cp "$assets/fontvertx-32.png"  "$iconset/icon_16x16@2x.png"
cp "$assets/fontvertx-32.png"  "$iconset/icon_32x32.png"
cp "$assets/fontvertx-64.png"  "$iconset/icon_32x32@2x.png"
cp "$assets/fontvertx-128.png" "$iconset/icon_128x128.png"
cp "$assets/fontvertx-256.png" "$iconset/icon_128x128@2x.png"
cp "$assets/fontvertx-256.png" "$iconset/icon_256x256.png"
iconutil -c icns "$iconset" -o build/macos/fontvertx.icns
rm -rf "$iconset"

# 2. PyInstaller.
uv run --group build pyinstaller packaging/macos/fontvertx.spec --noconfirm --clean \
    --distpath build/macos/dist --workpath build/macos/work

dist="build/macos/dist"
app="$dist/Fontvertx.app"

# The native tools run by cffsubr and ttfautohint-py must be in the bundle, with an arm64 slice.
for tool in cffsubr/tx ttfautohint/ttfautohint; do
    path="$app/Contents/Frameworks/$tool"
    if [[ ! -x "$path" ]]; then
        echo "Missing native executable in the bundle: $path" >&2
        exit 1
    fi
    if [[ " $(lipo -archs "$path") " != *" arm64 "* ]]; then
        echo "$path has no arm64 slice ($(lipo -archs "$path"))" >&2
        exit 1
    fi
done
codesign --verify --deep --strict "$app"

# 3. LICENSE and README next to the app (not inside the bundle).
cp LICENSE README.md "$dist/"

# 4. Zip with ditto, which keeps the symlinks and signatures of the Qt frameworks.
#    The archive holds a Fontvertx/ folder with Fontvertx.app, LICENSE and README.md.
stage="build/macos/package/Fontvertx"
rm -rf "build/macos/package"
mkdir -p "$stage"
ditto "$app" "$stage/Fontvertx.app"
cp LICENSE README.md "$stage/"

zip="build/macos/Fontvertx-$version-macos-arm64.zip"
rm -f "$zip"
ditto -c -k --keepParent "$stage" "$zip"
rm -rf "build/macos/package"

echo "App: $root/$app"
echo "Zip: $root/$zip"
