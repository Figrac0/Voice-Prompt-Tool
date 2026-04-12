from __future__ import annotations

import logging
import sys
import time

from pynput import keyboard


class TextInjectorError(RuntimeError):
    """Raised when text cannot be inserted into the active window."""


class TextInjector:
    def __init__(self, logger: logging.Logger) -> None:
        if sys.platform != "win32":
            raise TextInjectorError("TextInjector supports Windows only.")

        self._logger = logger
        self._controller = keyboard.Controller()

    def paste_from_clipboard(self, settle_delay_seconds: float = 0.05) -> None:
        try:
            time.sleep(settle_delay_seconds)
            with self._controller.pressed(keyboard.Key.ctrl):
                self._controller.press("v")
                self._controller.release("v")
        except Exception as exc:
            raise TextInjectorError("Unable to paste text into the active window.") from exc

        self._logger.info("Active window paste triggered.")
