from __future__ import annotations

import logging
from threading import Event, RLock, Thread

from app.audio_recorder import AudioRecorder, AudioRecorderError
from app.clipboard_service import ClipboardService
from app.config import LivePreviewConfig
from app.text_injector import TextInjector, TextInjectorError
from app.text_postprocess import TextPostprocessor
from app.transcriber import LocalTranscriber, TranscriberError


class LivePreviewError(RuntimeError):
    """Raised when the live preview pipeline fails critically."""


class LivePreviewService:
    def __init__(
        self,
        config: LivePreviewConfig,
        audio_recorder: AudioRecorder,
        transcriber: LocalTranscriber,
        text_postprocessor: TextPostprocessor,
        text_injector: TextInjector,
        clipboard_service: ClipboardService,
        logger: logging.Logger,
    ) -> None:
        self._config = config
        self._audio_recorder = audio_recorder
        self._transcriber = transcriber
        self._text_postprocessor = text_postprocessor
        self._text_injector = text_injector
        self._clipboard_service = clipboard_service
        self._logger = logger
        self._lock = RLock()
        self._stop_event: Event | None = None
        self._thread: Thread | None = None
        self._warmup_thread: Thread | None = None
        self._model_loaded = False

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def current_text(self) -> str:
        return self._text_injector.live_text

    def warm_up_async(self) -> None:
        if not self._config.enabled:
            return

        with self._lock:
            if self._model_loaded:
                return

            if self._warmup_thread is not None and self._warmup_thread.is_alive():
                return

            self._warmup_thread = Thread(
                target=self._warm_up_model,
                daemon=True,
                name="voice-prompt-live-preview-warmup",
            )
            self._warmup_thread.start()

    def start_session(self) -> None:
        if not self._config.enabled:
            return

        with self._lock:
            thread = self._thread
            if thread is not None and thread.is_alive():
                return

            self._text_injector.begin_live_session()
            stop_event = Event()
            self._stop_event = stop_event
            self._thread = Thread(
                target=self._preview_loop,
                args=(stop_event,),
                daemon=True,
                name="voice-prompt-live-preview",
            )
            self._thread.start()

        self._logger.info("Live preview session started.")

    def stop_session(self, discard_preview: bool = False, timeout_seconds: float = 0.75) -> None:
        if not self._config.enabled:
            return

        with self._lock:
            stop_event = self._stop_event
            thread = self._thread
            self._stop_event = None
            self._thread = None

        if stop_event is not None:
            stop_event.set()

        if thread is not None and thread.is_alive():
            thread.join(timeout_seconds)

        if discard_preview:
            self._discard_preview()

        self._logger.info("Live preview session stopped | discarded=%s", discard_preview)

    def apply_final_text(self, text: str) -> bool:
        if not self._config.enabled:
            return False

        normalized_text = text.strip()

        try:
            if normalized_text:
                self._text_injector.finalize_live_session(normalized_text, self._clipboard_service)
            else:
                self._discard_preview()
        except TextInjectorError as exc:
            raise LivePreviewError("Unable to replace live preview with final text.") from exc

        return True

    def clear_session_state(self) -> None:
        self._text_injector.clear_live_session()

    def _preview_loop(self, stop_event: Event) -> None:
        try:
            self._ensure_model_loaded()
        except TranscriberError:
            self._logger.exception("Live preview model failed to load.")
            return

        while not stop_event.is_set():
            if stop_event.wait(self._config.update_interval_seconds):
                break

            try:
                snapshot = self._audio_recorder.create_snapshot(
                    max_duration_seconds=self._config.max_preview_window_seconds
                )
            except AudioRecorderError:
                self._logger.exception("Live preview snapshot creation failed.")
                continue

            if snapshot is None:
                continue

            try:
                if snapshot.duration_seconds < self._config.min_audio_seconds:
                    continue

                result = self._transcriber.transcribe(snapshot.file_path)
                if stop_event.is_set():
                    continue
                postprocessed = self._text_postprocessor.process_text(result.text)
                preview_text = postprocessed.cleaned_text.strip()

                if not preview_text:
                    continue

                if stop_event.is_set():
                    continue
                self._text_injector.replace_live_text(preview_text, self._clipboard_service)
            except (TranscriberError, TextInjectorError):
                self._logger.exception("Live preview update failed.")
            finally:
                self._audio_recorder.delete_recording_file(snapshot.file_path)

    def _warm_up_model(self) -> None:
        try:
            self._ensure_model_loaded()
        except TranscriberError:
            self._logger.exception("Live preview model warm-up failed.")

    def _ensure_model_loaded(self) -> None:
        with self._lock:
            if self._model_loaded:
                return

        self._transcriber.load_model()

        with self._lock:
            self._model_loaded = True

        self._logger.info("Live preview model loaded.")

    def _discard_preview(self) -> None:
        try:
            self._text_injector.discard_live_session(self._clipboard_service)
        except TextInjectorError:
            self._logger.exception("Unable to discard live preview text.")
