from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Iterable

from faster_whisper import WhisperModel

from app.config import TranscriptionConfig


class TranscriberError(RuntimeError):
    """Raised when model loading or transcription fails."""


@dataclass(frozen=True, slots=True)
class TranscriptionSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True, slots=True)
class TranscriptionMetadata:
    model_size: str
    requested_language_mode: str
    detected_language: str | None
    detected_language_probability: float | None
    audio_duration_seconds: float | None
    transcription_duration_seconds: float
    segment_count: int
    audio_path: Path


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    metadata: TranscriptionMetadata
    segments: tuple[TranscriptionSegment, ...]


class LocalTranscriber:
    def __init__(self, config: TranscriptionConfig, models_dir: Path, logger: logging.Logger) -> None:
        self._config = config
        self._models_dir = models_dir
        self._logger = logger
        self._lock = RLock()
        self._model: WhisperModel | None = None
        self._last_result: TranscriptionResult | None = None

    @property
    def last_result(self) -> TranscriptionResult | None:
        return self._last_result

    def load_model(self) -> None:
        with self._lock:
            if self._model is not None:
                return

            self._models_dir.mkdir(parents=True, exist_ok=True)
            started_at = time.perf_counter()
            cpu_threads = self._config.cpu_threads

            if cpu_threads <= 0:
                cpu_threads = max(1, min(os.cpu_count() or 4, 8))

            try:
                self._model = WhisperModel(
                    self._config.model_size,
                    device=self._config.device,
                    compute_type=self._config.compute_type,
                    cpu_threads=cpu_threads,
                    download_root=str(self._models_dir),
                )
            except Exception as exc:
                raise TranscriberError(
                    f"Unable to load faster-whisper model '{self._config.model_size}'."
                ) from exc

            duration_seconds = time.perf_counter() - started_at
            self._logger.info(
                "Model loaded | engine=faster-whisper | model=%s | device=%s | compute_type=%s | cpu_threads=%s | seconds=%.3f | models_dir=%s",
                self._config.model_size,
                self._config.device,
                self._config.compute_type,
                cpu_threads,
                duration_seconds,
                self._models_dir,
            )

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        if self._model is None:
            raise TranscriberError("The transcription model is not loaded.")
        if not audio_path.exists():
            raise TranscriberError(f"Audio file does not exist: '{audio_path}'.")
        if not audio_path.is_file():
            raise TranscriberError(f"Audio path is not a file: '{audio_path}'.")
        if audio_path.stat().st_size <= 0:
            raise TranscriberError(f"Audio file is empty: '{audio_path}'.")

        requested_language = None if self._config.language_mode == "auto" else self._config.language_mode
        started_at = time.perf_counter()
        self._logger.info(
            "Transcription started | audio=%s | model=%s | language_mode=%s | beam_size=%s | best_of=%s | without_timestamps=%s | vad_filter=%s | condition_on_previous_text=%s",
            audio_path,
            self._config.model_size,
            self._config.language_mode,
            self._config.beam_size,
            self._config.best_of,
            self._config.without_timestamps,
            self._config.vad_filter,
            self._config.condition_on_previous_text,
        )

        try:
            segments_iterable, info = self._model.transcribe(
                str(audio_path),
                language=requested_language,
                task="transcribe",
                beam_size=self._config.beam_size,
                best_of=self._config.best_of,
                condition_on_previous_text=self._config.condition_on_previous_text,
                without_timestamps=self._config.without_timestamps,
                vad_filter=self._config.vad_filter,
                initial_prompt=self._config.initial_prompt or None,
                hotwords=self._config.hotwords or None,
                language_detection_segments=self._config.language_detection_segments,
                temperature=[0.0, 0.2, 0.4],
            )
            segments = tuple(self._collect_segments(segments_iterable))
        except Exception as exc:
            raise TranscriberError(f"Local transcription failed for '{audio_path}'.") from exc

        transcript_text = "".join(segment.text for segment in segments).strip()
        duration_seconds = time.perf_counter() - started_at
        detected_language = getattr(info, "language", None)
        language_probability = getattr(info, "language_probability", None)
        audio_duration = getattr(info, "duration", None)

        metadata = TranscriptionMetadata(
            model_size=self._config.model_size,
            requested_language_mode=self._config.language_mode,
            detected_language=detected_language,
            detected_language_probability=language_probability,
            audio_duration_seconds=audio_duration,
            transcription_duration_seconds=duration_seconds,
            segment_count=len(segments),
            audio_path=audio_path,
        )
        result = TranscriptionResult(
            text=transcript_text,
            metadata=metadata,
            segments=segments,
        )
        self._last_result = result

        if detected_language is not None:
            self._logger.info(
                "Detected language | language=%s | probability=%s",
                detected_language,
                language_probability,
            )

        self._logger.info("Transcript text | %s", transcript_text)
        self._logger.info(
            "Transcription finished | audio=%s | seconds=%.3f | segments=%s",
            audio_path,
            duration_seconds,
            len(segments),
        )

        return result

    @staticmethod
    def _collect_segments(segments_iterable: Iterable) -> Iterable[TranscriptionSegment]:
        for segment in segments_iterable:
            yield TranscriptionSegment(
                start=float(segment.start),
                end=float(segment.end),
                text=str(segment.text),
            )
