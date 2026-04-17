from __future__ import annotations

import ctypes
import os

# ── Fix ctranslate2 / Intel-MKL memory allocation failure on Windows ──────────
# Must be set BEFORE faster_whisper / ctranslate2 are imported.
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
from app.config import ConfigError, ensure_runtime_paths, load_config
from app.groq_transcriber import GroqTranscriber
from app.history_service import HistoryService
from app.history_window import HistoryWindow
from app.hotkeys import GlobalHotkeyManager, HotkeyRegistrationError
from app.logger import build_emergency_logger, configure_logging
from app.notifications import NotificationManager
from app.overlay import OverlayConfig, RecordingOverlay
from app.settings_dialog import SettingsDialog
from app.single_instance import SingleInstanceError, SingleInstanceGuard
from app.state import StateStore
from app.text_injector import TextInjector
from app.text_postprocess import TextPostprocessor
from app.transcriber import LocalTranscriber
from app.tray import TrayApp


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _clipboard_set(text: str) -> None:
    """Thread-safe Win32 clipboard write. No Qt, no extra libs."""
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE  = 0x0002
    data = (text + "\0").encode("utf-16-le")
    if not ctypes.windll.user32.OpenClipboard(0):
        return
    try:
        ctypes.windll.user32.EmptyClipboard()
        h = ctypes.windll.kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if h:
            p = ctypes.windll.kernel32.GlobalLock(h)
            if p:
                ctypes.memmove(p, data, len(data))
                ctypes.windll.kernel32.GlobalUnlock(h)
                ctypes.windll.user32.SetClipboardData(CF_UNICODETEXT, h)
    finally:
        ctypes.windll.user32.CloseClipboard()


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
        qt_app = QApplication(sys.argv)
        qt_app.setQuitOnLastWindowClosed(False)
        qt_app.setApplicationName(config.app_name)
        qt_app.setApplicationVersion("2.0.0")

        # ── Core state ────────────────────────────────────────────────────────
        state_store = StateStore(logger=logger)

        # ── History window ────────────────────────────────────────────────────
        history_window = HistoryWindow(
            history_file=config.paths.history_file,
            app_name=config.app_name,
            hotkey=config.hotkey.combination,
            on_exit=lambda: _stop_runtime(),
            logger=logger,
        )

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
            on_click=history_window.show_and_raise,
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
        notifier = NotificationManager(logger=logger, enabled=config.notifications.enabled)
        notifier.bind_tray_icon(tray_app)

        # ── Core services ─────────────────────────────────────────────────────
        audio_recorder = AudioRecorder(
            config=config.audio,
            temp_dir=config.paths.temp_dir,
            logger=logger,
        )
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
            logger.info("Transcription backend: Groq | model=%s", config.groq.model)
        else:
            transcriber = LocalTranscriber(
                config=config.transcription,
                models_dir=config.paths.models_dir,
                logger=logger,
            )
            logger.info("Transcription backend: local | model=%s", config.transcription.model_size)

        text_postprocessor = TextPostprocessor(config=config.text_postprocess, logger=logger)

        audio_recorder.set_level_callback(overlay.push_audio_level)

        previous_history_entries = history_service.ensure_ready()
        audio_recorder.cleanup_stale_files()

        # ── Hotkey handlers ───────────────────────────────────────────────────

        def handle_recording_start() -> bool:
            if not state_store.start_recording("Recording..."):
                return False
            try:
                audio_recorder.start_recording()
                return True
            except AudioRecorderError as exc:
                logger.exception("Recording failed to start.")
                state_store.set_error("Recording failed to start.", error=str(exc))
                return False

        def handle_recording_stop() -> bool:
            try:
                result = audio_recorder.stop_recording()
            except AudioRecorderError as exc:
                logger.exception("Recording failed to stop.")
                state_store.set_error("Recording failed to stop.", error=str(exc))
                return False

            if result.ignored:
                state_store.finish_recording("Recording too short.")
                return True

            artifact = result.artifact
            state_store.start_transcribing("Transcribing...")

            final_text = ""
            try:
                if artifact:
                    tr   = transcriber.transcribe(artifact.file_path)
                    proc = text_postprocessor.process_text(tr.text)
                    final_text = proc.cleaned_text.strip()
            except Exception:
                logger.exception("Transcription failed.")
            finally:
                if artifact:
                    audio_recorder.delete_recording_file(artifact.file_path)

            state_store.finish_transcribing("Done.")

            if final_text:
                try:
                    text_injector._controller.type(final_text)
                except Exception:
                    logger.exception("Text injection failed.")

                try:
                    _clipboard_set(final_text)
                except Exception:
                    logger.exception("Clipboard copy failed.")

                tray_app.set_last_transcript_preview(final_text)
                history_window.notify_new_entry()
                try:
                    entry = history_service.build_entry(
                        raw_text=final_text,
                        cleaned_text=final_text,
                        language_mode=config.transcription.language_mode,
                        recording_duration_seconds=artifact.duration_seconds if artifact else 0.0,
                    )
                    history_service.append_entry(entry)
                except Exception:
                    logger.exception("History write failed.")

                logger.info("Transcript: %s", final_text)

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

        # ── Start ─────────────────────────────────────────────────────────────

        def _start_runtime() -> None:
            overlay.start()
            try:
                hotkey_manager.start()
            except HotkeyRegistrationError as exc:
                logger.exception("Hotkey registration failed.")
                state_store.set_error("Hotkey registration failed.", error=str(exc))
                return
            Thread(
                target=transcriber.load_model,
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
            overlay.stop()
            try:
                audio_recorder.stop_recording()
            except AudioRecorderError:
                logger.exception("Recording error during shutdown.")

        # ── Run ───────────────────────────────────────────────────────────────

        if previous_history_entries:
            tray_app.set_last_transcript_preview(previous_history_entries[-1].cleaned_text)

        state_store.mark_ready("Ready.")
        _start_runtime()

        if config.tray.startup_notification:
            notifier.info(config.app_name, f"Готов. Горячая клавиша: {config.hotkey.combination.upper()}")

        exit_code = qt_app.exec()
        _stop_runtime()
        sys.exit(exit_code)

    except ConfigError:
        emergency_logger.exception("Configuration bootstrap failed.")
        raise
    except SingleInstanceError:
        emergency_logger.exception("Second instance launch blocked.")
        raise SystemExit("Voice Prompt Tool is already running.")
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
