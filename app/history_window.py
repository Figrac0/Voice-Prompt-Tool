from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_MAX_ENTRIES = 5
_W           = 360   # inner panel width
_HEADER_H    = 44
_ENTRY_H     = 62
_SHADOW      = 14    # margin for drop-shadow


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
        months = ["янв","фев","мар","апр","май","июн","июл","авг","сен","окт","ноя","дек"]
        return f"{dt.day} {months[dt.month - 1]}, {t}"
    except Exception:
        return iso[:16].replace("T", " ")


class _EntryRow(QWidget):
    def __init__(self, ts: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text  = text
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._reset_btn)

        self.setFixedHeight(_ENTRY_H)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QWidget { background: transparent; }")

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 10, 14, 10)
        row.setSpacing(0)

        # Text column
        col = QVBoxLayout()
        col.setSpacing(4)

        ts_lbl = QLabel(ts)
        ts_lbl.setFont(QFont("Segoe UI", 9))
        ts_lbl.setStyleSheet("color:#4A4A4A; background:transparent;")
        col.addWidget(ts_lbl)

        body = QLabel()
        body.setFont(QFont("Segoe UI", 11))
        body.setStyleSheet("color:#D0D0D0; background:transparent;")
        # Elide long text
        fm      = body.fontMetrics()
        elided  = fm.elidedText(text, Qt.TextElideMode.ElideRight, 268)
        body.setText(elided)
        col.addWidget(body)

        row.addLayout(col, stretch=1)

        # Copy button
        self._btn = QPushButton("⎘")
        self._btn.setFixedSize(28, 28)
        self._btn.setFont(QFont("Segoe UI", 13))
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setStyleSheet(_BTN_COPY)
        self._btn.clicked.connect(self._copy)
        row.addWidget(self._btn, alignment=Qt.AlignmentFlag.AlignVCenter)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._text)
        self._btn.setText("✓")
        self._btn.setStyleSheet(_BTN_COPY_DONE)
        self._timer.start(1600)

    def _reset_btn(self) -> None:
        self._btn.setText("⎘")
        self._btn.setStyleSheet(_BTN_COPY)

    def mouseDoubleClickEvent(self, _event) -> None:  # noqa: N802
        self._copy()

    def enterEvent(self, _event) -> None:  # noqa: N802
        self.setStyleSheet("QWidget { background: #1C1C1C; }")

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self.setStyleSheet("QWidget { background: transparent; }")


class _Signals(QObject):
    refresh      = Signal()
    state_update = Signal(object)   # AppState


class HistoryWindow(QWidget):
    def __init__(
        self,
        history_file: Path,
        app_name: str,
        hotkey: str,
        on_exit: Callable[[], None],
        logger: logging.Logger,
        state_store=None,
    ) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._history_file = history_file
        self._on_exit      = on_exit
        self._logger       = logger
        self._drag_pos: QPoint | None = None

        # ── Outer layout — provides shadow margin ──────────────────────────────
        s = _SHADOW
        outer = QVBoxLayout(self)
        outer.setContentsMargins(s, s, s, s)

        # ── Inner panel ────────────────────────────────────────────────────────
        self._panel = QWidget(self)
        self._panel.setObjectName("panel")
        self._panel.setStyleSheet("""
            QWidget#panel {
                background: #111111;
                border-radius: 12px;
                border: 1px solid #242424;
            }
        """)
        outer.addWidget(self._panel)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setColor(QColor(0, 0, 0, 130))
        shadow.setOffset(0, 8)
        self._panel.setGraphicsEffect(shadow)

        panel_vbox = QVBoxLayout(self._panel)
        panel_vbox.setContentsMargins(0, 0, 0, 0)
        panel_vbox.setSpacing(0)

        # ── Header ─────────────────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(_HEADER_H)
        header.setStyleSheet("background:transparent;")
        header.setCursor(Qt.CursorShape.SizeAllCursor)
        header.mousePressEvent = self._drag_press   # type: ignore[method-assign]
        header.mouseMoveEvent  = self._drag_move    # type: ignore[method-assign]

        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 12, 0)
        hl.setSpacing(8)

        self._dot = QLabel("●")
        self._dot.setFont(QFont("Segoe UI", 7))
        self._dot.setStyleSheet("color:#22C55E; background:transparent;")
        hl.addWidget(self._dot)

        title = QLabel("Voice Prompt")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Medium))
        title.setStyleSheet("color:#E0E0E0; background:transparent;")
        hl.addWidget(title)
        hl.addStretch()

        hk = QLabel(hotkey.upper())
        hk.setFont(QFont("Segoe UI", 9))
        hk.setStyleSheet("color:#333; background:transparent;")
        hl.addWidget(hk)

        min_btn = QPushButton("—")
        min_btn.setFixedSize(26, 26)
        min_btn.setStyleSheet(_BTN_HEADER)
        min_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        min_btn.clicked.connect(self.hide)
        hl.addWidget(min_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(26, 26)
        close_btn.setStyleSheet(_BTN_HEADER_CLOSE)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self._do_exit)
        hl.addWidget(close_btn)

        panel_vbox.addWidget(header)

        # Divider below header
        div = QWidget()
        div.setFixedHeight(1)
        div.setStyleSheet("background:#1E1E1E;")
        panel_vbox.addWidget(div)

        # ── Entries container ──────────────────────────────────────────────────
        self._entries_host   = QWidget()
        self._entries_host.setStyleSheet("background:transparent;")
        self._entries_layout = QVBoxLayout(self._entries_host)
        self._entries_layout.setContentsMargins(0, 0, 0, 0)
        self._entries_layout.setSpacing(0)
        panel_vbox.addWidget(self._entries_host)

        # Position bottom-right, near tray
        screen = QApplication.primaryScreen().geometry()
        self.move(
            screen.width()  - (_W + s * 2) - 20,
            screen.height() - (_HEADER_H + _ENTRY_H * _MAX_ENTRIES + s * 2) - 80,
        )

        # Signals
        self._signals = _Signals(self)
        self._signals.refresh.connect(self._reload)
        self._signals.state_update.connect(self._on_state)

        if state_store is not None:
            state_store.register_listener(
                lambda snap: self._signals.state_update.emit(snap.state)
            )

        self._reload()

    # ── Public API ─────────────────────────────────────────────────────────────

    def show_and_raise(self) -> None:
        self._signals.refresh.emit()
        self.show()
        self.raise_()
        self.activateWindow()

    def notify_new_entry(self) -> None:
        if self.isVisible():
            self._signals.refresh.emit()

    # ── Qt overrides ───────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: N802
        event.ignore()
        self.hide()

    # ── Drag ──────────────────────────────────────────────────────────────────

    def _drag_press(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _drag_move(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _on_state(self, state) -> None:
        from app.state import AppState
        colors = {
            AppState.IDLE:         "#22C55E",
            AppState.RECORDING:    "#EF4444",
            AppState.TRANSCRIBING: "#F59E0B",
            AppState.ERROR:        "#555555",
        }
        self._dot.setStyleSheet(f"color:{colors.get(state, '#22C55E')}; background:transparent;")

    def _reload(self) -> None:
        while self._entries_layout.count():
            item = self._entries_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        entries = self._load_entries()[-_MAX_ENTRIES:]

        n = 0
        if not entries:
            lbl = QLabel("Записей пока нет.\nЗажмите горячую клавишу и говорите.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFont(QFont("Segoe UI", 11))
            lbl.setStyleSheet("color:#2E2E2E; background:transparent; padding:28px;")
            self._entries_layout.addWidget(lbl)
        else:
            for i, entry in enumerate(reversed(entries)):
                ts   = _fmt_ts(entry.get("created_at", ""))
                text = entry.get("cleaned_text") or entry.get("raw_text") or ""
                if not text:
                    continue
                self._entries_layout.addWidget(_EntryRow(ts, text))
                n += 1
                if i < len(entries) - 1:
                    sep = QWidget()
                    sep.setFixedHeight(1)
                    sep.setStyleSheet("background:#191919;")
                    self._entries_layout.addWidget(sep)

        # Resize panel to fit content
        s          = _SHADOW
        content_h  = 80 if n == 0 else (n * _ENTRY_H + max(0, n - 1))
        inner_h    = _HEADER_H + 1 + content_h
        self.setFixedSize(_W + s * 2, inner_h + s * 2)

    def _do_exit(self) -> None:
        self._logger.info("Exit from history window.")
        self._on_exit()
        QApplication.quit()

    def _load_entries(self) -> list[dict]:
        if not self._history_file.exists():
            return []
        try:
            with self._history_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("entries", []) if isinstance(data, dict) else []
        except Exception:
            return []


# ── Styles ─────────────────────────────────────────────────────────────────────

_BTN_COPY = """
QPushButton {
    background: transparent;
    color: #363636;
    border: none;
    border-radius: 6px;
    font-size: 14px;
}
QPushButton:hover {
    background: #222222;
    color: #BBBBBB;
}
"""

_BTN_COPY_DONE = """
QPushButton {
    background: #132318;
    color: #22C55E;
    border: none;
    border-radius: 6px;
    font-size: 13px;
}
"""

_BTN_HEADER = """
QPushButton {
    background: transparent;
    color: #3A3A3A;
    border: none;
    border-radius: 5px;
    font-size: 13px;
}
QPushButton:hover { background: #222222; color: #888888; }
"""

_BTN_HEADER_CLOSE = """
QPushButton {
    background: transparent;
    color: #3A3A3A;
    border: none;
    border-radius: 5px;
    font-size: 11px;
}
QPushButton:hover { background: #3D1515; color: #EF4444; }
"""
