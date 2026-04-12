from __future__ import annotations

import logging
from typing import Any


class NotificationManager:
    def __init__(self, logger: logging.Logger, enabled: bool = True) -> None:
        self._logger = logger
        self._enabled = enabled
        self._tray_icon: Any | None = None

    def bind_tray_icon(self, tray_icon: Any) -> None:
        self._tray_icon = tray_icon

    def info(self, title: str, message: str) -> None:
        self._dispatch(logging.INFO, title, message)

    def warning(self, title: str, message: str) -> None:
        self._dispatch(logging.WARNING, title, message)

    def error(self, title: str, message: str) -> None:
        self._dispatch(logging.ERROR, title, message)

    def _dispatch(self, level: int, title: str, message: str) -> None:
        self._logger.log(level, "%s | %s", title, message)

        if not self._enabled or self._tray_icon is None:
            return

        try:
            self._tray_icon.notify(message, title)
        except Exception:
            self._logger.exception("Unable to show local notification.")
