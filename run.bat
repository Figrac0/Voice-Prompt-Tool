@echo off
setlocal EnableDelayedExpansion

cd /d "%~dp0"

set "VENV_DIR=%CD%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "BOOTSTRAP_PY="

if not exist "%PYTHON_EXE%" (
    if not defined BOOTSTRAP_PY (
        if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
            set "BOOTSTRAP_PY=""%LocalAppData%\Programs\Python\Python313\python.exe"""
        )
    )

    if not defined BOOTSTRAP_PY (
        where python >nul 2>nul
        if %errorlevel%==0 (
            set "BOOTSTRAP_PY=python"
        )
    )

    if not defined BOOTSTRAP_PY (
        where py >nul 2>nul
        if %errorlevel%==0 (
            set "BOOTSTRAP_PY=py -3"
        )
    )

    if not defined BOOTSTRAP_PY (
        echo Failed to find Python runtime.
        exit /b 1
    )

    call !BOOTSTRAP_PY! -c "import sys" >nul 2>nul
    if errorlevel 1 (
        echo Python runtime command is unavailable: !BOOTSTRAP_PY!
        echo Try reinstalling Python and enable "Add python.exe to PATH".
        exit /b 1
    )

    call !BOOTSTRAP_PY! -m venv "%VENV_DIR%"

    if errorlevel 1 (
        echo Failed to create virtual environment.
        exit /b 1
    )
)

"%PYTHON_EXE%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies.
    exit /b 1
)

echo Starting Voice Prompt Tool in console mode...
echo Keep this window open while the tray app is running.
echo Press Ctrl+C here only if you want to force-stop it.
echo.

"%PYTHON_EXE%" -m app.main

set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo Voice Prompt Tool exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
