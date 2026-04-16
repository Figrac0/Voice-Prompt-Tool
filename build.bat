@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ====================================================
echo   Voice Prompt Tool  ^|  EXE Builder
echo ====================================================
echo.

:: ── 1. Ensure virtual environment exists ────────────────────────────────────
if exist ".venv\Scripts\python.exe" goto :install

echo [1/4] Creating virtual environment...
where python >nul 2>&1
if %errorlevel%==0 (
    python -m venv .venv
    goto :check_venv
)
where py >nul 2>&1
if %errorlevel%==0 (
    py -3 -m venv .venv
    goto :check_venv
)
echo ERROR: Python not found. Install Python 3.10+ from https://python.org
echo        Make sure "Add python.exe to PATH" is ticked during install.
pause
exit /b 1

:check_venv
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

:: ── 2. Install / upgrade dependencies ───────────────────────────────────────
:install
echo [2/4] Installing dependencies...
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Dependency installation failed.
    pause
    exit /b 1
)

:: ── 3. Clean previous build ─────────────────────────────────────────────────
echo [3/4] Cleaning previous build artefacts...
if exist "dist\VoicePromptTool" rmdir /s /q "dist\VoicePromptTool"
if exist "build"                rmdir /s /q "build"

:: ── 4. Build EXE via PyInstaller spec ───────────────────────────────────────
echo [4/4] Building EXE (this may take a few minutes)...
.venv\Scripts\python.exe -m PyInstaller VoicePromptTool.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo ERROR: Build failed. Check the output above for details.
    pause
    exit /b 1
)

echo.
echo ====================================================
echo   Build complete!
echo   Run:  dist\VoicePromptTool\VoicePromptTool.exe
echo ====================================================
pause
