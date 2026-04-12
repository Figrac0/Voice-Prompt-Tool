from __future__ import annotations

import logging
import sys
import time
from threading import RLock

from pynput import keyboard

from app.clipboard_service import ClipboardService, ClipboardServiceError


class TextInjectorError(RuntimeError):
    """Raised when text cannot be inserted into the active window."""


class TextInjector:
    def __init__(self, logger: logging.Logger) -> None:
        if sys.platform != "win32":
            raise TextInjectorError("TextInjector supports Windows only.")

        self._logger = logger
        self._controller = keyboard.Controller()
        self._lock = RLock()
        self._live_text = ""

    @property
    def live_text(self) -> str:
        with self._lock:
            return self._live_text

    def begin_live_session(self) -> None:
        with self._lock:
            self._live_text = ""

        self._logger.info("Live text session started.")

    def replace_live_text(
        self,
        text: str,
        clipboard_service: ClipboardService,
        settle_delay_seconds: float = 0.02,
    ) -> bool:
        normalized_text = self._normalize_text(text)

        with self._lock:
            previous_text = self._live_text
            if normalized_text == previous_text:
                return False

            self._replace_text(previous_text, normalized_text, clipboard_service, settle_delay_seconds)
            self._live_text = normalized_text

        self._logger.info("Live text updated | characters=%s", len(normalized_text))
        return True

    def finalize_live_session(
        self,
        final_text: str,
        clipboard_service: ClipboardService,
        settle_delay_seconds: float = 0.02,
    ) -> None:
        self.replace_live_text(final_text, clipboard_service, settle_delay_seconds)
        self._logger.info("Live text session finalized.")

    def discard_live_session(
        self,
        clipboard_service: ClipboardService,
        settle_delay_seconds: float = 0.02,
    ) -> None:
        with self._lock:
            previous_text = self._live_text
            if not previous_text:
                return

            self._replace_text(previous_text, "", clipboard_service, settle_delay_seconds)
            self._live_text = ""

        self._logger.info("Live text session discarded.")

    def clear_live_session(self) -> None:
        with self._lock:
            self._live_text = ""

        self._logger.info("Live text session state cleared.")

    def paste_from_clipboard(self, settle_delay_seconds: float = 0.05) -> None:
        try:
            time.sleep(settle_delay_seconds)
            with self._controller.pressed(keyboard.Key.ctrl):
                self._controller.press("v")
                self._controller.release("v")
        except Exception as exc:
            raise TextInjectorError("Unable to paste text into the active window.") from exc

        self._logger.info("Active window paste triggered.")

    def _replace_text(
        self,
        previous_text: str,
        next_text: str,
        clipboard_service: ClipboardService,
        settle_delay_seconds: float,
    ) -> None:
        try:
            time.sleep(settle_delay_seconds)
            self._send_backspaces(len(previous_text))

            if next_text:
                clipboard_service.copy_text(next_text)
                self.paste_from_clipboard(settle_delay_seconds=0.01)
        except ClipboardServiceError as exc:
            raise TextInjectorError("Unable to update text in the active window.") from exc
        except Exception as exc:
            raise TextInjectorError("Unable to update text in the active window.") from exc

    def _send_backspaces(self, count: int) -> None:
        for _ in range(max(0, count)):
            self._controller.press(keyboard.Key.backspace)
            self._controller.release(keyboard.Key.backspace)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return text.replace("\r\n", "\n").replace("\r", "\n")
