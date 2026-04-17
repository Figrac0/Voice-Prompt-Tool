# Voice Prompt Tool

A local Windows voice-to-text tool built for writing AI prompts. Hold a hotkey, speak, release — the transcribed text is instantly pasted into any active window.

Powered by **Groq cloud API** (Whisper Large v3 Turbo) for near-instant transcription (~0.1–0.3 s), with a **local faster-whisper** fallback that runs entirely offline.

---

## Features

- **Hold-to-record** — hold `Ctrl+Shift`, speak, release to transcribe
- **Auto-paste** — text is copied to clipboard and pasted into the focused window automatically
- **Groq backend** — transcription via Groq API in ~0.1–0.3 s (free tier: ~7 200 s/day)
- **Local fallback** — works offline with faster-whisper if Groq is disabled
- **Tiny overlay** — small pill indicator shows recording (green) / processing (orange) state
- **System tray** — right-click for settings, history, and exit
- **Russian + English** — language auto-detection or explicit mode
- **Custom replacements** — fix recurring mis-transcriptions in `config.json`

---

## Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/your-username/Voice-Prompt-Tool.git
cd Voice-Prompt-Tool
```

### 2. Add your Groq API key

Copy `.env.example` to `.env` and paste your key:

```bash
cp .env.example .env
```

```env
GROQ_API_KEY=gsk_your_key_here
```

Get a free key at [console.groq.com](https://console.groq.com) → API Keys → Create API Key.

### 3. Run

Double-click **`run.bat`** or run from terminal:

```bash
run.bat
```

The script creates a virtual environment, installs all dependencies, and launches the app. A tray icon appears in the system tray.

---

## Usage

| Action | Result |
|--------|--------|
| Hold `Ctrl+Shift` | Start recording (green dot appears) |
| Release `Ctrl+Shift` | Stop recording → transcribe → paste |
| Right-click tray icon | Open menu: Settings, History, Exit |

The transcribed text is automatically pasted into whichever window was focused when you released the hotkey.

---

## Configuration

Edit **`config.json`** in the project root. Key fields:

```jsonc
{
  "groq": {
    "enabled": true,          // use Groq API (fast)
    "api_key": "",            // leave empty — key comes from .env
    "model": "whisper-large-v3-turbo"
  },
  "transcription": {
    "language_mode": "ru",    // "ru", "en", or "auto"
    "model_size": "small",    // fallback local model if Groq is disabled
    "initial_prompt": "..."   // primes the model — use example sentences
  },
  "hotkey": {
    "combination": "ctrl+shift"
  },
  "text_postprocess": {
    "auto_copy": true,
    "auto_paste": true,
    "custom_replacements": {
      "чат gpt": "ChatGPT"
    }
  }
}
```

### Switching to local mode

Set `"groq": { "enabled": false }` in `config.json`. The app will use faster-whisper locally — no internet required.

| Model | Speed (CPU) | Accuracy |
|-------|-------------|----------|
| `tiny` | ~0.3 s | Low |
| `base` | ~0.6 s | Medium |
| `small` | ~1.2 s | Good |
| `medium` | ~3 s | Very good |

---

## Project Structure

```
Voice-Prompt-Tool/
├── app/
│   ├── __main__.py          # entry point — loads .env, sets MKL vars
│   ├── main.py              # app bootstrap and runtime loop
│   ├── groq_transcriber.py  # Groq API transcription backend
│   ├── transcriber.py       # local faster-whisper backend
│   ├── overlay.py           # floating state indicator (PySide6)
│   ├── tray.py              # system tray icon and menu
│   ├── audio_recorder.py    # microphone capture (sounddevice)
│   ├── hotkeys.py           # global hotkey listener (pynput)
│   ├── text_postprocess.py  # custom replacements, cleanup
│   ├── text_injector.py     # clipboard paste into active window
│   ├── config.py            # config loading and validation
│   └── ...
├── config.json              # user configuration
├── .env                     # secrets — not committed (contains GROQ_API_KEY)
├── .env.example             # template — commit this
├── requirements.txt
└── run.bat                  # one-click launcher
```

---

## Requirements

- Windows 10 / 11
- Python 3.10+
- Internet connection (for Groq backend) **or** local models in `models/` (for offline mode)

---

## Security

- `.env` is listed in `.gitignore` — your API key will never be committed
- The key is loaded at runtime via `python-dotenv`
- You can also set `GROQ_API_KEY` as a system environment variable instead of using `.env`
