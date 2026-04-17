from __future__ import annotations

import os

# ── Fix ctranslate2 / Intel-MKL memory allocation failure on Windows ──────────
# Must be set BEFORE faster_whisper / ctranslate2 are imported (these env vars
# affect how MKL initialises its internal thread pool and aligned allocator).
os.environ.setdefault("MKL_THREADING_LAYER", "SEQUENTIAL")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("MKL_ENABLE_INSTRUCTIONS", "SSE4_2")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("CT2_INTER_THREADS", "1")
os.environ.setdefault("CT2_INTRA_THREADS", "1")
# ─────────────────────────────────────────────────────────────────────────────

import sys
from pathlib import Path
from threading import Thread

from PySide6.QtWidgets import QApplication

from app.audio_recorder import AudioRecorder, AudioRecorderError
from app.clipboard_service import ClipboardService, ClipboardServiceError
from app.config import ConfigError, TranscriptionConfig, ensure_runtime_paths, load_config
from app.groq_transcriber import GroqTranscriber
from app.history_service import HistoryService, HistoryServiceError
from app.history_window import HistoryWindow
from app.hotkeys import GlobalHotkeyManager, HotkeyRegistrationError
from app.live_preview import LivePreviewError, LivePreviewService
from app.logger import build_emergency_logger, configure_logging
from app.notifications import NotificationManager
from app.overlay import OverlayConfig, RecordingOverlay
from app.processing_worker import BackgroundProcessingWorker, ProcessingJob, ProcessingOutcome
from app.settings_dialog import SettingsDialog
from app.single_instance import SingleInstanceError, SingleInstanceGuard
from app.state import AppState, StateStore
from app.text_injector import TextInjector, TextInjectorError
from app.text_postprocess import TextPostprocessError, TextPostprocessor
from app.transcriber import LocalTranscriber, TranscriberError
from app.tray import TrayApp


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("Voice Prompt Tool supports Windows only.")

    emergency_logger = build_emergency_logger(PROJECT_ROOT)
    instance_guard: SingleInstanceGuard | None = None

    try:
        config = load_config()
        ensure_runtime_paths(config)
        logger = configure_logging(config)
        logger.info("Application bootstrap started.")

        instance_guard = SingleInstanceGuard(
            lock_file=config.paths.temp_dir / f"{config.app_slug}.lock",
            logger=logger,
        )
        instance_guard.acquire()

        # ── Qt application ────────────────────────────────────────────────────
        # Must be created before any QWidget / QSystemTrayIcon.
        qt_app = QApplication(sys.argv)
        qt_app.setQuitOnLastWindowClosed(False)
        qt_app.setApplicationName(config.app_name)
        qt_app.setApplicationVersion("2.0.0")

        # ── Core state ────────────────────────────────────────────────────────
        state_store = StateStore(logger=logger)

        # ── Overlay ───────────────────────────────────────────────────────────
        overlay = RecordingOverlay(
            config=OverlayConfig(
                enabled=config.overlay.enabled,
                size=config.overlay.size,
                margin=config.overlay.margin,
                idle_alpha=config.overlay.idle_alpha,
                recording_alpha=config.overlay.recording_alpha,
                transcribing_alpha=config.overlay.transcribing_alpha,
                idle_color=config.overlay.idle_color,
                recording_color=config.overlay.recording_color,
                transcribing_color=config.overlay.transcribing_color,
            ),
            state_store=state_store,
            logger=logger,
        )

        # ── History window ────────────────────────────────────────────────────
        history_window = HistoryWindow(
            history_file=config.paths.history_file,
            app_name=config.app_name,
            hotkey=config.hotkey.combination,
            on_exit=lambda: _stop_runtime(),
            logger=logger,
        )

        # ── Settings dialog (created on demand) ───────────────────────────────
        _settings_dialog: SettingsDialog | None = None

        def open_settings() -> None:
            nonlocal _settings_dialog
            if _settings_dialog is None or not _settings_dialog.isVisible():
                _settings_dialog = SettingsDialog(config.paths.config_file)
            _settings_dialog.show()
            _settings_dialog.raise_()
            _settings_dialog.activateWindow()

        # ── Tray ──────────────────────────────────────────────────────────────
        tray_app = TrayApp(
            config=config,
            logger=logger,
            state_store=state_store,
            on_exit=lambda: _stop_runtime(),
            on_open_settings=open_settings,
            on_open_history=history_window.show_and_raise,
        )

        # ── Notifications ─────────────────────────────────────────────────────
        notifier = NotificationManager(
            logger=logger,
            enabled=config.notifications.enabled,
        )
        notifier.bind_tray_icon(tray_app)

        # ── Services ──────────────────────────────────────────────────────────
        audio_recorder = AudioRecorder(
            config=config.audio,
            temp_dir=config.paths.temp_dir,
            logger=logger,
        )
        clipboard_service = ClipboardService(logger=logger)
        text_injector = TextInjector(logger=logger)
        history_service = HistoryService(
            history_file=config.paths.history_file,
            limit=config.history_limit,
            logger=logger,
        )
        if config.groq.enabled and config.groq.api_key:
            transcriber = GroqTranscriber(
                api_key=config.groq.api_key,
                model=config.groq.model,
                language_mode=config.transcription.language_mode,
                initial_prompt=config.transcription.initial_prompt,
                logger=logger,
            )
            logger.info("Transcription backend: Groq API | model=%s", config.groq.model)
        else:
            transcriber = LocalTranscriber(
                config=config.transcription,
                models_dir=config.paths.models_dir,
                logger=logger,
            )
            logger.info("Transcription backend: local faster-whisper | model=%s", config.transcription.model_size)
        text_postprocessor = TextPostprocessor(
            config=config.text_postprocess,
            logger=logger,
        )
        preview_transcriber = LocalTranscriber(
            config=TranscriptionConfig(
                model_size=config.live_preview.model_size,
                language_mode=config.live_preview.language_mode,
                device=config.live_preview.device,
                compute_type=config.live_preview.compute_type,
                cpu_threads=config.transcription.cpu_threads,
                beam_size=config.live_preview.beam_size,
                best_of=config.live_preview.best_of,
                condition_on_previous_text=config.live_preview.condition_on_previous_text,
                without_timestamps=config.live_preview.without_timestamps,
                vad_filter=config.live_preview.vad_filter,
                initial_prompt=config.transcription.initial_prompt,
                hotwords=config.transcription.hotwords,
                language_detection_segments=config.transcription.language_detection_segments,
            ),
            models_dir=config.paths.models_dir,
            logger=logger,
        )
        live_preview_service = LivePreviewService(
            config=config.live_preview,
            audio_recorder=audio_recorder,
            transcriber=preview_transcriber,
            text_postprocessor=text_postprocessor,
            text_injector=text_injector,
            clipboard_service=clipboard_service,
            logger=logger,
        )
        live_preview_service.set_text_update_callback(overlay.update_live_text)

        previous_history_entries = history_service.ensure_ready()
        audio_recorder.cleanup_stale_files()
        latest_sequence_id = 0

        # ── Background job processor ──────────────────────────────────────────

        def process_recording_job(job: ProcessingJob) -> ProcessingOutcome:
            nonlocal latest_sequence_id
            audio_path = Path(job.audio_path)
            completion_detail = "Processing finished. Ready."
            cleanup_processed_audio = False

            try:
                transcription_result = transcriber.transcribe(audio_path)
                postprocess_result = text_postprocessor.process_text(transcription_result.text)

                if postprocess_result.raw_text.strip() or postprocess_result.cleaned_text.strip():
                    history_entry = history_service.build_entry(
                        raw_text=postprocess_result.raw_text,
                        cleaned_text=postprocess_result.cleaned_text,
                        language_mode=transcription_result.metadata.requested_language_mode,
                        recording_duration_seconds=job.recording_duration_seconds,
                    )
                    try:
                        history_service.append_entry(history_entry)
                    except HistoryServiceError:
                        logger.exception("History write failed.")
                        notifier.error(config.app_name, "Не удалось сохранить историю")
                        completion_detail = "History save failed. Ready."

                is_latest = job.sequence_id == latest_sequence_id

                if postprocess_result.cleaned_text:
                    tray_app.set_last_transcript_preview(postprocess_result.cleaned_text)
                    history_window.notify_new_entry()

                    if not is_latest:
                        logger.info("Skipping stale sequence %s (latest=%s)", job.sequence_id, latest_sequence_id)
                        completion_detail = "Skipped stale dictation result. Ready."
                    elif config.text_postprocess.auto_copy or config.text_postprocess.auto_paste:
                        try:
                            clipboard_service.copy_text(postprocess_result.cleaned_text)
                        except ClipboardServiceError:
                            logger.exception("Clipboard copy failed.")
                            notifier.error(config.app_name, "Не удалось скопировать текст")
                            completion_detail = "Clipboard copy failed. Ready."
                        else:
                            if config.text_postprocess.auto_paste:
                                try:
                                    replaced = live_preview_service.apply_final_text(
                                        postprocess_result.cleaned_text
                                    )
                                except LivePreviewError:
                                    replaced = False
                                    logger.exception("Live preview finalization failed.")
                                    notifier.error(config.app_name, "Ошибка обновления текста")
                                    completion_detail = "Live text update failed. Ready."
                                else:
                                    if replaced:
                                        notifier.info(config.app_name, "Текст вставлен")

                                if not replaced:
                                    try:
                                        text_injector.paste_from_clipboard()
                                    except TextInjectorError:
                                        logger.exception("Active window paste failed.")
                                        notifier.error(config.app_name, "Не удалось вставить текст")
                                        completion_detail = "Text paste failed. Ready."
                                    else:
                                        notifier.info(config.app_name, "Текст вставлен")

                            if config.text_postprocess.auto_copy:
                                notifier.info(config.app_name, "Текст скопирован")
                    else:
                        logger.info("Clipboard copy and auto-paste are disabled.")
                else:
                    if config.text_postprocess.auto_paste and live_preview_service.enabled:
                        try:
                            live_preview_service.apply_final_text("")
                        except LivePreviewError:
                            logger.exception("Unable to discard empty live preview.")
                    logger.info("Cleaned text is empty. Skipping clipboard.")
                    notifier.warning(config.app_name, "Текст не распознан")
                    completion_detail = "Empty recognition result. Ready."

                logger.info(
                    "Transcript | lang=%s | raw=%s | clean=%s",
                    transcription_result.metadata.detected_language,
                    transcription_result.text,
                    postprocess_result.cleaned_text,
                )
                cleanup_processed_audio = True
                return ProcessingOutcome(success=True, detail=completion_detail)

            except TranscriberError as exc:
                logger.exception("Transcription error")
                notifier.error(config.app_name, "Ошибка распознавания")
                return ProcessingOutcome(success=False, detail="Transcription failed.", error=str(exc))
            except TextPostprocessError as exc:
                logger.exception("Post-processing error")
                notifier.error(config.app_name, "Ошибка обработки текста")
                return ProcessingOutcome(success=False, detail="Post-processing failed.", error=str(exc))
            finally:
                if cleanup_processed_audio:
                    audio_recorder.delete_recording_file(audio_path)

        def handle_processing_finished(
            job: ProcessingJob, outcome: ProcessingOutcome, remaining: int
        ) -> None:
            snapshot = state_store.snapshot()
            if outcome.success:
                if (
                    remaining == 0
                    and not audio_recorder.is_recording
                    and snapshot.state is AppState.TRANSCRIBING
                ):
                    state_store.finish_transcribing(outcome.detail)
                return
            logger.warning("Background processing failed | %s | remaining=%s", outcome.error, remaining)
            if remaining == 0 and not audio_recorder.is_recording:
                state_store.set_error(outcome.detail, error=outcome.error)

        processing_worker = BackgroundProcessingWorker(
            logger=logger,
            processor=process_recording_job,
            on_job_finished=handle_processing_finished,
        )

        # ── Hotkey handlers ───────────────────────────────────────────────────

        def handle_recording_start() -> bool:
            nonlocal latest_sequence_id
            if not state_store.start_recording("Hotkey held. Recording microphone."):
                return False

            latest_sequence_id += 1
            try:
                clipboard_service.clear()
            except ClipboardServiceError:
                logger.exception("Unable to clear clipboard before recording.")

            try:
                audio_recorder.start_recording()
            except AudioRecorderError as exc:
                logger.exception("Recording error")
                state_store.set_error("Recording failed to start.", error=str(exc))
                notifier.error(config.app_name, "Не удалось начать запись")
                return False

            if config.text_postprocess.auto_paste and live_preview_service.enabled:
                live_preview_service.start_session()

            notifier.info(config.app_name, "Запись началась")
            return True

        def handle_recording_stop() -> bool:
            if config.text_postprocess.auto_paste and live_preview_service.enabled:
                live_preview_service.stop_session(discard_preview=False)

            try:
                recording_result = audio_recorder.stop_recording()
            except AudioRecorderError as exc:
                logger.exception("Recording error")
                state_store.set_error("Recording failed to stop.", error=str(exc))
                notifier.error(config.app_name, "Ошибка записи")
                return False

            if recording_result.ignored:
                if state_store.snapshot().state is AppState.RECORDING:
                    state_store.finish_recording("Recording ignored.")
                if config.text_postprocess.auto_paste and live_preview_service.enabled:
                    try:
                        live_preview_service.apply_final_text("")
                    except LivePreviewError:
                        logger.exception("Unable to discard ignored live preview.")
                if recording_result.reason == "short_recording":
                    notifier.warning(config.app_name, "Запись слишком короткая")
                return True

            artifact = recording_result.artifact
            if artifact is None:
                if state_store.snapshot().state is AppState.RECORDING:
                    state_store.finish_recording("No recording artifact.")
                if config.text_postprocess.auto_paste and live_preview_service.enabled:
                    try:
                        live_preview_service.apply_final_text("")
                    except LivePreviewError:
                        logger.exception("Unable to discard empty live preview.")
                notifier.warning(config.app_name, "Пустая запись проигнорирована")
                return False

            if not state_store.start_transcribing("Recording stopped. Transcribing..."):
                audio_recorder.delete_recording_file(artifact.file_path)
                return False

            # Immediately push the live-preview draft so user sees text fast
            quick_text = live_preview_service.current_text.strip()
            if quick_text:
                try:
                    clipboard_service.copy_text(quick_text)
                    if config.text_postprocess.auto_paste:
                        text_injector.paste_from_clipboard(settle_delay_seconds=0.01)
                except (ClipboardServiceError, TextInjectorError):
                    logger.exception("Quick-publish from live preview failed.")

            notifier.info(config.app_name, "Обработка...")
            processing_worker.enqueue(
                ProcessingJob(
                    audio_path=str(artifact.file_path),
                    recording_duration_seconds=artifact.duration_seconds,
                    sequence_id=latest_sequence_id,
                )
            )
            return True

        hotkey_manager = GlobalHotkeyManager(
            config=config.hotkey,
            logger=logger,
            state_store=state_store,
            notifier=notifier,
            app_name=config.app_name,
            on_recording_start=handle_recording_start,
            on_recording_stop=handle_recording_stop,
        )

        # ── Warm-up helpers ───────────────────────────────────────────────────

        def _warm_up_models_sequential() -> None:
            # Live-preview model (only if enabled)
            if config.live_preview.enabled:
                try:
                    preview_transcriber.load_model()
                    with live_preview_service._lock:
                        live_preview_service._model_loaded = True
                    logger.info("Live-preview model loaded.")
                except TranscriberError:
                    logger.exception("Live-preview model warm-up failed.")

            # Final transcription model (Groq just initialises the HTTP client)
            try:
                transcriber.load_model()
            except TranscriberError:
                logger.exception("Final model warm-up failed.")
                notifier.error(config.app_name, "Ошибка загрузки модели распознавания")

        def _start_runtime() -> None:
            overlay.start()
            processing_worker.start()

            try:
                hotkey_manager.start()
            except HotkeyRegistrationError as exc:
                processing_worker.stop()
                logger.exception("Hotkey registration failed.")
                state_store.set_error("Hotkey registration failed.", error=str(exc))
                notifier.error(config.app_name, "Не удалось зарегистрировать горячую клавишу")
                return

            Thread(
                target=_warm_up_models_sequential,
                daemon=True,
                name="voice-prompt-model-warmup",
            ).start()

        _runtime_stopped = False

        def _stop_runtime() -> None:
            nonlocal _runtime_stopped
            if _runtime_stopped:
                return
            _runtime_stopped = True

            hotkey_manager.stop()
            live_preview_service.stop_session(discard_preview=False)
            overlay.stop()

            try:
                audio_recorder.stop_recording()
            except AudioRecorderError:
                logger.exception("Recording error during shutdown.")

            processing_worker.stop()

        # ── Initialise history and start ──────────────────────────────────────

        if previous_history_entries:
            tray_app.set_last_transcript_preview(previous_history_entries[-1].cleaned_text)

        state_store.mark_ready("Background service is running.")
        _start_runtime()

        if config.tray.startup_notification:
            notifier.info(
                config.app_name,
                f"Готов. Горячая клавиша: {config.hotkey.combination.upper()}",
            )

        # ── Qt main loop ──────────────────────────────────────────────────────
        exit_code = qt_app.exec()

        _stop_runtime()
        sys.exit(exit_code)

    except ConfigError:
        emergency_logger.exception("Configuration bootstrap failed.")
        raise
    except SingleInstanceError:
        emergency_logger.exception("Second instance launch blocked.")
        raise SystemExit("Voice Prompt Tool is already running. Close the older instance first.")
    except Exception as exc:
        emergency_logger.exception("Unexpected startup failure.")
        try:
            state_store.set_error("Startup failed.", error=str(exc))  # type: ignore[possibly-undefined]
        except UnboundLocalError:
            pass
        raise
    finally:
        if instance_guard is not None:
            instance_guard.release()


if __name__ == "__main__":
    main()
