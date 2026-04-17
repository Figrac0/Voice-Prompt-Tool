from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass

from PySide6.QtCore import Qt, QPoint, QTimer, Signal, QObject
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
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


class RecordingOverlay(QWidget):
    """Tiny pill indicator in the bottom-right corner.

    Green dot = recording. Orange dot = transcribing. Hidden when idle.
    """

    _W = 130
    _H = 30
    _R = 15.0  # corner radius (full pill)

    def __init__(
        self,
        config: OverlayConfig,
        state_store: StateStore,
        logger: logging.Logger,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._config = config
        self._logger = logger
        self._state = AppState.IDLE
        self._anim_phase = 0

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(self._W, self._H)

        screen = QApplication.primaryScreen().geometry()
        m = config.margin
        self.move(screen.width() - self._W - m, screen.height() - self._H - m - 40)

        self._signals = _Signals(self)
        self._signals.state_changed.connect(self._handle_state)
        self._signals.text_updated.connect(self._handle_text)
        state_store.register_listener(
            lambda snap: self._signals.state_changed.emit(snap)
        )

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self._config.enabled:
            self._logger.info("Overlay disabled by config.")

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def update_live_text(self, text: str) -> None:
        self._signals.text_updated.emit(text)

    # ── Qt slots ───────────────────────────────────────────────────────────────

    def _handle_state(self, snap: StateSnapshot) -> None:
        self._state = snap.state
        if snap.state in (AppState.IDLE, AppState.ERROR):
            self._timer.stop()
            self.hide()
        else:
            self._timer.start()
            self._apply_click_through()
            self.show()
            self.update()

    def _handle_text(self, text: str) -> None:
        self.update()

    def _tick(self) -> None:
        self._anim_phase ^= 1
        self.update()

    # ── Painting ───────────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # noqa: N802
        if self._state is AppState.IDLE:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h, r = self._W, self._H, self._R

        # Pill background
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, r, r)
        bg = QColor("#1A1A1A")
        bg.setAlphaF(0.90)
        p.fillPath(path, QBrush(bg))

        # Subtle border
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, w - 2, h - 2, r - 1, r - 1)

        # Dot color + label
        if self._state is AppState.RECORDING:
            dot_color = self._config.recording_color
            label = "Запись"
        else:
            dot_color = self._config.transcribing_color
            label = "Обработка"

        # Pulsing dot
        dot_r = 5 if self._anim_phase == 0 else 4
        dot_cx = 18
        dot_cy = h // 2

        glow = QColor(dot_color)
        glow.setAlphaF(0.30)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPoint(dot_cx, dot_cy), dot_r + 4, dot_r + 4)

        p.setBrush(QBrush(QColor(dot_color)))
        p.drawEllipse(QPoint(dot_cx, dot_cy), dot_r, dot_r)

        # Label text
        from PySide6.QtGui import QFont, QFontMetrics
        font = QFont("Segoe UI", 10, QFont.Weight.Medium)
        p.setFont(font)
        p.setPen(QColor("#EEEEEE"))
        fm = QFontMetrics(font)
        text_x = dot_cx + dot_r + 8
        text_y = (h + fm.ascent() - fm.descent()) // 2
        p.drawText(text_x, text_y, label)

        p.end()

    # ── Windows click-through ─────────────────────────────────────────────────

    def _apply_click_through(self) -> None:
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            )
        except Exception:
            pass
