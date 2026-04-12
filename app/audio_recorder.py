from __future__ import annotations

import logging
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock, RLock, Thread
from uuid import uuid4

import sounddevice as sd

from app.config import AudioConfig


class AudioRecorderError(RuntimeError):
    """Raised when microphone recording fails."""


@dataclass(frozen=True, slots=True)
class RecordingArtifact:
    file_path: Path
    duration_seconds: float
    sample_rate: int
    channels: int
    frame_count: int


@dataclass(frozen=True, slots=True)
class RecordingResult:
    artifact: RecordingArtifact | None
    ignored: bool
    reason: str | None = None


@dataclass(slots=True)
class _RecordingSession:
    file_path: Path
    stop_event: Event
    ready_event: Event
    finished_event: Event
    thread: Thread
    started_monotonic: float
    frames_captured: int = 0
    error: Exception | None = None
    max_duration_reached: bool = False
    buffer_lock: Lock = field(default_factory=Lock)
    audio_buffer: bytearray = field(default_factory=bytearray)


class AudioRecorder:
    _sample_width_bytes = 2
    _startup_timeout_seconds = 5.0
    _stop_timeout_seconds = 5.0

    def __init__(self, config: AudioConfig, temp_dir: Path, logger: logging.Logger) -> None:
        self._config = config
        self._temp_dir = temp_dir
        self._logger = logger
        self._lock = RLock()
        self._active_session: _RecordingSession | None = None
        self._last_result: RecordingResult | None = None

    @property
    def last_result(self) -> RecordingResult | None:
        with self._lock:
            return self._last_result

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._active_session is not None

    def cleanup_stale_files(self) -> int:
        cutoff_timestamp = time.time() - (self._config.stale_temp_file_age_hours * 3600)
        deleted_count = 0

        self._temp_dir.mkdir(parents=True, exist_ok=True)

        for path in self._temp_dir.glob(f"{self._config.file_prefix}-*.wav"):
            if not path.is_file():
                continue

            try:
                if path.stat().st_mtime >= cutoff_timestamp:
                    continue

                path.unlink()
                deleted_count += 1
            except OSError:
                self._logger.exception("Unable to remove stale temporary audio file: %s", path)

        if deleted_count:
            self._logger.info("Removed stale temporary audio files: %s", deleted_count)

        return deleted_count

    def start_recording(self) -> Path:
        with self._lock:
            if self._active_session is not None:
                raise AudioRecorderError("A recording session is already active.")

            self.cleanup_stale_files()
            session = self._create_session()
            self._active_session = session
            self._last_result = None
            session.thread.start()

        session.ready_event.wait(self._startup_timeout_seconds)

        if not session.ready_event.is_set():
            session.stop_event.set()
            session.thread.join(self._stop_timeout_seconds)
            self._clear_session(session)
            self._delete_file_if_exists(session.file_path)
            raise AudioRecorderError("Timed out while starting microphone recording.")

        if session.error is not None:
            self._clear_session(session)
            self._delete_file_if_exists(session.file_path)
            raise AudioRecorderError("Unable to start microphone recording.") from session.error

        self._logger.info(
            "Recording started | sample_rate=%s | channels=%s | path=%s",
            self._config.sample_rate,
            self._config.channels,
            session.file_path,
        )
        return session.file_path

    def stop_recording(self) -> RecordingResult:
        with self._lock:
            session = self._active_session
            if session is None:
                return RecordingResult(artifact=None, ignored=True, reason="no_active_recording")

            session.stop_event.set()

        session.thread.join(self._stop_timeout_seconds)

        if session.thread.is_alive():
            raise AudioRecorderError("Timed out while stopping microphone recording.")

        with self._lock:
            self._active_session = None

        if session.error is not None:
            self._delete_file_if_exists(session.file_path)
            raise AudioRecorderError("Recording failed.") from session.error

        duration_seconds = session.frames_captured / float(self._config.sample_rate)

        if session.frames_captured <= 0 or duration_seconds < self._config.min_duration_seconds:
            self._delete_file_if_exists(session.file_path)
            self._logger.info(
                "Short recording ignored | duration=%.3f | path=%s",
                duration_seconds,
                session.file_path,
            )
            result = RecordingResult(artifact=None, ignored=True, reason="short_recording")
            with self._lock:
                self._last_result = result
            return result

        artifact = RecordingArtifact(
            file_path=session.file_path,
            duration_seconds=duration_seconds,
            sample_rate=self._config.sample_rate,
            channels=self._config.channels,
            frame_count=session.frames_captured,
        )
        result = RecordingResult(artifact=artifact, ignored=False)

        self._logger.info(
            "Recording stopped | duration=%.3f | path=%s",
            artifact.duration_seconds,
            artifact.file_path,
        )

        with self._lock:
            self._last_result = result

        return result

    def delete_recording_file(self, file_path: Path) -> None:
        self._delete_file_if_exists(file_path)

    def create_snapshot(self, max_duration_seconds: float | None = None) -> RecordingArtifact | None:
        with self._lock:
            session = self._active_session
            if session is None:
                return None

        with session.buffer_lock:
            total_frames = session.frames_captured
            if total_frames <= 0 or not session.audio_buffer:
                return None

            audio_bytes = bytes(session.audio_buffer)

        selected_frames = total_frames
        selected_bytes = audio_bytes

        if max_duration_seconds is not None and max_duration_seconds > 0:
            max_frames = int(self._config.sample_rate * max_duration_seconds)
            if max_frames > 0 and total_frames > max_frames:
                bytes_per_frame = self._sample_width_bytes * self._config.channels
                selected_frames = max_frames
                selected_bytes = audio_bytes[-(max_frames * bytes_per_frame) :]

        if selected_frames <= 0 or not selected_bytes:
            return None

        snapshot_path = self._temp_dir / (
            f"{self._config.file_prefix}-live-{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}.wav"
        )
        try:
            self._write_wav_file(snapshot_path, selected_bytes)
        except OSError as exc:
            raise AudioRecorderError("Unable to write a live preview audio snapshot.") from exc

        return RecordingArtifact(
            file_path=snapshot_path,
            duration_seconds=selected_frames / float(self._config.sample_rate),
            sample_rate=self._config.sample_rate,
            channels=self._config.channels,
            frame_count=selected_frames,
        )

    def _create_session(self) -> _RecordingSession:
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{self._config.file_prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}.wav"
        file_path = self._temp_dir / file_name
        stop_event = Event()
        ready_event = Event()
        finished_event = Event()
        thread = Thread(
            target=self._record_worker,
            args=(file_path, stop_event, ready_event, finished_event),
            daemon=True,
            name="voice-prompt-audio-recorder",
        )

        return _RecordingSession(
            file_path=file_path,
            stop_event=stop_event,
            ready_event=ready_event,
            finished_event=finished_event,
            thread=thread,
            started_monotonic=time.monotonic(),
        )

    def _record_worker(
        self,
        file_path: Path,
        stop_event: Event,
        ready_event: Event,
        finished_event: Event,
    ) -> None:
        session = self._get_session_by_path(file_path)
        if session is None:
            finished_event.set()
            return

        bytes_per_frame = self._sample_width_bytes * self._config.channels
        max_frames = self._config.sample_rate * self._config.max_record_seconds

        try:
            with wave.open(str(file_path), "wb") as wav_handle:
                wav_handle.setnchannels(self._config.channels)
                wav_handle.setsampwidth(self._sample_width_bytes)
                wav_handle.setframerate(self._config.sample_rate)

                with sd.RawInputStream(
                    samplerate=self._config.sample_rate,
                    channels=self._config.channels,
                    dtype="int16",
                    blocksize=self._config.block_frames,
                ) as stream:
                    ready_event.set()

                    while not stop_event.is_set():
                        remaining_frames = max_frames - session.frames_captured
                        if remaining_frames <= 0:
                            session.max_duration_reached = True
                            self._logger.info(
                                "Maximum recording duration reached | seconds=%s | path=%s",
                                self._config.max_record_seconds,
                                file_path,
                            )
                            break

                        requested_frames = min(self._config.block_frames, remaining_frames)
                        data, overflowed = stream.read(requested_frames)

                        if overflowed:
                            self._logger.warning("Audio input overflow detected while recording.")

                        wav_handle.writeframes(data)
                        with session.buffer_lock:
                            session.audio_buffer.extend(data)
                            session.frames_captured += len(data) // bytes_per_frame
        except Exception as exc:
            session.error = exc
            ready_event.set()
            self._logger.exception("Recording error")
        finally:
            finished_event.set()

    def _get_session_by_path(self, file_path: Path) -> _RecordingSession | None:
        with self._lock:
            session = self._active_session
            if session is None or session.file_path != file_path:
                return None
            return session

    def _clear_session(self, session: _RecordingSession) -> None:
        with self._lock:
            if self._active_session is session:
                self._active_session = None

    def _delete_file_if_exists(self, file_path: Path) -> None:
        try:
            if file_path.exists():
                file_path.unlink()
                self._logger.info("Temporary audio file removed: %s", file_path)
        except OSError:
            self._logger.exception("Unable to remove temporary audio file: %s", file_path)

    def _write_wav_file(self, file_path: Path, audio_bytes: bytes) -> None:
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        with wave.open(str(file_path), "wb") as wav_handle:
            wav_handle.setnchannels(self._config.channels)
            wav_handle.setsampwidth(self._sample_width_bytes)
            wav_handle.setframerate(self._config.sample_rate)
            wav_handle.writeframes(audio_bytes)
