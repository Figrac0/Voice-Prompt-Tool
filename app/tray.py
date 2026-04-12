from __future__ import annotations

import logging
import os
from typing import Callable

import pystray
from PIL import Image, ImageDraw

from app.config import AppConfig
from app.notifications import NotificationManager
from app.state import StateSnapshot, StateStore


class TrayApp:
    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        state_store: StateStore,
        notifier: NotificationManager,
        on_ready: Callable[[], None] | None = None,
        on_exit: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self._logger = logger
        self._state_store = state_store
        self._notifier = notifier
        self._on_ready = on_ready
        self._on_exit = on_exit
        self._last_transcript_preview: str | None = None

        self._icon = pystray.Icon(
            name=config.app_slug,
            icon=self._build_icon_image(),
            title=config.tray.tooltip,
            menu=pystray.Menu(
                pystray.MenuItem("Show current status", self._show_status, default=True),
                pystray.MenuItem("Open history file", self._open_history_file),
                pystray.MenuItem("Exit", self._exit_app),
            ),
        )

        self._notifier.bind_tray_icon(self._icon)
        self._state_store.register_listener(self._handle_state_change)

    def run(self) -> None:
        self._logger.info("Starting system tray loop.")
        self._icon.run(self._setup_tray)

    def _setup_tray(self, icon: pystray.Icon) -> None:
        self._logger.info("System tray icon is ready.")
        self._state_store.mark_ready("Background service is running.")

        if self._on_ready is not None:
            self._on_ready()

        if self._config.tray.startup_notification:
            snapshot = self._state_store.snapshot()
            self._notifier.info(
                self._config.app_name,
                f"Tray application started. Status is {snapshot.state.value}.",
            )

    def _show_status(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        del icon, item
        snapshot = self._state_store.snapshot()
        status_text = snapshot.to_display_text()

        if self._last_transcript_preview:
            status_text = f"{status_text} | Last text: {self._last_transcript_preview}"

        self._logger.info("Status requested: %s", status_text)
        self._notifier.info(self._config.app_name, status_text)

    def _open_history_file(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        del icon, item
        history_file = self._config.paths.history_file

        if not history_file.exists():
            self._notifier.error(self._config.app_name, "History file is missing.")
            self._logger.error("History file does not exist: %s", history_file)
            return

        self._logger.info("Opening history file: %s", history_file)

        try:
            os.startfile(str(history_file))
        except OSError:
            self._logger.exception("Unable to open history file: %s", history_file)
            self._notifier.error(self._config.app_name, "Unable to open history file.")

    def _exit_app(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        del item
        self._logger.info("Exit requested from tray menu.")
        self._state_store.shutdown("Application is shutting down.")
        icon.stop()

        if self._on_exit is not None:
            self._on_exit()

    def _handle_state_change(self, snapshot: StateSnapshot) -> None:
        self._icon.title = f"{self._config.tray.tooltip} - {snapshot.state.value}"

    def set_last_transcript_preview(self, text: str | None) -> None:
        if text is None:
            self._last_transcript_preview = None
            return

        normalized = " ".join(text.split()).strip()
        self._last_transcript_preview = normalized[:80]

    @staticmethod
    def _build_icon_image() -> Image.Image:
        canvas = Image.new("RGBA", (64, 64), (24, 28, 38, 255))
        draw = ImageDraw.Draw(canvas)

        draw.rounded_rectangle((18, 10, 46, 40), radius=14, fill=(69, 159, 255, 255))
        draw.rectangle((26, 34, 38, 48), fill=(232, 240, 255, 255))
        draw.rounded_rectangle((18, 46, 46, 52), radius=3, fill=(232, 240, 255, 255))
        draw.arc((12, 14, 52, 54), start=200, end=340, fill=(232, 240, 255, 255), width=4)

        return canvas
