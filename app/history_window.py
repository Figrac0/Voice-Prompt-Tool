from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


def _fmt_ts(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso[:19])
        now = datetime.now()
        diff = (now.date() - dt.date()).days
        time = dt.strftime("%H:%M")
        if diff == 0:
            return f"сегодня, {time}"
        if diff == 1:
            return f"вчера, {time}"
        months = ["янв", "фев", "мар", "апр", "май", "июн",
                  "июл", "авг", "сен", "окт", "ноя", "дек"]
        return f"{dt.day} {months[dt.month - 1]}, {time}"
    except Exception:
        return iso[:16].replace("T", " ")


def _pluralise(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} запись"
    if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
        return f"{n} записи"
    return f"{n} записей"


class _EntryCard(QFrame):
    def __init__(self, ts: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = text

        self.setObjectName("card")
        self.setStyleSheet(_CARD_STYLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        # ── Header: timestamp + copy button ───────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(8)

        ts_lbl = QLabel(ts)
        ts_lbl.setFont(QFont("Segoe UI", 9))
        ts_lbl.setStyleSheet("color:#636366; background:transparent;")
        header.addWidget(ts_lbl)
        header.addStretch()

        self._copy_btn = QPushButton("Скопировать")
        self._copy_btn.setFixedHeight(22)
        self._copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_btn.setStyleSheet(_COPY_BTN)
        self._copy_btn.clicked.connect(self._copy)
        header.addWidget(self._copy_btn)

        layout.addLayout(header)

        # ── Body text ─────────────────────────────────────────────────────────
        body = QLabel(text)
        body.setWordWrap(True)
        body.setFont(QFont("Segoe UI", 11))
        body.setStyleSheet("color:#F2F2F7; background:transparent;")
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(body)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._text)
        self._copy_btn.setText("Скопировано ✓")
        self._copy_btn.setStyleSheet(_COPY_BTN_DONE)
        QTimer.singleShot(1800, self._reset_btn)

    def _reset_btn(self) -> None:
        self._copy_btn.setText("Скопировать")
        self._copy_btn.setStyleSheet(_COPY_BTN)

    def mouseDoubleClickEvent(self, _event) -> None:  # noqa: N802
        self._copy()


class _Signals(QObject):
    refresh = Signal()


class HistoryWindow(QWidget):
    """Floating history panel — shows past transcriptions as cards."""

    def __init__(
        self,
        history_file: Path,
        app_name: str,
        hotkey: str,
        on_exit: Callable[[], None],
        logger: logging.Logger,
    ) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self._history_file = history_file
        self._on_exit = on_exit
        self._logger = logger

        self.setWindowTitle(app_name)
        self.setMinimumSize(480, 540)
        self.resize(520, 700)
        self.setStyleSheet("QWidget { background:#1C1C1E; }")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ───────────────────────────────────────────────────────────
        topbar = QWidget()
        topbar.setFixedHeight(58)
        topbar.setStyleSheet("background:#2C2C2E; border-bottom:1px solid #38383A;")
        tb = QHBoxLayout(topbar)
        tb.setContentsMargins(20, 0, 20, 0)

        icon_title = QLabel("🎤  Voice Prompt Tool")
        icon_title.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        icon_title.setStyleSheet("color:#F2F2F7; background:transparent;")
        tb.addWidget(icon_title)
        tb.addStretch()

        self._count_lbl = QLabel("")
        self._count_lbl.setFont(QFont("Segoe UI", 10))
        self._count_lbl.setStyleSheet(
            "color:#8E8E93; background:#3A3A3C; padding:3px 10px;"
            " border-radius:10px;"
        )
        tb.addWidget(self._count_lbl)

        root.addWidget(topbar)

        # ── Scroll area with cards ─────────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(_SCROLL_STYLE)

        self._cards_host = QWidget()
        self._cards_host.setStyleSheet("background:#1C1C1E;")
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(16, 16, 16, 16)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch()

        scroll.setWidget(self._cards_host)
        root.addWidget(scroll, stretch=1)

        # ── Bottom bar ────────────────────────────────────────────────────────
        botbar = QWidget()
        botbar.setFixedHeight(56)
        botbar.setStyleSheet("background:#2C2C2E; border-top:1px solid #38383A;")
        bb = QHBoxLayout(botbar)
        bb.setContentsMargins(20, 0, 20, 0)
        bb.setSpacing(10)

        hotkey_chip = QLabel(hotkey.upper().replace("+", " + "))
        hotkey_chip.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        hotkey_chip.setStyleSheet(
            "color:#8E8E93; background:#3A3A3C; padding:4px 12px;"
            " border-radius:6px;"
        )
        bb.addWidget(hotkey_chip)
        bb.addStretch()

        hide_btn = QPushButton("Свернуть")
        hide_btn.setFixedSize(96, 34)
        hide_btn.setStyleSheet(_BTN_SECONDARY)
        hide_btn.clicked.connect(self.hide)
        bb.addWidget(hide_btn)

        exit_btn = QPushButton("Завершить")
        exit_btn.setFixedSize(110, 34)
        exit_btn.setStyleSheet(_BTN_DANGER)
        exit_btn.clicked.connect(self._do_exit)
        bb.addWidget(exit_btn)

        root.addWidget(botbar)

        # Thread-safe signal bridge
        self._signals = _Signals(self)
        self._signals.refresh.connect(self.reload)

        self.reload()

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

    # ── Slots ──────────────────────────────────────────────────────────────────

    def reload(self) -> None:
        # Remove all cards (keep the trailing stretch)
        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        entries = self._load_entries()

        if not entries:
            empty = QLabel("Записей пока нет.\n\nЗажмите горячую клавишу и начните говорить.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setFont(QFont("Segoe UI", 12))
            empty.setStyleSheet("color:#48484A; background:transparent;")
            self._cards_layout.insertWidget(0, empty)
            self._count_lbl.setText("нет записей")
            return

        self._count_lbl.setText(_pluralise(len(entries)))

        for entry in reversed(entries):
            ts   = _fmt_ts(entry.get("created_at", ""))
            text = entry.get("cleaned_text") or entry.get("raw_text") or ""
            if not text:
                continue
            card = _EntryCard(ts, text)
            self._cards_layout.insertWidget(0, card)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _do_exit(self) -> None:
        self._logger.info("Exit requested from history window.")
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
            self._logger.exception("Failed to load history.")
            return []


# ── Styles ─────────────────────────────────────────────────────────────────────

_CARD_STYLE = """
QFrame#card {
    background: #2C2C2E;
    border: 1px solid #38383A;
    border-radius: 10px;
}
QFrame#card:hover {
    background: #323234;
    border-color: #48484A;
}
"""

_COPY_BTN = """
QPushButton {
    background: #3A3A3C;
    color: #8E8E93;
    border: none;
    border-radius: 5px;
    padding: 0 10px;
    font-size: 11px;
    font-family: 'Segoe UI';
}
QPushButton:hover { background: #48484A; color: #EBEBF5; }
"""

_COPY_BTN_DONE = """
QPushButton {
    background: #1C3A25;
    color: #30D158;
    border: none;
    border-radius: 5px;
    padding: 0 10px;
    font-size: 11px;
    font-family: 'Segoe UI';
}
"""

_SCROLL_STYLE = """
QScrollArea { border: none; background: #1C1C1E; }
QScrollBar:vertical {
    background: #2C2C2E;
    width: 5px;
    border-radius: 3px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #48484A;
    border-radius: 3px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
"""

_BTN_SECONDARY = """
QPushButton {
    background: #3A3A3C;
    color: #EBEBF5;
    border: none;
    border-radius: 8px;
    font-size: 13px;
    font-family: 'Segoe UI';
}
QPushButton:hover { background: #48484A; }
QPushButton:pressed { background: #2C2C2E; }
"""

_BTN_DANGER = """
QPushButton {
    background: #2A1515;
    color: #FF453A;
    border: 1px solid #FF453A44;
    border-radius: 8px;
    font-size: 13px;
    font-family: 'Segoe UI';
}
QPushButton:hover { background: #FF453A; color: #FFF; border-color: #FF453A; }
QPushButton:pressed { background: #C0392B; color: #FFF; }
"""
