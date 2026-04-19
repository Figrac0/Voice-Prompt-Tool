from __future__ import annotations

import logging
from typing import Any


class NotificationManager:
    """Routes notifications to the system tray icon and the log."""

    def __init__(self, logger: logging.Logger, enabled: bool = True) -> None:
        self._logger = logger
        self._enabled = enabled
        self._tray: Any | None = None

    def bind_tray_icon(self, tray: Any) -> None:
        self._tray = tray

    def info(self, title: str, message: str) -> None:
        self._dispatch(logging.INFO, title, message)

    def warning(self, title: str, message: str) -> None:
        self._dispatch(logging.WARNING, title, message)

    def error(self, title: str, message: str) -> None:
        self._dispatch(logging.ERROR, title, message)

    def _dispatch(self, level: int, title: str, message: str) -> None:
        self._logger.log(level, "%s | %s", title, message)

        if not self._enabled or self._tray is None:
            return

        try:
            self._tray.notify(title, message, level)
        except Exception:
            self._logger.exception("Unable to show tray notification.")
