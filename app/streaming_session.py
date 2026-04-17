from __future__ import annotations

import logging
from pathlib import Path
from threading import Event, Thread

from app.audio_recorder import AudioRecorder
from app.text_postprocess import TextPostprocessor


class StreamingTranscriptionSession:
    """Real-time transcription with append-only streaming + final correction.

    While the hotkey (Ctrl+Space) is held:
      - Polls every _POLL_INTERVAL seconds.
      - Transcribes accumulated audio, appends only the NEW suffix to the field.
      - Never sends backspaces — Ctrl+Backspace would delete entire words.
      - Skips any poll result that diverges from what was already typed
        (hallucination guard).

    After the hotkey is released (stop() is called):
      - Worker thread is stopped.
      - A final full-audio transcription is run for maximum accuracy.
      - Delta correction is applied: backspace the diverged tail, type the
        correct suffix. Ctrl is now released, so backspace works normally.
    """

    _POLL_INTERVAL = 0.65   # seconds between intermediate polls
    _MIN_AUDIO_S   = 0.50   # skip snapshot if audio shorter than this

    def __init__(
        self,
        audio_recorder: AudioRecorder,
        transcriber,
        text_postprocessor: TextPostprocessor,
        keyboard_controller,
        logger: logging.Logger,
    ) -> None:
        self._recorder    = audio_recorder
        self._transcriber = transcriber
        self._postprocess = text_postprocessor
        self._kb          = keyboard_controller
        self._logger      = logger

        self._stop_event  = Event()
        self._thread: Thread | None = None
        self._injected    = ""   # text already typed into the focused field

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._injected = ""
        self._stop_event.clear()
        self._thread = Thread(
            target=self._worker,
            daemon=True,
            name="streaming-transcription",
        )
        self._thread.start()
        self._logger.info("Streaming session started.")

    def stop(self, audio_path: Path) -> str:
        """Stop polling, do final correction. Returns all injected text."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=6.0)
        self._final_correct(audio_path)
        self._logger.info("Streaming session stopped | chars=%s | text=%r",
                          len(self._injected), self._injected)
        return self._injected

    def discard(self) -> None:
        """Abort and erase whatever was already typed."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        if self._injected:
            self._send_backspaces(len(self._injected))
            self._injected = ""
        self._logger.info("Streaming session discarded.")

    @property
    def injected_text(self) -> str:
        return self._injected

    # ── Worker (runs while hotkey is held) ─────────────────────────────────────

    def _worker(self) -> None:
        while not self._stop_event.wait(self._POLL_INTERVAL):
            self._stream_poll()

    def _stream_poll(self) -> None:
        """Transcribe accumulated audio and append-only inject the new suffix."""
        snapshot = self._recorder.create_snapshot()
        if snapshot is None:
            return
        if snapshot.duration_seconds < self._MIN_AUDIO_S:
            self._unlink(snapshot.file_path)
            return

        try:
            result = self._transcriber.transcribe(snapshot.file_path)
            proc   = self._postprocess.process_text(result.text)
            text   = proc.cleaned_text.strip()
        except Exception:
            self._logger.exception("Streaming poll error")
            return
        finally:
            self._unlink(snapshot.file_path)

        if not text:
            return

        # Append-only guard: only inject if the new transcription is a proper
        # extension of what we've already typed. If Whisper returned a
        # completely different phrase (hallucination), skip — the final pass
        # will correct it after the key is released.
        if text.startswith(self._injected):
            suffix = text[len(self._injected):]
            if suffix:
                try:
                    self._kb.type(suffix)
                    self._injected = text
                    self._logger.debug("Stream append | +%r | total=%r", suffix, self._injected)
                except Exception:
                    self._logger.exception("Stream injection error")
        else:
            self._logger.debug("Stream skipped (diverged) | got=%r | injected=%r",
                               text, self._injected)

    # ── Final correction (runs after hotkey released, Ctrl no longer held) ─────

    def _final_correct(self, audio_path: Path) -> None:
        """Transcribe the full WAV and fix any streaming drift with delta correction."""
        try:
            result = self._transcriber.transcribe(audio_path)
            proc   = self._postprocess.process_text(result.text)
            text   = proc.cleaned_text.strip()
        except Exception:
            self._logger.exception("Final transcription error | path=%s", audio_path)
            return

        if not text:
            self._logger.info("Final transcription returned empty text.")
            return

        prev = self._injected

        # Find longest common prefix between streamed text and final result.
        common = 0
        limit  = min(len(prev), len(text))
        while common < limit and prev[common] == text[common]:
            common += 1

        backspaces = len(prev) - common
        suffix     = text[common:]

        try:
            if backspaces:
                # Ctrl is released at this point → Key.backspace works normally.
                self._send_backspaces(backspaces)
            if suffix:
                self._kb.type(suffix)
            self._injected = text
            self._logger.debug("Final correction | bs=%s | +%r | final=%r",
                               backspaces, suffix, self._injected)
        except Exception:
            self._logger.exception("Final correction injection error")

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _send_backspaces(self, count: int) -> None:
        from pynput.keyboard import Key
        for _ in range(max(0, count)):
            self._kb.press(Key.backspace)
            self._kb.release(Key.backspace)

    @staticmethod
    def _unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
