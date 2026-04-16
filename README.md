# Voice Prompt Tool

Local voice-to-text for Windows. Hold a hotkey, speak, release — text appears wherever your cursor is.

Built on [faster-whisper](https://github.com/SYSTRAN/faster-whisper). No cloud, no API keys.

## Requirements

- Windows 10/11
- Python 3.10+

## Run

```bat
run.bat
```

First launch creates `.venv` and downloads the selected Whisper model (~500 MB for `small`). Subsequent launches start in seconds.

## Build standalone EXE

```bat
build.bat
```

Output: `dist\VoicePromptTool\VoicePromptTool.exe` — no console, no Python required.

## How it works

1. Focus any text field.
2. Hold `Ctrl+Shift` and speak.
3. Live preview text appears while you speak (fast draft).
4. Release the hotkey — final, more accurate transcription replaces the draft.
5. Result is copied to clipboard and saved to `data/history.json`.

Two-phase pipeline:
- **Live preview** — `base` model, updates every 0.6 s while recording
- **Final pass** — `small` model, `beam=5`, runs after release

## Settings

Right-click the tray icon → **Settings** to change model, language, hotkey, and paste behaviour without editing JSON.

Manual config: `config.json` in the project root.

| Key | Default | Notes |
|-----|---------|-------|
| `hotkey.combination` | `ctrl+shift` | Any combo of ctrl/shift/alt/win |
| `transcription.model_size` | `small` | tiny / base / small / medium |
| `transcription.language_mode` | `ru` | ru / en / auto |
| `transcription.beam_size` | `5` | Higher = slower but more accurate |
| `live_preview.model_size` | `base` | Model used for the draft |
| `text_postprocess.auto_paste` | `true` | Insert into active field |
| `text_postprocess.auto_copy` | `true` | Copy to clipboard |
| `text_postprocess.custom_replacements` | `{}` | Phonetic → correct spelling |

### Model speed vs. accuracy

| Model | Size | CPU speed |
|-------|------|-----------|
| `tiny` | 150 MB | ~0.5 s |
| `base` | 150 MB | ~1 s |
| `small` | 500 MB | ~2–4 s |
| `medium` | 1.5 GB | ~6–10 s |

## File layout

```
run.bat              — launch script
build.bat            — EXE builder
config.json          — user config
app/                 — source
models/              — cached Whisper models (auto-downloaded)
data/history.json    — transcript history (last 100 entries)
logs/                — rotating log files
temp/                — ephemeral WAV recordings (auto-cleaned)
```

## Known limits

- Auto-paste goes to whichever window has focus — don't switch windows mid-recording.
- Punctuation is heuristic, not perfect.
- First launch is slow while the model downloads and loads.
