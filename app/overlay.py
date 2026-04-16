from __future__ import annotations

import logging
import queue
from dataclasses import dataclass
from threading import Event, Thread

from app.state import AppState, StateSnapshot, StateStore

try:
    import tkinter as tk
except Exception:  # pragma: no cover - tkinter import may fail in minimal env
    tk = None  # type: ignore[assignment]


@dataclass(frozen=True, slots=True)
class OverlayConfig:
    enabled: bool
    size: int
    margin: int
    idle_alpha: float
    recording_alpha: float
    transcribing_alpha: float
    idle_color: str
    recording_color: str
    transcribing_color: str


class RecordingOverlay:
    """Small always-on-top indicator synced with recorder state."""

    def __init__(self, config: OverlayConfig, state_store: StateStore, logger: logging.Logger) -> None:
        self._config = config
        self._state_store = state_store
        self._logger = logger
        self._queue: queue.Queue[AppState | None] = queue.Queue()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._running = False

    def start(self) -> None:
        if not self._config.enabled:
            self._logger.info("Recording overlay is disabled by config.")
            return

        if tk is None:
            self._logger.warning("Recording overlay unavailable: tkinter is missing.")
            return

        if self._running:
            return

        self._running = True
        self._state_store.register_listener(self._on_state_change)
        self._thread = Thread(target=self._run_ui, daemon=True, name="voice-prompt-overlay")
        self._thread.start()
        self._logger.info("Recording overlay started.")

    def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        self._stop_event.set()
        self._queue.put(None)
        self._logger.info("Recording overlay stop requested.")

    def _on_state_change(self, snapshot: StateSnapshot) -> None:
        if not self._running:
            return
        self._queue.put(snapshot.state)

    def _run_ui(self) -> None:
        assert tk is not None
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-toolwindow", True)
        root.configure(bg="black")

        size = max(28, self._config.size)
        margin = max(8, self._config.margin)
        x = max(0, root.winfo_screenwidth() - size - margin)
        y = max(0, margin)
        root.geometry(f"{size}x{size}+{x}+{y}")

        canvas = tk.Canvas(root, width=size, height=size, highlightthickness=0, bd=0, bg="#121212")
        canvas.pack(fill="both", expand=True)
        canvas.create_oval(6, 6, size - 6, size - 6, fill=self._config.idle_color, outline="")

        def render(state: AppState) -> None:
            canvas.delete("all")

            color = self._config.idle_color
            alpha = self._config.idle_alpha
            if state is AppState.RECORDING:
                color = self._config.recording_color
                alpha = self._config.recording_alpha
            elif state is AppState.TRANSCRIBING:
                color = self._config.transcribing_color
                alpha = self._config.transcribing_alpha

            root.attributes("-alpha", max(0.2, min(1.0, alpha)))
            canvas.create_rectangle(0, 0, size, size, fill="#121212", outline="")
            canvas.create_oval(6, 6, size - 6, size - 6, fill=color, outline="")

        def pump() -> None:
            if self._stop_event.is_set():
                root.destroy()
                return

            try:
                while True:
                    state = self._queue.get_nowait()
                    if state is None:
                        root.destroy()
                        return
                    render(state)
            except queue.Empty:
                pass

            root.after(40, pump)

        render(self._state_store.snapshot().state)
        root.after(40, pump)
        try:
            root.mainloop()
        except Exception:
            self._logger.exception("Recording overlay UI loop crashed.")
