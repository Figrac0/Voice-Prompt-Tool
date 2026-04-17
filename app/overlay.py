from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QPoint, Qt, QTimer, Signal, QObject
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from app.state import AppState, StateSnapshot, StateStore


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


class _Signals(QObject):
    state_changed = Signal(object)  # StateSnapshot
    text_updated = Signal(str)


# Dot colours per state
_STATE_COLORS = {
    AppState.IDLE:        "#459FFF",   # blue
    AppState.RECORDING:   "#2BFF59",   # green
    AppState.TRANSCRIBING:"#FF9F0A",   # orange
    AppState.ERROR:       "#FF453A",   # red
}

_STATE_LABELS = {
    AppState.IDLE:        "Voice Prompt",
    AppState.RECORDING:   "Запись...",
    AppState.TRANSCRIBING:"Обработка...",
    AppState.ERROR:       "Ошибка",
}


class RecordingOverlay(QWidget):
    """Always-visible draggable pill indicator.

    Idle = blue dot.  Recording = pulsing green.  Transcribing = pulsing orange.
    Left-click opens the history window.  Drag to reposition.
    """

    _W = 170
    _H = 38
    _R = 19.0   # full pill radius

    def __init__(
        self,
        config: OverlayConfig,
        state_store: StateStore,
        logger: logging.Logger,
        on_click: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._config = config
        self._logger = logger
        self._on_click = on_click
        self._state = AppState.IDLE
        self._anim_phase = 0

        # Drag state
        self._drag_origin: QPoint | None = None
        self._drag_moved = False

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(self._W, self._H)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        # Default position: bottom-right corner
        screen = QApplication.primaryScreen().geometry()
        m = config.margin
        self.move(screen.width() - self._W - m, screen.height() - self._H - m - 48)

        # Thread-safe signal bridge
        self._signals = _Signals(self)
        self._signals.state_changed.connect(self._handle_state)
        self._signals.text_updated.connect(self._handle_text)
        state_store.register_listener(
            lambda snap: self._signals.state_changed.emit(snap)
        )

        # Pulse animation (500 ms tick — only when active)
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self._config.enabled:
            self._logger.info("Overlay disabled by config.")
            return
        self.show()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def update_live_text(self, text: str) -> None:
        self._signals.text_updated.emit(text)

    # ── Qt slots ───────────────────────────────────────────────────────────────

    def _handle_state(self, snap: StateSnapshot) -> None:
        self._state = snap.state
        if snap.state in (AppState.RECORDING, AppState.TRANSCRIBING):
            self._timer.start()
        else:
            self._timer.stop()
            self._anim_phase = 0
        self.update()

    def _handle_text(self, _text: str) -> None:
        self.update()

    def _tick(self) -> None:
        self._anim_phase ^= 1
        self.update()

    # ── Mouse events (drag + click) ────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_moved = False
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_origin is not None:
            new_pos = event.globalPosition().toPoint() - self._drag_origin
            delta = (new_pos - self.pos()).manhattanLength()
            if delta > 4:
                self._drag_moved = True
            self.move(new_pos)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._drag_moved and self._on_click is not None:
                self._on_click()
            self._drag_origin = None
            self._drag_moved = False
        event.accept()

    # ── Painting ───────────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h, r = self._W, self._H, self._R
        state = self._state

        # ── Background pill ───────────────────────────────────────────────────
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, r, r)

        if state == AppState.IDLE:
            bg = QColor("#1C1C1E")
            bg.setAlphaF(0.82)
        else:
            bg = QColor("#1A1A1A")
            bg.setAlphaF(0.95)
        p.fillPath(path, QBrush(bg))

        # ── Border ────────────────────────────────────────────────────────────
        dot_hex = _STATE_COLORS[state]
        if state == AppState.IDLE:
            border_color = QColor(255, 255, 255, 22)
        else:
            border_color = QColor(dot_hex)
            border_color.setAlphaF(0.35)

        p.setPen(QPen(border_color, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(0.5, 0.5, w - 1, h - 1, r, r)

        # ── Dot ───────────────────────────────────────────────────────────────
        if state in (AppState.RECORDING, AppState.TRANSCRIBING):
            dot_r = 6 if self._anim_phase == 0 else 5
        else:
            dot_r = 5

        dot_cx = int(r)
        dot_cy = h // 2

        # Glow
        glow = QColor(dot_hex)
        glow.setAlphaF(0.22 if state == AppState.IDLE else 0.32)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPoint(dot_cx, dot_cy), dot_r + 5, dot_r + 5)

        # Fill
        p.setBrush(QBrush(QColor(dot_hex)))
        p.drawEllipse(QPoint(dot_cx, dot_cy), dot_r, dot_r)

        # ── Label ─────────────────────────────────────────────────────────────
        label = _STATE_LABELS[state]
        font = QFont("Segoe UI", 10, QFont.Weight.Medium if state == AppState.IDLE else QFont.Weight.SemiBold)
        p.setFont(font)

        text_color = QColor("#8E8E93") if state == AppState.IDLE else QColor("#F2F2F7")
        p.setPen(text_color)

        fm = QFontMetrics(font)
        text_x = dot_cx + dot_r + 10
        text_y = (h + fm.ascent() - fm.descent()) // 2
        p.drawText(text_x, text_y, label)

        p.end()
