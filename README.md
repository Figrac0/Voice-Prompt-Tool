# Voice Prompt Tool

A lightweight Windows voice-to-text tool that transcribes your speech and instantly types it into any focused text field. Built for writing AI prompts hands-free.

---

## How it works

1. Click into any text field (browser, IDE, chat, etc.)
2. Hold **Ctrl + Shift** and speak
3. Release — your words are transcribed and typed automatically
4. The text is also copied to your clipboard

---

## Features

- **Fast transcription** via Groq cloud API (Whisper Large v3 Turbo, ~0.2–0.4 s latency)
- **Local fallback** using faster-whisper if no API key is configured
- **Floating overlay** — always visible, draggable, shows live audio waveform while recording and "Обработка..." while transcribing
- **Compact history popup** — click the overlay to open; shows last 5 transcriptions with one-click copy
- **Silent background process** — no console window, only the small overlay is visible on screen
- **Hotkey:** Ctrl + Shift (hold to record, release to transcribe)

---

## Requirements

- Windows 10 / 11
- Python 3.10 or newer → [python.org](https://www.python.org/downloads/) *(tick "Add python.exe to PATH")*
- A free [Groq API key](https://console.groq.com) for cloud transcription *(optional but recommended)*

---

## Quick start

### 1. Clone or download

```
git clone https://github.com/your-username/voice-prompt-tool.git
cd voice-prompt-tool
```

### 2. Add your Groq API key *(optional but recommended)*

Create a `.env` file in the project root:

```
GROQ_API_KEY=gsk_your_key_here
```

Without a key the app uses a local Whisper model (slower, downloads ~500 MB on first run).

### 3. Launch

Double-click **`run.bat`**.

First launch automatically:
- Creates a Python virtual environment in `.venv/`
- Installs all dependencies
- Launches the app with no console window

Every subsequent launch is instant and silent.

---

## Usage

| Action | Result |
|--------|--------|
| Hold **Ctrl + Shift** | Start recording — waveform appears in overlay |
| Release **Ctrl + Shift** | Transcribe → type text into focused field → copy to clipboard |
| Click overlay | Open compact history popup |
| Drag overlay | Move it anywhere on screen |
| **⎘** button in history | Copy that entry to clipboard |
| **—** button in history | Hide history popup |
| **✕** button in history | Quit the application |

---

## Configuration

Edit `config.json` to customise behaviour:

```json
{
  "hotkey":        { "combination": "ctrl+shift" },
  "transcription": { "model_size": "small", "language_mode": "ru" },
  "groq":          { "enabled": true, "api_key": "", "model": "whisper-large-v3-turbo" },
  "overlay":       { "enabled": true, "margin": 20 }
}
```

| Field | Description |
|-------|-------------|
| `hotkey.combination` | Push-to-talk hotkey. Tokens: `ctrl`, `shift`, `alt`, `win`, `space` |
| `transcription.language_mode` | `"ru"` / `"en"` / `"auto"` |
| `transcription.model_size` | Local model: `tiny`, `base`, `small`, `medium` |
| `groq.enabled` | `true` = Groq API, `false` = local model |

API key can also be set in `.env` as `GROQ_API_KEY` (recommended — keeps it out of git).

---

## Project structure

```
Voice-Prompt-Tool/
├── app/
│   ├── audio_recorder.py    # Microphone capture + RMS level callback
│   ├── config.py            # Config loading and validation
│   ├── groq_transcriber.py  # Groq cloud transcription backend
│   ├── history_service.py   # Persist transcription history to JSON
│   ├── history_window.py    # Compact floating history popup (Qt)
│   ├── hotkeys.py           # Global push-to-talk hotkey listener
│   ├── logger.py            # Logging setup
│   ├── main.py              # App bootstrap and recording pipeline
│   ├── notifications.py     # System tray notifications
│   ├── overlay.py           # Always-visible floating waveform overlay
│   ├── settings_dialog.py   # Settings editor dialog
│   ├── single_instance.py   # Single-instance lock
│   ├── state.py             # App state machine (IDLE / RECORDING / TRANSCRIBING)
│   ├── text_injector.py     # Types text into the focused window via pynput
│   ├── text_postprocess.py  # Capitalisation and punctuation cleanup
│   ├── transcriber.py       # Local Whisper backend (faster-whisper)
│   └── tray.py              # System tray icon and context menu
├── config.json              # User configuration
├── requirements.txt         # Python dependencies
├── run.bat                  # One-click launcher
└── .env                     # Secret keys (not committed to git)
```

---

## Transcription quality tips

- **Use Groq API** — dramatically faster and more accurate than the local model
- **Set `language_mode`** explicitly (`"ru"` or `"en"`) rather than `"auto"` — faster and more reliable
- Add domain-specific terms to `initial_prompt` in `config.json` to help Whisper spell them correctly (e.g. brand names, technical terms)
- Keep recordings under 60 seconds for best results

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Nothing happens on hotkey | Another app may have claimed Ctrl+Shift globally. Check `logs/` for errors |
| Garbled text | Set your microphone as the Windows default input; set explicit `language_mode` |
| App doesn't start | Delete `.venv/` and re-run `run.bat` to rebuild the environment |
| Groq errors | Check `.env` has a valid `GROQ_API_KEY`; the app falls back to local model automatically |

---

## License

MIT
