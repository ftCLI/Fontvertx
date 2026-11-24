# Build the Windows distribution of Fontvertx with PyInstaller.
#
# Output:
#   build/windows/dist/Fontvertx/                    folder with Fontvertx.exe and fontvertx-cli.exe
#   build/windows/Fontvertx-<version>-windows-x64.zip
#
# Usage (from any directory): .\packaging\windows\build.ps1

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $root
try {
    uv run --group build pyinstaller packaging/windows/fontvertx.spec --noconfirm --clean `
        --distpath build/windows/dist --workpath build/windows/work
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }

    $distDir = Join-Path $root "build\windows\dist\Fontvertx"
    Copy-Item -Path (Join-Path $root "LICENSE") -Destination $distDir -Force
    Copy-Item -Path (Join-Path $root "README.md") -Destination $distDir -Force

    $init = Get-Content -Raw -Path (Join-Path $root "src\fontvertx\__init__.py")
    $match = [regex]::Match($init, '__version__\s*=\s*"([^"]+)"')
    if (-not $match.Success) {
        throw "Could not read __version__ from src/fontvertx/__init__.py"
    }
    $version = $match.Groups[1].Value

    $zip = Join-Path $root "build\windows\Fontvertx-$version-windows-x64.zip"
    if (Test-Path $zip) {
        Remove-Item -Path $zip -Force
    }
    Compress-Archive -Path $distDir -DestinationPath $zip

    Write-Host "Folder: $distDir"
    Write-Host "Zip:    $zip"
}
finally {
    Pop-Location
}
