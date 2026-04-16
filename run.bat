@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "VENV_PYTHON=.venv\Scripts\python.exe"

:: ── Ensure virtual environment exists ───────────────────────────────────────
if exist "%VENV_PYTHON%" goto :deps

echo [setup] Creating virtual environment...

set "BOOTSTRAP="
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
    set "BOOTSTRAP=%LocalAppData%\Programs\Python\Python313\python.exe"
    goto :create_venv
)
where python >nul 2>&1 && set "BOOTSTRAP=python" && goto :create_venv
where py    >nul 2>&1 && set "BOOTSTRAP=py -3"  && goto :create_venv

echo ERROR: Python 3.10+ not found.
echo Install from https://python.org and tick "Add python.exe to PATH".
pause
exit /b 1

:create_venv
call %BOOTSTRAP% -m venv .venv
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

:: ── Install / update dependencies ───────────────────────────────────────────
:deps
echo [setup] Checking dependencies...
"%VENV_PYTHON%" -m pip install --upgrade pip --quiet
"%VENV_PYTHON%" -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

:: ── Launch app ───────────────────────────────────────────────────────────────
echo Starting Voice Prompt Tool...
echo Hotkey: Ctrl+Shift  ^|  Tray icon in system tray  ^|  Close window to exit
echo.
"%VENV_PYTHON%" -m app.main
set "EXIT=%ERRORLEVEL%"
echo.
echo App exited (code %EXIT%).
pause
exit /b %EXIT%
