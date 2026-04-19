from __future__ import annotations

import logging
import time
from pathlib import Path

from app.transcriber import TranscriptionMetadata, TranscriptionResult, TranscriptionSegment, TranscriberError


class GroqTranscriber:
    """Transcribes audio via Groq cloud API (whisper-large-v3-turbo).

    Drop-in replacement for LocalTranscriber — same public interface.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        language_mode: str,
        initial_prompt: str,
        logger: logging.Logger,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._language = None if language_mode == "auto" else language_mode
        self._initial_prompt = initial_prompt
        self._logger = logger
        self._client = None
        self._last_result: TranscriptionResult | None = None

    @property
    def last_result(self) -> TranscriptionResult | None:
        return self._last_result

    def load_model(self) -> None:
        try:
            from groq import Groq
            self._client = Groq(api_key=self._api_key)
            self._logger.info("Groq client ready | model=%s | language=%s", self._model, self._language or "auto")
        except Exception as exc:
            raise TranscriberError("Failed to initialise Groq client.") from exc

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        if self._client is None:
            self.load_model()

        if not audio_path.exists():
            raise TranscriberError(f"Audio file does not exist: '{audio_path}'.")
        if audio_path.stat().st_size <= 0:
            raise TranscriberError(f"Audio file is empty: '{audio_path}'.")

        started_at = time.perf_counter()
        self._logger.info("Groq transcription started | audio=%s | model=%s", audio_path, self._model)

        try:
            with audio_path.open("rb") as f:
                response = self._client.audio.transcriptions.create(
                    file=(audio_path.name, f.read()),
                    model=self._model,
                    language=self._language,
                    response_format="verbose_json",
                    prompt=self._initial_prompt or None,
                    temperature=0.0,
                )
        except Exception as exc:
            raise TranscriberError(f"Groq transcription failed for '{audio_path}'.") from exc

        duration_seconds = time.perf_counter() - started_at

        raw_segments = getattr(response, "segments", None) or []
        segments = tuple(
            TranscriptionSegment(
                start=float(seg.get("start", 0) if isinstance(seg, dict) else getattr(seg, "start", 0)),
                end=float(seg.get("end", 0) if isinstance(seg, dict) else getattr(seg, "end", 0)),
                text=str(seg.get("text", "") if isinstance(seg, dict) else getattr(seg, "text", "")),
            )
            for seg in raw_segments
        )

        transcript_text = (
            "".join(s.text for s in segments).strip()
            if segments
            else (getattr(response, "text", "") or "").strip()
        )

        detected_language = getattr(response, "language", None)
        audio_duration = getattr(response, "duration", None)

        metadata = TranscriptionMetadata(
            model_size=self._model,
            requested_language_mode=self._language or "auto",
            detected_language=detected_language,
            detected_language_probability=None,
            audio_duration_seconds=float(audio_duration) if audio_duration is not None else None,
            transcription_duration_seconds=duration_seconds,
            segment_count=len(segments),
            audio_path=audio_path,
        )
        result = TranscriptionResult(text=transcript_text, metadata=metadata, segments=segments)
        self._last_result = result

        self._logger.info(
            "Groq transcription finished | seconds=%.3f | lang=%s | text=%s",
            duration_seconds,
            detected_language,
            transcript_text,
        )
        return result
