@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
set "PYW=.venv\Scripts\pythonw.exe"

:: ── First-time setup (visible) ───────────────────────────────────────────────
if exist "%PY%" goto :launch

echo [Voice Prompt Tool] First-time setup — please wait...
echo.

set "BOOTSTRAP="
if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
    set "BOOTSTRAP=%LocalAppData%\Programs\Python\Python313\python.exe"
    goto :create_venv
)
where python >nul 2>&1 && set "BOOTSTRAP=python" && goto :create_venv
where py     >nul 2>&1 && set "BOOTSTRAP=py -3"  && goto :create_venv

echo ERROR: Python 3.10+ not found.
echo        Download from https://python.org and tick "Add python.exe to PATH".
pause & exit /b 1

:create_venv
%BOOTSTRAP% -m venv .venv
if errorlevel 1 ( echo ERROR: Failed to create virtual environment. & pause & exit /b 1 )

"%PY%" -m pip install --upgrade pip --quiet
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 ( echo ERROR: Dependency installation failed. & pause & exit /b 1 )

echo.
echo Setup complete. Launching Voice Prompt Tool...
echo.

:: ── Silent launch via temporary VBScript (no console window) ─────────────────
:launch
set "_VBS=%TEMP%\vpt_%RANDOM%.vbs"
set "_DIR=%~dp0"
if "%_DIR:~-1%"=="\" set "_DIR=%_DIR:~0,-1%"

(echo Dim s : Set s = CreateObject^("WScript.Shell"^))  > "%_VBS%"
(echo s.CurrentDirectory = "%_DIR%")                   >> "%_VBS%"
(echo s.Run Chr^(34^) ^& "%PYW%" ^& Chr^(34^) ^& " -m app", 0, False) >> "%_VBS%"

wscript //nologo "%_VBS%"
del "%_VBS%" 2>nul
