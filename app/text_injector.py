from __future__ import annotations

import logging
import sys

from pynput import keyboard


class TextInjector:
    """Thin wrapper around pynput keyboard controller for text injection."""

    def __init__(self, logger: logging.Logger) -> None:
        if sys.platform != "win32":
            raise RuntimeError("TextInjector supports Windows only.")
        self._logger = logger
        self._controller = keyboard.Controller()
