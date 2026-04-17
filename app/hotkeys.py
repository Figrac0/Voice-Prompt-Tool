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
        # Require all combo keys to be fully released before next activation.
        # Prevents stale key state (missed release events) from triggering recording
        # when only a single modifier is pressed.
        self._all_combo_keys_released = True

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
            self._all_combo_keys_released = True
        if listener is not None:
            listener.stop()
            self._logger.info("Hotkey listener stopped.")

    # ── Key event handlers ─────────────────────────────────────────────────────

    def _handle_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        key_name = self._normalize_key(key)
        if key_name is None:
            return

        fire_start = False
        with self._lock:
            self._pressed_keys.add(key_name)

            if self._combo_active:
                return

            # The combo may only re-arm after ALL required keys were released.
            if not self._all_combo_keys_released:
                return

            if not self._is_combo_complete():
                return

            # The key that just completed the combo must itself be one of the
            # required tokens. This blocks spurious triggers from unrelated keys
            # pressed while combo keys happen to be held.
            if key_name not in set(self._config.tokens):
                return

            self._combo_active = True
            self._all_combo_keys_released = False
            fire_start = True

        if fire_start:
            self._logger.info("Hotkey activated: %s", self._config.combination)
            if self._on_recording_start is not None:
                self._on_recording_start()
            else:
                if self._state_store.start_recording("Hotkey held."):
                    self._notifier.info(self._app_name, "Recording started")

    def _handle_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        key_name = self._normalize_key(key)
        if key_name is None:
            return

        fire_stop = False
        with self._lock:
            self._pressed_keys.discard(key_name)

            if self._combo_active and not self._is_combo_complete():
                self._combo_active = False
                fire_stop = True

            # Mark all-released when no required key is currently pressed.
            if not (set(self._config.tokens) & self._build_active_tokens()):
                self._all_combo_keys_released = True

        if fire_stop:
            self._logger.info("Hotkey released: %s", self._config.combination)
            if self._on_recording_stop is not None:
                self._on_recording_stop()
            else:
                if self._state_store.stop_recording("Hotkey released."):
                    self._notifier.info(self._app_name, "Recording stopped")

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _is_combo_complete(self) -> bool:
        return set(self._config.tokens).issubset(self._build_active_tokens())

    def _build_active_tokens(self) -> set[str]:
        """Expand pressed keys with canonical group aliases (ctrl, alt, shift, win)."""
        active = set(self._pressed_keys)
        if {"ctrl", "left_ctrl", "right_ctrl"} & active:
            active.add("ctrl")
        if {"alt", "left_alt", "right_alt"} & active:
            active.add("alt")
        if {"shift", "left_shift", "right_shift"} & active:
            active.add("shift")
        if {"win", "left_win", "right_win"} & active:
            active.add("win")
        return active

    @staticmethod
    def _normalize_key(key: keyboard.Key | keyboard.KeyCode) -> str | None:
        """Return a canonical token name for the given key, or None to ignore."""
        if isinstance(key, keyboard.KeyCode):
            # Ignore regular character keys — only modifier keys are tracked.
            return None

        return {
            keyboard.Key.ctrl:    "ctrl",
            keyboard.Key.ctrl_l:  "ctrl",
            keyboard.Key.ctrl_r:  "ctrl",
            keyboard.Key.alt:     "alt",
            keyboard.Key.alt_l:   "alt",
            keyboard.Key.alt_r:   "alt",
            keyboard.Key.shift:   "shift",
            keyboard.Key.shift_l: "shift",
            keyboard.Key.shift_r: "shift",
            keyboard.Key.cmd:     "win",
            keyboard.Key.cmd_l:   "win",
            keyboard.Key.cmd_r:   "win",
        }.get(key)
