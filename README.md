# Voice Prompt Tool

A lightweight Windows voice-to-text utility that transcribes speech and immediately types the result into the active text field. Designed for writing prompts, notes, and messages hands-free.

---

<div align="center">
  
| 1 |
| :---: |
| <img src="https://github.com/Figrac0/Voice-Prompt-Tool/blob/V3/assets/img/1.png" width="300"/> |

|                                               2                                                |
| :--------------------------------------------------------------------------------------------: |
| <img src="https://github.com/Figrac0/Voice-Prompt-Tool/blob/V3/assets/img/2.png" width="400"/> |

</div>

## How it works

1. Click into any text field — browser address bar, IDE, chat, anything.
2. Hold **Ctrl + Shift** and speak.
3. Release the keys — the transcription is typed at the cursor position and copied to the clipboard.

The floating overlay widget is always visible in the corner of your screen. It shows a live audio waveform while recording, an amber indicator while processing, and the transcription history when clicked.

---

## Features

| Feature             | Detail                                                                |
| ------------------- | --------------------------------------------------------------------- |
| Cloud transcription | Groq API with Whisper Large v3 Turbo — typically 0.2–0.5 s round-trip |
| Local fallback      | `faster-whisper` runs on-device if no API key is provided             |
| Floating overlay    | Draggable pill widget; no taskbar entry; stays on top                 |
| Expandable history  | Click the pill to reveal the last 5 transcriptions inline             |
| Auto-inject         | Text is typed via `pynput` keyboard emulation into the focused window |
| Clipboard sync      | Every transcription is also written to the clipboard                  |
| System tray         | Right-click for status, settings, history, and quit                   |
| Silent launch       | `run.bat` starts the app with no console window via `pythonw.exe`     |
| Single instance     | A lock file prevents duplicate processes                              |

---

## Requirements

- **OS:** Windows 10 or 11
- **Python:** 3.10 or newer — download from [python.org](https://www.python.org/downloads/) and tick _"Add python.exe to PATH"_ during installation
- **Groq API key** _(optional, but strongly recommended)_ — free tier available at [console.groq.com](https://console.groq.com)

---

## Installation

### 1. Obtain the project

```
git clone https://github.com/your-username/voice-prompt-tool.git
cd voice-prompt-tool
```

Or download and extract the ZIP.

### 2. Configure your API key _(optional)_

Create a file named `.env` in the project root:

```
GROQ_API_KEY=gsk_your_key_here
```

Without a key the app downloads and runs a local Whisper model (~500 MB on first use, slower inference).

### 3. Enable Groq in `config.json`

Ensure the `groq` section reads:

```json
"groq": {
  "enabled": true,
  "api_key": "",
  "model": "whisper-large-v3-turbo"
}
```

The `api_key` field can be left empty when the key is supplied via `.env`.

### 4. Launch

Double-click **`run.bat`**.

The first run performs a one-time setup:

- Creates a Python virtual environment in `.venv/`
- Installs all dependencies from `requirements.txt`
- Launches the application silently

Every subsequent launch skips setup and starts immediately.

---

## Usage

### Overlay widget

The pill-shaped overlay sits in the bottom-right corner of the screen.

| Interaction              | Result                                                          |
| ------------------------ | --------------------------------------------------------------- |
| Hold **Ctrl + Shift**    | Recording starts — animated waveform                            |
| Release **Ctrl + Shift** | Transcription runs — amber indicator — text is typed and copied |
| **Click** the pill       | Expand to show last 5 transcriptions + action buttons           |
| **Drag** the pill        | Reposition anywhere on screen                                   |
| **Свернуть** button      | Collapse the history back to the pill                           |
| **Закрыть** button       | Quit the application                                            |
| **⎘** on any entry       | Copy that transcription to the clipboard                        |

### System tray

Right-click the tray icon (bottom-right of the taskbar) for the context menu:

- **История записей** — open or close the history panel
- **Настройки...** — open the settings editor
- **Выход** — quit

---

## Configuration

`config.json` is created automatically on first launch. Edit it to adjust behaviour:

```json
{
    "hotkey": {
        "combination": "ctrl+shift"
    },
    "transcription": {
        "model_size": "small",
        "language_mode": "ru"
    },
    "groq": {
        "enabled": true,
        "api_key": "",
        "model": "whisper-large-v3-turbo"
    },
    "overlay": {
        "enabled": true,
        "margin": 12
    }
}
```

| Key                           | Accepted values                              | Description                                                       |
| ----------------------------- | -------------------------------------------- | ----------------------------------------------------------------- |
| `hotkey.combination`          | e.g. `ctrl+shift`, `ctrl+alt+space`          | Push-to-talk key combination                                      |
| `transcription.language_mode` | `"ru"` · `"en"` · `"auto"`                   | Explicit language is faster and more accurate than auto-detection |
| `transcription.model_size`    | `"tiny"` · `"base"` · `"small"` · `"medium"` | Local model size (ignored when Groq is enabled)                   |
| `groq.enabled`                | `true` · `false`                             | `true` = Groq cloud; `false` = local faster-whisper               |
| `overlay.enabled`             | `true` · `false`                             | Show or hide the floating pill widget                             |
| `overlay.margin`              | integer (px)                                 | Distance from screen edge                                         |

The `GROQ_API_KEY` environment variable (set in `.env`) takes precedence over an empty `groq.api_key` in `config.json`.

---

## Project structure

```
Voice-Prompt/
├── app/
│   ├── audio_recorder.py    # Microphone capture; RMS level callback for waveform
│   ├── config.py            # Configuration loading, validation, and defaults
│   ├── groq_transcriber.py  # Groq Whisper API client
│   ├── history_service.py   # Append-only transcription history (JSON)
│   ├── hotkeys.py           # Global push-to-talk listener via pynput
│   ├── logger.py            # Logging configuration
│   ├── main.py              # Application bootstrap and recording pipeline
│   ├── notifications.py     # System tray balloon notifications
│   ├── overlay.py           # Floating pill widget with expandable history panel
│   ├── settings_dialog.py   # In-app settings editor
│   ├── single_instance.py   # Lock file guard against duplicate processes
│   ├── state.py             # State machine: IDLE → RECORDING → TRANSCRIBING → IDLE
│   ├── text_injector.py     # Keyboard emulation via pynput Controller
│   ├── text_postprocess.py  # Post-processing: capitalisation, punctuation, replacements
│   ├── transcriber.py       # Local faster-whisper backend
│   └── tray.py              # System tray icon, dynamic state icons, context menu
├── data/
│   └── history.json         # Transcription history (auto-created)
├── logs/                    # Rotating log files (auto-created)
├── models/                  # Local Whisper model cache (auto-created)
├── temp/                    # Temporary audio files (auto-created)
├── config.json              # User configuration (auto-created on first run)
├── requirements.txt         # Python package dependencies
├── run.bat                  # One-click launcher with auto-setup
└── .env                     # Secret environment variables (not committed)
```

---

## Transcription quality tips

- **Use Groq** — cloud inference is 10–20× faster than the local small model on a typical laptop CPU.
- **Set an explicit language** — `"language_mode": "ru"` or `"en"` is faster than `"auto"` and avoids language switching mid-recording.
- **Add domain vocabulary** to `transcription.initial_prompt` in `config.json`. Whisper will bias towards those words and spellings (useful for brand names, technical terms, proper nouns).
- Keep each recording under 60 seconds. Longer audio is processed sequentially and increases latency.

---

## Troubleshooting

| Symptom                                          | Resolution                                                                                                                                         |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Nothing happens on hotkey                        | Another process may own the combination globally. Check `logs/` for `HotkeyRegistrationError`. Try changing `hotkey.combination` in `config.json`. |
| Text is transcribed in the wrong language        | Set `transcription.language_mode` explicitly rather than `"auto"`.                                                                                 |
| Garbled or missing words                         | Set the Windows default recording device to your microphone. Add relevant vocabulary to `initial_prompt`.                                          |
| App does not start after moving to a new machine | Delete the `.venv/` folder and re-run `run.bat` — it will rebuild the environment from scratch.                                                    |
| Groq returns errors                              | Verify `.env` contains a valid `GROQ_API_KEY`. The app falls back to the local model automatically if Groq fails.                                  |
| High CPU after launch                            | The local model is warming up in a background thread — this is normal for ~10–30 s after startup. Use Groq to avoid it entirely.                   |
