# Voice Prompt Tool

Windows-only background tray utility for local voice dictation on Python 3.11+.

This personal MVP includes:

- global hotkey `Ctrl + Win`
- microphone recording while the hotkey is held
- local offline transcription through `faster-whisper`
- background processing queue so transcription does not block the next recording start
- light text cleanup
- clipboard copy
- auto-paste into the active text field
- local capped history in `data/history.json`
- file logging and temp file cleanup
- single-instance lock so hidden old processes do not duplicate events

This MVP does not include:

- cloud APIs
- GUI editor window
- LLM rewriting, paraphrasing, or summarization
- live word-by-word streaming while speaking

## Project Structure

```text
voice_prompt_tool/
  app/
    __init__.py
    main.py
    config.py
    logger.py
    state.py
    tray.py
    notifications.py
    hotkeys.py
    audio_recorder.py
    transcriber.py
    text_postprocess.py
    clipboard_service.py
    history_service.py
    processing_worker.py
    single_instance.py
    text_injector.py
  data/
    history.json
  temp/
  requirements.txt
  README.md
  config.json
  run.bat
```

## Setup on Windows

1. Install Python 3.11 or newer.
2. Open the `voice_prompt_tool` folder.
3. Run `run.bat`.

`run.bat` will:

- create `.venv` if needed
- install dependencies from `requirements.txt`
- start the tray app through `python.exe` in the current console window

After startup:

- the tray icon appears in the Windows system tray
- the console stays open and shows runtime logs
- when the app exits, the batch file shows the exit code and waits for a key press

## Manual Run

```bat
cd voice_prompt_tool
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m app.main
```

## Runtime Flow

1. Hold `Ctrl + Win`.
2. The app enters `RECORDING`.
3. Microphone audio is recorded into `temp/`.
4. Release the hotkey.
5. The app enters `TRANSCRIBING` and queues the WAV for background processing.
6. `faster-whisper` transcribes the WAV locally.
7. Light text cleanup is applied.
8. Cleaned text is copied to the clipboard when `text_postprocess.auto_copy` is enabled.
9. Cleaned text is pasted into the focused text field when `text_postprocess.auto_paste` is enabled.
10. The last history entries are stored in `data/history.json`.
11. The processed temp WAV is deleted after successful completion.
12. The app returns to `IDLE` when there are no more queued transcription jobs.

If the recording is too short or empty, the WAV file is deleted and transcription is skipped.

## Config Options

Main options in `config.json`:

- `app_name` - tray app name
- `log_level` - `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`
- `history_limit` - maximum number of saved history entries
- `hotkey.combination` - default is `ctrl+win`
- `audio.sample_rate` - default `16000`
- `audio.max_record_seconds` - default `120`
- `transcription.model_size` - any `faster-whisper` model name or local model path
- `transcription.language_mode` - `auto`, `ru`, or `en`
- `transcription.cpu_threads` - `0` means automatic CPU thread count
- `transcription.beam_size` - lower values are faster, default `1`
- `transcription.best_of` - lower values are faster, default `1`
- `transcription.condition_on_previous_text` - default `false`
- `transcription.without_timestamps` - default `true`
- `transcription.vad_filter` - default `false`
- `text_postprocess.auto_copy` - `true` or `false`
- `text_postprocess.auto_paste` - `true` or `false`
- `text_postprocess.custom_replacements` - exact phrase replacements applied after transcription

Example:

```json
{
  "history_limit": 100,
  "hotkey": {
    "combination": "ctrl+win"
  },
  "audio": {
    "sample_rate": 16000,
    "max_record_seconds": 120
  },
  "transcription": {
    "model_size": "tiny",
    "language_mode": "auto",
    "cpu_threads": 0,
    "beam_size": 1,
    "best_of": 1,
    "condition_on_previous_text": false,
    "without_timestamps": true,
    "vad_filter": false
  },
  "text_postprocess": {
    "auto_copy": true,
    "auto_paste": true,
    "custom_replacements": {
      "чат gpt": "ChatGPT",
      "опен эй ай": "OpenAI",
      "реакт": "React",
      "тайпскрипт": "TypeScript",
      "некст джей эс": "Next.js"
    }
  }
}
```

## Model Size

Examples:

- `tiny` - fastest, lowest quality
- `small` - slower, but usually better than `tiny`
- `medium` - slower and heavier, but often more accurate

## Language Mode

Allowed values:

- `auto` - automatic language detection
- `ru` - force Russian
- `en` - force English

If you mostly dictate in Russian, forcing `ru` usually removes language detection overhead.

## Speed Tuning

For the lowest latency on CPU, keep:

- `model_size: "tiny"`
- `beam_size: 1`
- `best_of: 1`
- `without_timestamps: true`
- `condition_on_previous_text: false`
- `vad_filter: false`
- `language_mode: "ru"` when you are dictating only Russian

If recognition quality is more important than speed, switch to `small` or `medium`.

## History Format

`data/history.json` stores the last `history_limit` entries.
Each entry contains:

- `timestamp`
- `raw_text`
- `cleaned_text`
- `language_mode`
- `recording_duration_seconds`

The app writes history atomically, skips exact accidental duplicates, and resets a corrupted history file gracefully.

## Tray Menu

- `Show current status`
- `Open history file`
- `Exit`

`Show current status` also displays the last cleaned transcript preview when available.

## Logs and Files

- app log: `logs/voice_prompt_tool.log`
- bootstrap log: `logs/bootstrap.log`
- history file: `data/history.json`
- temporary audio files: `temp/*.wav`
- cached models: `models/`

Important events are logged:

- hotkey registered, pressed, released
- recording started, stopped, ignored, or failed
- transcription started, finished, or failed
- transcript text and cleaned text
- clipboard copy and active-field paste success or failure
- history save success or failure
- temp file cleanup
- second-instance blocking

## Known Limitations

- Windows only
- single microphone input only
- mono recording only
- CPU transcription is not instant - on weaker machines there can still be a noticeable delay after hotkey release
- active-field paste depends on focus staying on the intended text field
- `faster-whisper` first model download can take time and disk space
- punctuation recovery is heuristic - question marks improve, but they are not guaranteed for every sentence
