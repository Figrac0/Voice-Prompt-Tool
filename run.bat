@echo off
setlocal

cd /d "%~dp0"

set "VENV_DIR=%CD%\.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "BOOTSTRAP_PY="

if not exist "%PYTHON_EXE%" (
    where py >nul 2>nul
    if %errorlevel%==0 (
        py -3.11 -c "import sys" >nul 2>nul
        if %errorlevel%==0 (
            set "BOOTSTRAP_PY=py -3.11"
        ) else (
            py -3.10 -c "import sys" >nul 2>nul
            if %errorlevel%==0 (
                set "BOOTSTRAP_PY=py -3.10"
            )
        )
    )

    if not defined BOOTSTRAP_PY (
        where python >nul 2>nul
        if %errorlevel%==0 (
            set "BOOTSTRAP_PY=python"
        )
    )

    if not defined BOOTSTRAP_PY (
        echo Failed to find a suitable Python runtime.
        exit /b 1
    )

    call %BOOTSTRAP_PY% -m venv "%VENV_DIR%"

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
