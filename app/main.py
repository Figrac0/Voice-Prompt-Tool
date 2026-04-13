from __future__ import annotations

import sys
from pathlib import Path
from threading import Thread

from app.audio_recorder import AudioRecorder, AudioRecorderError
from app.clipboard_service import ClipboardService, ClipboardServiceError
from app.config import ConfigError, TranscriptionConfig, ensure_runtime_paths, load_config
from app.history_service import HistoryService, HistoryServiceError
from app.hotkeys import GlobalHotkeyManager, HotkeyRegistrationError
from app.live_preview import LivePreviewError, LivePreviewService
from app.logger import build_emergency_logger, configure_logging
from app.notifications import NotificationManager
from app.processing_worker import BackgroundProcessingWorker, ProcessingJob, ProcessingOutcome
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

        state_store = StateStore(logger=logger)
        notifier = NotificationManager(
            logger=logger,
            enabled=config.notifications.enabled,
        )
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
        transcriber = LocalTranscriber(
            config=config.transcription,
            models_dir=config.paths.models_dir,
            logger=logger,
        )
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
        previous_history_entries = history_service.ensure_ready()
        audio_recorder.cleanup_stale_files()

        tray_app: TrayApp | None = None

        def process_recording_job(job: ProcessingJob) -> ProcessingOutcome:
            audio_path = Path(job.audio_path)
            completion_detail = "Processing finished. Ready."
            cleanup_processed_audio = False

            try:
                transcription_result = transcriber.transcribe(audio_path)
                postprocess_result = text_postprocessor.process_text(transcription_result.text)
                logger.info("Raw and cleaned transcription are available in memory for next stages.")

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
                        notifier.error(config.app_name, "History save failed")
                        completion_detail = "History save failed. Ready."

                if postprocess_result.cleaned_text:
                    if tray_app is not None:
                        tray_app.set_last_transcript_preview(postprocess_result.cleaned_text)

                    if config.text_postprocess.auto_copy or config.text_postprocess.auto_paste:
                        try:
                            clipboard_service.copy_text(postprocess_result.cleaned_text)
                        except ClipboardServiceError:
                            logger.exception("Clipboard copy failed.")
                            notifier.error(config.app_name, "Clipboard copy failed")
                            completion_detail = "Clipboard copy failed. Ready."
                        else:
                            if config.text_postprocess.auto_paste:
                                try:
                                    live_preview_replaced = live_preview_service.apply_final_text(
                                        postprocess_result.cleaned_text
                                    )
                                except LivePreviewError:
                                    live_preview_replaced = False
                                    logger.exception("Live preview finalization failed.")
                                    notifier.error(config.app_name, "Live text update failed")
                                    completion_detail = "Live text update failed. Ready."
                                else:
                                    if live_preview_replaced:
                                        notifier.info(config.app_name, "Text pasted into active field")

                                if not live_preview_replaced:
                                    try:
                                        text_injector.paste_from_clipboard()
                                    except TextInjectorError:
                                        logger.exception("Active window paste failed.")
                                        notifier.error(config.app_name, "Text paste failed")
                                        completion_detail = "Text paste failed. Ready."
                                    else:
                                        notifier.info(config.app_name, "Text pasted into active field")

                            if config.text_postprocess.auto_copy:
                                notifier.info(config.app_name, "Text copied to clipboard")
                    else:
                        logger.info("Clipboard copy and auto-paste are disabled by configuration.")
                else:
                    if config.text_postprocess.auto_paste and live_preview_service.enabled:
                        try:
                            live_preview_service.apply_final_text("")
                        except LivePreviewError:
                            logger.exception("Unable to discard empty live preview text.")
                    logger.info("Cleaned text is empty. Clipboard copy skipped.")
                    notifier.warning(config.app_name, "Recognized text is empty. Clipboard not updated")
                    completion_detail = "Recognized text is empty. Ready."

                logger.info(
                    "Last transcript summary | language=%s | raw_text=%s | cleaned_text=%s",
                    transcription_result.metadata.detected_language,
                    transcription_result.text,
                    postprocess_result.cleaned_text,
                )
                cleanup_processed_audio = True
                return ProcessingOutcome(success=True, detail=completion_detail)
            except TranscriberError as exc:
                logger.exception("Transcription error")
                notifier.error(config.app_name, "Transcription failed")
                return ProcessingOutcome(
                    success=False,
                    detail="Local transcription failed.",
                    error=str(exc),
                )
            except TextPostprocessError as exc:
                logger.exception("Text post-processing error")
                notifier.error(config.app_name, "Text processing failed")
                return ProcessingOutcome(
                    success=False,
                    detail="Text post-processing failed.",
                    error=str(exc),
                )
            finally:
                if cleanup_processed_audio:
                    audio_recorder.delete_recording_file(audio_path)

        def handle_processing_finished(
            job: ProcessingJob,
            outcome: ProcessingOutcome,
            remaining: int,
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

            logger.warning(
                "Background processing failed | audio=%s | remaining=%s | recording=%s | detail=%s | error=%s",
                job.audio_path,
                remaining,
                audio_recorder.is_recording,
                outcome.detail,
                outcome.error,
            )

            if remaining == 0 and not audio_recorder.is_recording:
                state_store.set_error(outcome.detail, error=outcome.error)

        processing_worker = BackgroundProcessingWorker(
            logger=logger,
            processor=process_recording_job,
            on_job_finished=handle_processing_finished,
        )

        def handle_recording_start() -> bool:
            if not state_store.start_recording("Hotkey is held. Recording microphone audio."):
                if state_store.snapshot().state is AppState.TRANSCRIBING:
                    notifier.warning(config.app_name, "Wait until the previous dictation is finalized")
                return False

            try:
                audio_recorder.start_recording()
            except AudioRecorderError as exc:
                logger.exception("Recording error")
                state_store.set_error("Recording failed to start.", error=str(exc))
                notifier.error(config.app_name, "Recording failed to start")
                return False

            if config.text_postprocess.auto_paste and live_preview_service.enabled:
                live_preview_service.start_session()

            notifier.info(config.app_name, "Recording started")
            return True

        def handle_recording_stop() -> bool:
            if config.text_postprocess.auto_paste and live_preview_service.enabled:
                live_preview_service.stop_session(discard_preview=False)

            try:
                recording_result = audio_recorder.stop_recording()
            except AudioRecorderError as exc:
                logger.exception("Recording error")
                state_store.set_error("Recording failed to stop cleanly.", error=str(exc))
                notifier.error(config.app_name, "Recording failed")
                return False

            if recording_result.ignored:
                if state_store.snapshot().state is AppState.RECORDING:
                    state_store.finish_recording("Hotkey released. Recording ignored.")

                if config.text_postprocess.auto_paste and live_preview_service.enabled:
                    try:
                        live_preview_service.apply_final_text("")
                    except LivePreviewError:
                        logger.exception("Unable to discard ignored live preview text.")

                if recording_result.reason == "short_recording":
                    notifier.warning(config.app_name, "Short recording ignored")

                return True

            artifact = recording_result.artifact
            if artifact is None:
                if state_store.snapshot().state is AppState.RECORDING:
                    state_store.finish_recording("Hotkey released. No recording artifact available.")
                if config.text_postprocess.auto_paste and live_preview_service.enabled:
                    try:
                        live_preview_service.apply_final_text("")
                    except LivePreviewError:
                        logger.exception("Unable to discard empty live preview text.")
                notifier.warning(config.app_name, "Empty recording ignored")
                return False

            if not state_store.start_transcribing("Recording stopped. Starting local transcription."):
                audio_recorder.delete_recording_file(artifact.file_path)
                return False

            notifier.info(config.app_name, "Transcribing")
            processing_worker.enqueue(
                ProcessingJob(
                    audio_path=str(artifact.file_path),
                    recording_duration_seconds=artifact.duration_seconds,
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

        def warm_up_final_model_async() -> None:
            def worker() -> None:
                try:
                    transcriber.load_model()
                except TranscriberError:
                    logger.exception("Final transcription model warm-up failed.")
                    notifier.error(config.app_name, "Final transcription model warm-up failed")

            Thread(
                target=worker,
                daemon=True,
                name="voice-prompt-final-model-warmup",
            ).start()

        def start_runtime() -> None:
            processing_worker.start()

            try:
                hotkey_manager.start()
            except HotkeyRegistrationError as exc:
                processing_worker.stop()
                logger.exception("Global hotkey registration failed.")
                state_store.set_error("Global hotkey registration failed.", error=str(exc))
                notifier.error(config.app_name, "Global hotkey registration failed")
                return

            live_preview_service.warm_up_async()
            warm_up_final_model_async()

        def stop_runtime() -> None:
            hotkey_manager.stop()
            live_preview_service.stop_session(discard_preview=False)

            try:
                audio_recorder.stop_recording()
            except AudioRecorderError:
                logger.exception("Recording error during shutdown.")

            processing_worker.stop()

        tray_app = TrayApp(
            config=config,
            logger=logger,
            state_store=state_store,
            notifier=notifier,
            on_ready=start_runtime,
            on_exit=stop_runtime,
        )

        if previous_history_entries:
            tray_app.set_last_transcript_preview(previous_history_entries[-1].cleaned_text)

        tray_app.run()
    except ConfigError:
        emergency_logger.exception("Configuration bootstrap failed.")
        raise
    except SingleInstanceError:
        emergency_logger.exception("A second instance launch was blocked.")
        raise SystemExit("Voice Prompt Tool is already running. Close the older instance first.")
    except Exception as exc:
        emergency_logger.exception("Unexpected startup failure.")

        try:
            state_store.set_error("Startup failed.", error=str(exc))
        except UnboundLocalError:
            pass

        raise
    finally:
        if instance_guard is not None:
            instance_guard.release()


if __name__ == "__main__":
    main()
