@echo off
setlocal EnableExtensions DisableDelayedExpansion

rem ============================================================
rem  DeepSeek Harness Offline Launcher - Entry Script
rem  All output in ASCII to avoid encoding issues on double-click
rem ============================================================

set "APP_ROOT=%~dp0"
cd /d "%APP_ROOT%"

rem ----- 1. Locate Node Portable -----
set "NODE_EXE=%APP_ROOT%runtime\node\node.exe"
if not exist "%NODE_EXE%" (
    echo [ERROR] Node.js runtime not found.
    echo Expected at: %NODE_EXE%
    echo.
    echo Please ensure the folder "runtime\node" is complete.
    echo If you moved this file, keep it together with the other folders.
    pause
    exit /b 1
)

rem ----- 2. Locate Python Portable -----
set "PYTHONW_EXE=%APP_ROOT%runtime\python\pythonw.exe"
set "PYTHON_EXE=%APP_ROOT%runtime\python\python.exe"
if not exist "%PYTHONW_EXE%" (
    echo [ERROR] Python runtime not found.
    echo Expected at: %PYTHONW_EXE%
    echo.
    echo Please ensure the folder "runtime\python" is complete.
    pause
    exit /b 1
)

rem ----- 3. Locate launcher entry -----
set "LAUNCHER_PY=%APP_ROOT%launcher\app.py"
if not exist "%LAUNCHER_PY%" (
    echo [ERROR] Launcher script not found.
    echo Expected at: %LAUNCHER_PY%
    pause
    exit /b 1
)

rem ----- 4. Prepare environment (process-local only, NO system changes) -----
set "PATH=%APP_ROOT%runtime\node;%APP_ROOT%runtime\python;%APP_ROOT%runtime\python\Scripts;%PATH%"
set "PYTHONHOME=%APP_ROOT%runtime\python"
set "PYTHONPATH=%APP_ROOT%runtime\python\Lib;%APP_ROOT%runtime\python\DLLs;%APP_ROOT%launcher"

rem Find TCL/TK version directory dynamically
for /d %%D in ("%APP_ROOT%runtime\python\tcl\tcl8.*") do set "TCL_LIBRARY=%%~fD"
for /d %%D in ("%APP_ROOT%runtime\python\tcl\tk8.*")  do set "TK_LIBRARY=%%~fD"
if not defined TCL_LIBRARY (
    rem Fallback default
    set "TCL_LIBRARY=%APP_ROOT%runtime\python\tcl\tcl8.6"
    set "TK_LIBRARY=%APP_ROOT%runtime\python\tcl\tk8.6"
)

set "DSH_APP_ROOT=%APP_ROOT%"
set "DSH_LOG_DIR=%APP_ROOT%logs"
if not exist "%DSH_LOG_DIR%" mkdir "%DSH_LOG_DIR%" 2>nul

rem ----- 5. Launch the GUI via pythonw (no black console window) -----
start "DSH Launcher" "%PYTHONW_EXE%" "%LAUNCHER_PY%"

exit /b 0
