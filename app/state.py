from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from threading import RLock
from typing import Callable


class AppState(Enum):
    IDLE = "IDLE"
    RECORDING = "RECORDING"
    TRANSCRIBING = "TRANSCRIBING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    state: AppState
    detail: str
    updated_at: datetime
    last_error: str | None

    def to_display_text(self) -> str:
        base_text = f"State: {self.state.value}"
        if self.detail:
            base_text = f"{base_text} | {self.detail}"
        if self.last_error:
            base_text = f"{base_text} | Error: {self.last_error}"
        return base_text


class StateStore:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._lock = RLock()
        self._logger = logger or logging.getLogger(__name__)
        self._state = AppState.IDLE
        self._detail = "Background service is ready."
        self._last_error: str | None = None
        self._updated_at = datetime.now()
        self._listeners: list[Callable[[StateSnapshot], None]] = []

    def register_listener(self, listener: Callable[[StateSnapshot], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def mark_ready(self, detail: str) -> bool:
        return self._transition(
            target_state=AppState.IDLE,
            detail=detail,
            allowed_from={AppState.IDLE, AppState.ERROR},
        )

    def start_recording(self, detail: str) -> bool:
        return self._transition(
            target_state=AppState.RECORDING,
            detail=detail,
            allowed_from={AppState.IDLE, AppState.TRANSCRIBING},
        )

    def finish_recording(self, detail: str) -> bool:
        return self._transition(
            target_state=AppState.IDLE,
            detail=detail,
            allowed_from={AppState.RECORDING},
        )

    def start_transcribing(self, detail: str) -> bool:
        return self._transition(
            target_state=AppState.TRANSCRIBING,
            detail=detail,
            allowed_from={AppState.RECORDING},
        )

    def finish_transcribing(self, detail: str) -> bool:
        return self._transition(
            target_state=AppState.IDLE,
            detail=detail,
            allowed_from={AppState.TRANSCRIBING},
        )

    def shutdown(self, detail: str) -> bool:
        return self._transition(
            target_state=AppState.IDLE,
            detail=detail,
            allowed_from={AppState.IDLE, AppState.RECORDING, AppState.TRANSCRIBING, AppState.ERROR},
        )

    def set_error(self, detail: str, error: str | None = None) -> bool:
        return self._transition(
            target_state=AppState.ERROR,
            detail=detail,
            error=error,
            allowed_from={AppState.IDLE, AppState.RECORDING, AppState.TRANSCRIBING, AppState.ERROR},
        )

    def set_idle(self, detail: str) -> bool:
        return self.mark_ready(detail)

    def stop_recording(self, detail: str) -> bool:
        return self.finish_recording(detail)

    def _transition(
        self,
        target_state: AppState,
        detail: str,
        error: str | None = None,
        allowed_from: set[AppState] | None = None,
    ) -> bool:
        with self._lock:
            current_state = self._state

            if allowed_from is not None and current_state not in allowed_from:
                self._logger.warning(
                    "Invalid state transition requested: %s -> %s | detail=%s",
                    current_state.value,
                    target_state.value,
                    detail,
                )
                return False

            self._state = target_state
            self._detail = detail
            self._last_error = error if target_state is AppState.ERROR else None
            self._updated_at = datetime.now()
            snapshot = self.snapshot()
            listeners = list(self._listeners)

        self._logger.info(
            "State transition applied: %s -> %s | detail=%s",
            current_state.value,
            target_state.value,
            detail,
        )

        for listener in listeners:
            try:
                listener(snapshot)
            except Exception:
                self._logger.exception("State listener failed.")

        return True

    def snapshot(self) -> StateSnapshot:
        with self._lock:
            return StateSnapshot(
                state=self._state,
                detail=self._detail,
                updated_at=self._updated_at,
                last_error=self._last_error,
            )
