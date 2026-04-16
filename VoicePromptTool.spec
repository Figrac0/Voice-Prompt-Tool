# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Voice Prompt Tool (PySide6 edition).
Build via:  build.bat
"""

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None

extra_datas = []
extra_datas += collect_data_files("faster_whisper")
extra_datas += collect_data_files("ctranslate2")
extra_datas += collect_data_files("PySide6", includes=["Qt6Core.dll", "Qt6Gui.dll",
                                                        "Qt6Widgets.dll", "Qt6Network.dll"])

extra_binaries = []
extra_binaries += collect_dynamic_libs("ctranslate2")

a = Analysis(
    ["app/__main__.py"],
    pathex=["."],
    binaries=extra_binaries,
    datas=[
        ("config.json", "."),
        *extra_datas,
    ],
    hiddenimports=[
        # faster-whisper / ctranslate2
        "faster_whisper",
        "ctranslate2",
        "ctranslate2.specs",
        # audio
        "sounddevice",
        "_sounddevice_data",
        # input
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        # PySide6 plugins
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        # app modules
        "app.audio_recorder",
        "app.clipboard_service",
        "app.config",
        "app.history_service",
        "app.hotkeys",
        "app.live_preview",
        "app.logger",
        "app.main",
        "app.notifications",
        "app.overlay",
        "app.processing_worker",
        "app.settings_dialog",
        "app.single_instance",
        "app.state",
        "app.text_injector",
        "app.text_postprocess",
        "app.transcriber",
        "app.tray",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "scipy",
        "pandas",
        "notebook",
        "IPython",
        "pytest",
        "pystray",
        "PIL",
        "Pillow",
        "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoicePromptTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX can corrupt ctranslate2 and PySide6 DLLs
    console=False,      # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VoicePromptTool",
)
