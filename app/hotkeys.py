from __future__ import annotations

import logging
from threading import RLock
from typing import Callable

from pynput import keyboard

from app.config import HotkeyConfig
from app.notifications import NotificationManager
from app.state import StateStore


class HotkeyRegistrationError(RuntimeError):
    """Raised when the global hotkey listener cannot be started."""


class GlobalHotkeyManager:
    def __init__(
        self,
        config: HotkeyConfig,
        logger: logging.Logger,
        state_store: StateStore,
        notifier: NotificationManager,
        app_name: str,
        on_recording_start: Callable[[], bool] | None = None,
        on_recording_stop: Callable[[], bool] | None = None,
    ) -> None:
        self._config = config
        self._logger = logger
        self._state_store = state_store
        self._notifier = notifier
        self._app_name = app_name
        self._on_recording_start = on_recording_start
        self._on_recording_stop = on_recording_stop
        self._listener: keyboard.Listener | None = None
        self._lock = RLock()
        self._pressed_keys: set[str] = set()
        self._combo_active = False

    def start(self) -> None:
        with self._lock:
            if self._listener is not None:
                return

            try:
                listener = keyboard.Listener(
                    on_press=self._handle_press,
                    on_release=self._handle_release,
                )
                listener.start()
                listener.wait()
            except Exception as exc:
                raise HotkeyRegistrationError(
                    f"Unable to register global hotkey listener for '{self._config.combination}'."
                ) from exc

            self._listener = listener

        self._logger.info("Hotkey registered: %s", self._config.combination)

    def stop(self) -> None:
        with self._lock:
            listener = self._listener
            self._listener = None
            self._pressed_keys.clear()
            self._combo_active = False

        if listener is not None:
            listener.stop()
            self._logger.info("Hotkey listener stopped.")

    def _handle_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        key_name = self._normalize_pressed_key(key)
        if key_name is None:
            return

        with self._lock:
            self._pressed_keys.add(key_name)

            if self._combo_active or not self._is_hotkey_active():
                return

            self._combo_active = True

        self._logger.info("Hotkey pressed: %s", self._config.combination)

        if self._on_recording_start is not None:
            self._on_recording_start()
            return

        if self._state_store.start_recording("Hotkey is held. Recording session is armed."):
            self._notifier.info(self._app_name, "Recording started")

    def _handle_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        key_name = self._normalize_pressed_key(key)
        if key_name is None:
            return

        should_emit_release = False

        with self._lock:
            self._pressed_keys.discard(key_name)

            if self._combo_active and not self._is_hotkey_active():
                self._combo_active = False
                should_emit_release = True

        if not should_emit_release:
            return

        self._logger.info("Hotkey released: %s", self._config.combination)

        if self._on_recording_stop is not None:
            self._on_recording_stop()
            return

        if self._state_store.stop_recording("Hotkey released. Recording session stopped."):
            self._notifier.info(self._app_name, "Recording stopped")

    def _is_hotkey_active(self) -> bool:
        active_tokens = self._build_active_tokens()
        return set(self._config.tokens).issubset(active_tokens)

    def _build_active_tokens(self) -> set[str]:
        active_tokens = set(self._pressed_keys)

        if {"ctrl", "left_ctrl", "right_ctrl"} & active_tokens:
            active_tokens.add("ctrl")
        if {"alt", "left_alt", "right_alt"} & active_tokens:
            active_tokens.add("alt")
        if {"shift", "left_shift", "right_shift"} & active_tokens:
            active_tokens.add("shift")
        if {"win", "left_win", "right_win"} & active_tokens:
            active_tokens.add("win")

        return active_tokens

    @staticmethod
    def _normalize_pressed_key(key: keyboard.Key | keyboard.KeyCode) -> str | None:
        if isinstance(key, keyboard.KeyCode):
            if key.char is None:
                return None
            return key.char.lower()

        key_map = {
            keyboard.Key.ctrl: "ctrl",
            keyboard.Key.ctrl_l: "left_ctrl",
            keyboard.Key.ctrl_r: "right_ctrl",
            keyboard.Key.alt: "alt",
            keyboard.Key.alt_l: "left_alt",
            keyboard.Key.alt_r: "right_alt",
            keyboard.Key.shift: "shift",
            keyboard.Key.shift_l: "left_shift",
            keyboard.Key.shift_r: "right_shift",
            keyboard.Key.cmd: "win",
            keyboard.Key.cmd_l: "left_win",
            keyboard.Key.cmd_r: "right_win",
        }

        return key_map.get(key)
