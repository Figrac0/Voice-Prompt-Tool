$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

$python = Join-Path $root ".venv\Scripts\python.exe"

& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt

if (Test-Path "dist\VoicePromptTool") {
    Remove-Item -Recurse -Force "dist\VoicePromptTool"
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name "VoicePromptTool" `
    --collect-all faster_whisper `
    --collect-all pystray `
    --collect-all PIL `
    app/main.py

Write-Host "Build complete. App folder: dist\VoicePromptTool"
