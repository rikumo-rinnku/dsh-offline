@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0_pack.ps1"
if errorlevel 1 (
    echo [ERROR] Packaging failed. Do not distribute unverified output.
) else (
    echo [OK] Verified package is in release-output.
)
pause
