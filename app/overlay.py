from __future__ import annotations

import logging
from collections import deque
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
    state_changed = Signal(object)
    level_received = Signal(float)


_IDLE_DOT   = "#459FFF"   # blue
_REC_COLOR  = "#2BFF59"   # green
_ERR_COLOR  = "#FF453A"   # red

_WAVEFORM_BARS  = 14      # number of bars in waveform
_WAVEFORM_W     = 56      # total waveform section width (px)
_BAR_W          = 3       # each bar width
_BAR_MAX_H      = 20      # max bar height (px)
_BAR_MIN_H      = 2       # min bar height


class RecordingOverlay(QWidget):
    """Always-visible draggable pill.

    Idle  → blue dot + 'Voice Prompt'
    Recording → animated audio waveform + 'Запись...'
    Transcribing / Error → treated same as Idle (instant, no separate phase)

    Click  → open history window.
    Drag   → reposition anywhere on screen.
    """

    _W = 178
    _H = 40
    _R = 20.0

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
        self._config   = config
        self._logger   = logger
        self._on_click = on_click
        self._state    = AppState.IDLE

        # Waveform state
        self._levels: deque[float] = deque([0.0] * _WAVEFORM_BARS, maxlen=_WAVEFORM_BARS)
        self._anim_phase = 0

        # Drag state
        self._drag_origin: QPoint | None = None
        self._drag_moved = False

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(self._W, self._H)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        # Default position: bottom-right
        screen = QApplication.primaryScreen().geometry()
        m = config.margin
        self.move(screen.width() - self._W - m, screen.height() - self._H - m - 50)

        # Signal bridge
        self._signals = _Signals(self)
        self._signals.state_changed.connect(self._handle_state)
        self._signals.level_received.connect(self._handle_level)
        state_store.register_listener(
            lambda snap: self._signals.state_changed.emit(snap)
        )

        # Repaint timer during recording (for idle animation of bars)
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self._config.enabled:
            return
        self.show()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def push_audio_level(self, level: float) -> None:
        """Thread-safe: called from audio recorder callback with normalised RMS."""
        self._signals.level_received.emit(level)

    # kept for API compat
    def update_live_text(self, _text: str) -> None:
        pass

    # ── Qt slots ───────────────────────────────────────────────────────────────

    def _handle_state(self, snap: StateSnapshot) -> None:
        prev = self._state
        self._state = snap.state
        if snap.state == AppState.RECORDING:
            self._timer.start()
        else:
            self._timer.stop()
            # Reset bars smoothly
            self._levels = deque([0.0] * _WAVEFORM_BARS, maxlen=_WAVEFORM_BARS)
            self._anim_phase = 0
        if snap.state != prev:
            self.update()

    def _handle_level(self, level: float) -> None:
        self._levels.append(level)
        self.update()

    def _tick(self) -> None:
        # When no new audio comes in, slowly decay bars
        self._anim_phase = (self._anim_phase + 1) % 8
        decayed = deque((v * 0.88 for v in self._levels), maxlen=_WAVEFORM_BARS)
        self._levels = decayed
        self.update()

    # ── Mouse events ───────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_moved = False
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_origin is not None:
            new_pos = event.globalPosition().toPoint() - self._drag_origin
            if (new_pos - self.pos()).manhattanLength() > 4:
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
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            w, h, r = self._W, self._H, self._R
            recording = self._state == AppState.RECORDING

            # ── Background ────────────────────────────────────────────────────────
            path = QPainterPath()
            path.addRoundedRect(0, 0, w, h, r, r)
            bg = QColor("#1C1C1E")
            bg.setAlphaF(0.88 if not recording else 0.95)
            p.fillPath(path, QBrush(bg))

            # ── Border ────────────────────────────────────────────────────────────
            if recording:
                border = QColor(_REC_COLOR)
                border.setAlphaF(0.45)
            else:
                border = QColor(255, 255, 255, 20)
            p.setPen(QPen(border, 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(0.5, 0.5, w - 1, h - 1, r, r)

            left_pad = int(r)  # content starts after pill curve

            if recording:
                self._paint_waveform(p, left_pad, h)
            else:
                self._paint_idle_dot(p, left_pad, h)
        finally:
            p.end()

    def _paint_idle_dot(self, p: QPainter, left_pad: int, h: int) -> None:
        transcribing = self._state == AppState.TRANSCRIBING

        dot_color = "#F59E0B" if transcribing else _IDLE_DOT
        label     = "Обработка..." if transcribing else "Voice Prompt"
        label_color = "#C8922A" if transcribing else "#8E8E93"

        dot_r  = 5
        dot_cx = left_pad
        dot_cy = h // 2

        # Glow
        glow = QColor(dot_color)
        glow.setAlphaF(0.22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPoint(dot_cx, dot_cy), dot_r + 5, dot_r + 5)

        # Dot
        p.setBrush(QBrush(QColor(dot_color)))
        p.drawEllipse(QPoint(dot_cx, dot_cy), dot_r, dot_r)

        # Label
        font = QFont("Segoe UI", 10, QFont.Weight.Medium)
        p.setFont(font)
        p.setPen(QColor(label_color))
        fm = QFontMetrics(font)
        tx = dot_cx + dot_r + 9
        ty = (h + fm.ascent() - fm.descent()) // 2
        p.drawText(tx, ty, label)

    def _paint_waveform(self, p: QPainter, left_pad: int, h: int) -> None:
        levels = list(self._levels)
        n      = len(levels)
        cx_start = left_pad + 2

        p.setPen(Qt.PenStyle.NoPen)

        for i, lvl in enumerate(levels):
            bar_h  = max(_BAR_MIN_H, int(_BAR_MAX_H * (lvl ** 0.25)))
            bar_x  = cx_start + i * (_BAR_W + 2)
            bar_y  = (h - bar_h) // 2

            # Colour: brighter green for louder bars
            alpha  = 0.45 + 0.55 * lvl
            color  = QColor(_REC_COLOR)
            color.setAlphaF(alpha)

            bar_path = QPainterPath()
            bar_path.addRoundedRect(bar_x, bar_y, _BAR_W, bar_h, 1.5, 1.5)
            p.fillPath(bar_path, QBrush(color))

        # Label after waveform
        label_x = cx_start + n * (_BAR_W + 2) + 6
        font    = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor("#E8E8E8"))
        fm  = QFontMetrics(font)
        ty  = (h + fm.ascent() - fm.descent()) // 2
        p.drawText(label_x, ty, "Запись...")
