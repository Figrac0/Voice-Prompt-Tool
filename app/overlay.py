from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass

from PySide6.QtCore import Qt, QPoint, QTimer, Signal, QObject
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
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
    """Frameless pill-shaped floating indicator at the bottom-centre of the screen.

    Bridges the thread-safe StateStore to Qt via a QObject signal proxy so that
    worker-thread state transitions safely marshal to the main-thread paint loop.
    """

    _PILL_W = 360
    _PILL_H = 52
    _BOTTOM_MARGIN = 64
    _SHADOW = 3           # shadow offset in pixels
    _FONT_FAMILY = "Segoe UI"
    _FONT_SIZE = 12
    _MAX_CHARS = 42

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
        self._live_text = ""
        self._anim_phase = 0

        # Widget attributes
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(self._PILL_W + self._SHADOW, self._PILL_H + self._SHADOW)

        # Position: bottom-centre of primary screen
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self._PILL_W) // 2,
            screen.height() - self._PILL_H - self._BOTTOM_MARGIN,
        )

        # Thread-safe signal bridge
        self._signals = _Signals(self)
        self._signals.state_changed.connect(self._handle_state)
        self._signals.text_updated.connect(self._handle_text)
        state_store.register_listener(
            lambda snap: self._signals.state_changed.emit(snap)
        )

        # Pulsing dot animation (600 ms tick)
        self._timer = QTimer(self)
        self._timer.setInterval(600)
        self._timer.timeout.connect(self._tick)

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self._config.enabled:
            self._logger.info("Overlay disabled by config.")

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def update_live_text(self, text: str) -> None:
        """Called from live-preview thread; marshalled to main thread via signal."""
        self._signals.text_updated.emit(text)

    # ── Qt slots (always main thread) ─────────────────────────────────────────

    def _handle_state(self, snap: StateSnapshot) -> None:
        self._state = snap.state
        if snap.state is AppState.IDLE:
            self._live_text = ""
            self._timer.stop()
            self.hide()
        else:
            if snap.state is AppState.TRANSCRIBING:
                self._live_text = ""
            self._timer.start()
            self._apply_click_through()
            self.show()
            self.update()

    def _handle_text(self, text: str) -> None:
        if self._state is AppState.RECORDING:
            self._live_text = text
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

        w = self._PILL_W
        h = self._PILL_H
        r = h / 2.0
        s = self._SHADOW

        # Drop shadow (blurred approximation via offset semi-transparent pill)
        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(s, s, w, h, r, r)
        p.fillPath(shadow_path, QColor(0, 0, 0, 55))

        # Pill body
        pill_path = QPainterPath()
        pill_path.addRoundedRect(0, 0, w, h, r, r)
        bg = QColor("#1C1C1E")
        bg.setAlphaF(0.94)
        p.fillPath(pill_path, QBrush(bg))

        # Subtle inner border
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, w - 2, h - 2, r - 1, r - 1)

        # Indicator dot
        if self._state is AppState.RECORDING:
            dot_hex = self._config.recording_color
        else:
            dot_hex = "#FF9F0A"  # orange for transcribing regardless of config

        dot_r = 9 if self._anim_phase == 0 else 7
        dot_cx = int(r) + 14
        dot_cy = h // 2

        # Dot glow (soft halo)
        glow = QColor(dot_hex)
        glow.setAlphaF(0.25)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPoint(dot_cx, dot_cy), dot_r + 5, dot_r + 5)

        # Dot fill
        p.setBrush(QBrush(QColor(dot_hex)))
        p.drawEllipse(QPoint(dot_cx, dot_cy), dot_r, dot_r)

        # Label
        if self._state is AppState.RECORDING:
            label = self._live_text.strip() or "Запись..."
        elif self._state is AppState.TRANSCRIBING:
            label = "Обработка..."
        else:
            label = "Ошибка"

        if len(label) > self._MAX_CHARS:
            label = "…" + label[-(self._MAX_CHARS - 1):]

        font = QFont(self._FONT_FAMILY, self._FONT_SIZE, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QColor("#FFFFFF"))

        fm = QFontMetrics(font)
        text_x = dot_cx + 9 + 12
        text_y = (h + fm.ascent() - fm.descent()) // 2
        p.drawText(text_x, text_y, label)

        p.end()

    # ── Windows click-through ─────────────────────────────────────────────────

    def _apply_click_through(self) -> None:
        """Make the overlay transparent to mouse events via Windows API."""
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
