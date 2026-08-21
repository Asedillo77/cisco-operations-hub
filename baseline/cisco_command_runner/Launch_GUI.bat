@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
    echo uv was not found. Install uv and try again.
    pause
    exit /b 1
)
uv sync
if errorlevel 1 (
    echo Dependency synchronization failed.
    pause
    exit /b 1
)
uv run cisco-command-runner-gui
