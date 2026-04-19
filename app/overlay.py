from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPoint, Qt, QTimer, Signal, QObject
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

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
    state_changed   = Signal(object)
    level_received  = Signal(float)
    refresh_history = Signal()


_IDLE_DOT  = "#459FFF"
_REC_COLOR = "#2BFF59"

_WAVEFORM_BARS = 14
_BAR_W         = 3
_BAR_MAX_H     = 20
_BAR_MIN_H     = 2

_W        = 260   # widget width (collapsed and expanded)
_PILL_H   = 40    # pill section height
_R        = 20.0  # corner radius
_ENTRY_H  = 54    # height of each history row
_MAX_ENT  = 5     # max history entries shown
_FOOTER_H = 44    # button row height
_ANIM_STEPS = 14
_ANIM_INTERVAL_MS = 16  # ~60 fps


def _fmt_ts(iso: str) -> str:
    try:
        dt   = datetime.fromisoformat(iso[:19])
        now  = datetime.now()
        diff = (now.date() - dt.date()).days
        t    = dt.strftime("%H:%M")
        if diff == 0:
            return f"сегодня, {t}"
        if diff == 1:
            return f"вчера, {t}"
        months = ["янв", "фев", "мар", "апр", "май", "июн",
                  "июл", "авг", "сен", "окт", "ноя", "дек"]
        return f"{dt.day} {months[dt.month - 1]}, {t}"
    except Exception:
        return iso[:16].replace("T", " ")


class RecordingOverlay(QWidget):
    """Draggable pill — click to expand history panel below it.

    Idle       → blue dot + 'Voice Prompt'
    Recording  → animated waveform + 'Запись...'
    Expanded   → pill stays at top, last 5 entries + Collapse / Exit buttons below
    """

    def __init__(
        self,
        config: OverlayConfig,
        state_store: StateStore,
        history_file: Path,
        logger: logging.Logger,
        on_exit: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._config       = config
        self._logger       = logger
        self._history_file = history_file
        self._on_exit      = on_exit
        self._state        = AppState.IDLE
        self._expanded     = False

        self._levels: deque[float] = deque([0.0] * _WAVEFORM_BARS, maxlen=_WAVEFORM_BARS)
        self._anim_phase  = 0
        self._drag_origin: QPoint | None = None
        self._drag_moved  = False

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(_W, _PILL_H)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        screen = QApplication.primaryScreen().geometry()
        self.move(
            screen.width()  - _W - config.margin,
            screen.height() - _PILL_H - config.margin - 50,
        )

        self._sig = _Signals(self)
        self._sig.state_changed.connect(self._handle_state)
        self._sig.level_received.connect(self._handle_level)
        self._sig.refresh_history.connect(self._do_refresh)
        state_store.register_listener(lambda snap: self._sig.state_changed.emit(snap))

        self._rec_timer = QTimer(self)
        self._rec_timer.setInterval(80)
        self._rec_timer.timeout.connect(self._tick)

        self._anim_timer = QTimer(self)

        self._panel = self._build_panel()
        self._panel.move(0, _PILL_H)
        self._panel.hide()

    # ── Panel construction ────────────────────────────────────────────────────

    def _build_panel(self) -> QWidget:
        panel = QWidget(self)
        panel.setFixedWidth(_W)
        panel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        root = QVBoxLayout(panel)
        root.setContentsMargins(0, 6, 0, 0)
        root.setSpacing(0)

        self._entries_host = QWidget(panel)
        self._entries_host.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._entries_vbox = QVBoxLayout(self._entries_host)
        self._entries_vbox.setContentsMargins(0, 0, 0, 0)
        self._entries_vbox.setSpacing(0)
        root.addWidget(self._entries_host)

        footer = QWidget(panel)
        footer.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        footer.setFixedHeight(_FOOTER_H)
        fh = QHBoxLayout(footer)
        fh.setContentsMargins(12, 8, 12, 8)
        fh.setSpacing(8)

        btn_col = QPushButton("Свернуть")
        btn_col.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_col.setStyleSheet(_S_COLLAPSE)
        btn_col.clicked.connect(self._collapse)
        fh.addWidget(btn_col)

        btn_exit = QPushButton("Закрыть")
        btn_exit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_exit.setStyleSheet(_S_EXIT)
        btn_exit.clicked.connect(self._do_exit)
        fh.addWidget(btn_exit)

        root.addWidget(footer)
        return panel

    # ── History ───────────────────────────────────────────────────────────────

    def _load_entries(self) -> list[dict]:
        if not self._history_file.exists():
            return []
        try:
            with self._history_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("entries", []) if isinstance(data, dict) else []
        except Exception:
            return []

    def _do_refresh(self) -> None:
        while self._entries_vbox.count():
            item = self._entries_vbox.takeAt(0)
            if w := item.widget():
                w.deleteLater()

        entries = self._load_entries()[-_MAX_ENT:]
        n = 0

        if not entries:
            lbl = QLabel("Записей пока нет")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFont(QFont("Segoe UI", 10))
            lbl.setFixedHeight(_ENTRY_H)
            lbl.setStyleSheet("color:#3A3A3A; background:transparent;")
            self._entries_vbox.addWidget(lbl)
            n = 1
        else:
            for i, entry in enumerate(reversed(entries)):
                ts   = _fmt_ts(entry.get("timestamp") or entry.get("created_at", ""))
                text = entry.get("cleaned_text") or entry.get("raw_text") or ""
                if not text:
                    continue
                self._entries_vbox.addWidget(_entry_row(ts, text))
                n += 1
                if i < len(entries) - 1:
                    sep = QWidget()
                    sep.setFixedSize(_W, 1)
                    sep.setStyleSheet("background:#1E1E1E;")
                    self._entries_vbox.addWidget(sep)

        entries_h = n * _ENTRY_H + max(0, n - 1)
        self._entries_host.setFixedHeight(entries_h)
        panel_h = 6 + entries_h + _FOOTER_H
        self._panel.setFixedHeight(panel_h)

    def notify_new_entry(self) -> None:
        """Thread-safe: refresh history list if panel is currently open."""
        if self._expanded:
            self._sig.refresh_history.emit()

    # ── Expand / Collapse ─────────────────────────────────────────────────────

    def toggle_expand(self) -> None:
        if self._expanded:
            self._collapse()
        else:
            self._expand()

    def _expand(self) -> None:
        if self._expanded:
            return
        self._expanded = True
        self._do_refresh()
        self._panel.show()
        target = _PILL_H + self._panel.height()
        self._animate(self.height(), target, lambda: self.setFixedSize(_W, target))
        self.update()

    def _collapse(self) -> None:
        if not self._expanded:
            return
        self._expanded = False

        def _done() -> None:
            self._panel.hide()
            self.setFixedSize(_W, _PILL_H)

        self._animate(self.height(), _PILL_H, _done)
        self.update()

    def _animate(self, from_h: int, to_h: int, on_done: Callable[[], None]) -> None:
        # Always stop and disconnect — even if the previous animation already
        # finished, its _tick closure stays connected and would fire again.
        self._anim_timer.stop()
        try:
            self._anim_timer.timeout.disconnect()
        except RuntimeError:
            pass

        if from_h == to_h:
            on_done()
            return

        # Release fixed-size constraints before resizing
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)

        step = [0]

        def _tick() -> None:
            step[0] += 1
            t    = step[0] / _ANIM_STEPS
            ease = 1.0 - (1.0 - t) ** 3    # cubic ease-out
            h    = int(from_h + (to_h - from_h) * ease)
            self.resize(_W, h)
            if step[0] >= _ANIM_STEPS:
                self._anim_timer.stop()
                on_done()

        self._anim_timer.timeout.connect(_tick)
        self._anim_timer.start(_ANIM_INTERVAL_MS)

    def _do_exit(self) -> None:
        self._logger.info("Exit via overlay.")
        if self._on_exit:
            self._on_exit()
        QApplication.quit()

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self._config.enabled:
            return
        self.show()

    def stop(self) -> None:
        self._rec_timer.stop()
        self.hide()

    def push_audio_level(self, level: float) -> None:
        self._sig.level_received.emit(level)

    def update_live_text(self, _text: str) -> None:
        pass

    # ── Qt slots ──────────────────────────────────────────────────────────────

    def _handle_state(self, snap: StateSnapshot) -> None:
        prev = self._state
        self._state = snap.state
        if snap.state == AppState.RECORDING:
            self._rec_timer.start()
        else:
            self._rec_timer.stop()
            self._levels    = deque([0.0] * _WAVEFORM_BARS, maxlen=_WAVEFORM_BARS)
            self._anim_phase = 0
        if snap.state != prev:
            self.update()

    def _handle_level(self, level: float) -> None:
        self._levels.append(level)
        self.update()

    def _tick(self) -> None:
        self._anim_phase = (self._anim_phase + 1) % 8
        self._levels = deque((v * 0.88 for v in self._levels), maxlen=_WAVEFORM_BARS)
        self.update()

    # ── Mouse events ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_moved  = False
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_origin is not None:
            new_pos = event.globalPosition().toPoint() - self._drag_origin
            if (new_pos - self.pos()).manhattanLength() > 10:
                self._drag_moved = True
            if self._drag_moved:
                self.move(new_pos)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._drag_moved and event.position().y() <= _PILL_H:
                self.toggle_expand()
            self._drag_origin = None
            self._drag_moved  = False
        event.accept()

    # ── Window shape ──────────────────────────────────────────────────────────

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._disable_dwm_border()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.update()

    def _disable_dwm_border(self) -> None:
        """Tell DWM to stay out of our window — no border, no rounding, no backdrop."""
        try:
            import ctypes
            hwnd = int(self.winId())

            # No automatic 1-px accent border
            DWMWA_BORDER_COLOR = 34
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_BORDER_COLOR,
                ctypes.byref(ctypes.c_int(0xFFFFFFFE)),  # DWMWA_COLOR_NONE
                ctypes.sizeof(ctypes.c_int),
            )
            # We paint our own corners — stop Windows 11 from rounding them too
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(ctypes.c_int(1)),  # DWMWCP_DONOTROUND
                ctypes.sizeof(ctypes.c_int),
            )
            # Disable non-client rendering (removes DWM-drawn shadow / glow halo)
            DWMWA_NCRENDERING_POLICY = 2
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_NCRENDERING_POLICY,
                ctypes.byref(ctypes.c_int(2)),  # DWMNCRP_DISABLED
                ctypes.sizeof(ctypes.c_int),
            )
        except Exception:
            pass

    # ── Painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            # Reset entire rect to transparent — prevents DWM halo on
            # WA_TranslucentBackground windows on Windows 10/11.
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(self.rect(), Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            w, h      = self.width(), self.height()
            recording = self._state == AppState.RECORDING

            # ── Background fill ──────────────────────────────────────────────
            bg = QPainterPath()
            bg.addRoundedRect(0.0, 0.0, float(w), float(h), _R, _R)
            p.fillPath(bg, QBrush(QColor("#141414")))

            if h > _PILL_H:
                # Hairline separator between pill row and history panel
                p.fillRect(12, _PILL_H - 1, w - 24, 1, QColor("#2C2C2E"))

            # ── Subtle premium border ─────────────────────────────────────────
            # Inset 0.5 px so the 1 px stroke sits fully inside the widget.
            border = QPainterPath()
            border.addRoundedRect(0.5, 0.5, float(w) - 1.0, float(h) - 1.0, _R - 0.5, _R - 0.5)
            pen = QPen(QColor("#3A3A3C"))
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(border)
            p.setPen(Qt.PenStyle.NoPen)

            # ── Pill content (top _PILL_H px) ────────────────────────────────
            left_pad = int(_R)
            if recording:
                self._paint_waveform(p, left_pad, _PILL_H)
            else:
                self._paint_idle(p, left_pad, _PILL_H)
        finally:
            p.end()

    def _paint_idle(self, p: QPainter, lp: int, h: int) -> None:
        transcribing = self._state == AppState.TRANSCRIBING
        dot_c   = "#F59E0B" if transcribing else _IDLE_DOT
        label   = "Обработка..." if transcribing else "Voice Prompt"
        label_c = "#C8922A" if transcribing else "#8E8E93"

        dot_r  = 5
        dot_cx = lp
        dot_cy = h // 2

        glow = QColor(dot_c)
        glow.setAlphaF(0.22)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPoint(dot_cx, dot_cy), dot_r + 5, dot_r + 5)
        p.setBrush(QBrush(QColor(dot_c)))
        p.drawEllipse(QPoint(dot_cx, dot_cy), dot_r, dot_r)

        font = QFont("Segoe UI", 10, QFont.Weight.Medium)
        p.setFont(font)
        p.setPen(QColor(label_c))
        fm = QFontMetrics(font)
        p.drawText(dot_cx + dot_r + 9, (h + fm.ascent() - fm.descent()) // 2, label)

    def _paint_waveform(self, p: QPainter, lp: int, h: int) -> None:
        levels   = list(self._levels)
        cx_start = lp + 2
        p.setPen(Qt.PenStyle.NoPen)

        for i, lvl in enumerate(levels):
            bar_h = max(_BAR_MIN_H, int(_BAR_MAX_H * (lvl ** 0.25)))
            bar_x = cx_start + i * (_BAR_W + 2)
            bar_y = (h - bar_h) // 2
            c     = QColor(_REC_COLOR)
            c.setAlphaF(0.45 + 0.55 * lvl)
            bp = QPainterPath()
            bp.addRoundedRect(bar_x, bar_y, _BAR_W, bar_h, 1.5, 1.5)
            p.fillPath(bp, QBrush(c))

        font = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        p.setFont(font)
        p.setPen(QColor("#E8E8E8"))
        fm  = QFontMetrics(font)
        lx  = cx_start + len(levels) * (_BAR_W + 2) + 6
        ty  = (h + fm.ascent() - fm.descent()) // 2
        p.drawText(lx, ty, "Запись...")


# ── Module-level helpers ───────────────────────────────────────────────────────

def _entry_row(ts: str, text: str) -> QWidget:
    row = QWidget()
    row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    row.setFixedHeight(_ENTRY_H)

    hbox = QHBoxLayout(row)
    hbox.setContentsMargins(14, 8, 10, 8)
    hbox.setSpacing(0)

    col = QVBoxLayout()
    col.setSpacing(2)

    ts_lbl = QLabel(ts)
    ts_lbl.setFont(QFont("Segoe UI", 8))
    ts_lbl.setStyleSheet("color:#484848; background:transparent;")
    col.addWidget(ts_lbl)

    body = QLabel()
    body.setFont(QFont("Segoe UI", 10))
    body.setStyleSheet("color:#C0C0C0; background:transparent;")
    fm = body.fontMetrics()
    body.setText(fm.elidedText(text, Qt.TextElideMode.ElideRight, _W - 60))
    col.addWidget(body)

    hbox.addLayout(col, stretch=1)

    btn = QPushButton("⎘")
    btn.setFixedSize(24, 24)
    btn.setFont(QFont("Segoe UI", 12))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(_S_COPY)

    tmr = QTimer(row)
    tmr.setSingleShot(True)

    def _do_copy(b=btn, t=text, timer=tmr) -> None:
        QApplication.clipboard().setText(t)
        b.setText("✓")
        b.setStyleSheet(_S_COPY_DONE)
        timer.start(1500)

    def _reset(b=btn) -> None:
        b.setText("⎘")
        b.setStyleSheet(_S_COPY)

    tmr.timeout.connect(_reset)
    btn.clicked.connect(_do_copy)
    hbox.addWidget(btn, alignment=Qt.AlignmentFlag.AlignVCenter)

    return row


# ── Styles ─────────────────────────────────────────────────────────────────────

_S_COPY = """
QPushButton {
    background: transparent; color: #3A3A3A;
    border: none; border-radius: 5px; font-size: 14px;
}
QPushButton:hover { background: #222222; color: #AAAAAA; }
"""

_S_COPY_DONE = """
QPushButton {
    background: #0F2318; color: #22C55E;
    border: none; border-radius: 5px; font-size: 13px;
}
"""

_S_COLLAPSE = """
QPushButton {
    background: #1E1E1E; color: #777777; border: none;
    border-radius: 8px; font-family: 'Segoe UI'; font-size: 11px; padding: 0 12px;
}
QPushButton:hover { background: #2A2A2A; color: #BBBBBB; }
"""

_S_EXIT = """
QPushButton {
    background: #1E1E1E; color: #555555; border: none;
    border-radius: 8px; font-family: 'Segoe UI'; font-size: 11px; padding: 0 12px;
}
QPushButton:hover { background: #3D1515; color: #EF4444; }
"""
