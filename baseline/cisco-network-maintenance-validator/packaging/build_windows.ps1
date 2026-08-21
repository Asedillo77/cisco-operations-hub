param(
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$sourceRoot = Join-Path $projectRoot "src"
$guiEntry = Join-Path $PSScriptRoot "gui_entry.py"

Push-Location $projectRoot
try {
    & $PythonExe -c "import tkinter as tk; root = tk.Tk(); root.withdraw(); root.destroy()"
    if ($LASTEXITCODE -ne 0) {
        throw "The selected Python installation does not have a working Tcl/Tk runtime."
    }

    & $PythonExe -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --name "NetworkPrePostCheck" `
        --paths $sourceRoot `
        --collect-all netmiko `
        $guiEntry

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    $packageRoot = Join-Path $projectRoot "dist\NetworkPrePostCheck"
    Copy-Item -LiteralPath (Join-Path $projectRoot "configs") -Destination $packageRoot -Recurse
    Copy-Item -LiteralPath (Join-Path $projectRoot "reports") -Destination $packageRoot -Recurse
    Copy-Item -LiteralPath (Join-Path $projectRoot "samples") -Destination $packageRoot -Recurse

    $credentialRoot = Join-Path $packageRoot "credentials"
    New-Item -ItemType Directory -Path $credentialRoot -Force | Out-Null
    Copy-Item `
        -LiteralPath (Join-Path $projectRoot "credentials\credentials.example.txt") `
        -Destination $credentialRoot
    New-Item -ItemType Directory -Path (Join-Path $packageRoot "outputs") -Force | Out-Null

    Write-Host "Package created at: $packageRoot"
}
finally {
    Pop-Location
}
