from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QColor, QFont, QClipboard
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class _Signals(QObject):
    refresh_requested = Signal()


class HistoryWindow(QMainWindow):
    """Main application window — shows transcription history and allows exit."""

    def __init__(
        self,
        history_file: Path,
        app_name: str,
        hotkey: str,
        on_exit: Callable[[], None],
        logger: logging.Logger,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Window,
        )
        self._history_file = history_file
        self._on_exit = on_exit
        self._logger = logger

        self.setWindowTitle(app_name)
        self.setMinimumSize(520, 580)
        self.resize(520, 620)
        self.setStyleSheet(_WINDOW_STYLE)

        # Center on screen
        screen = QApplication.primaryScreen().geometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )

        # Closing the window hides it (doesn't exit the app)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        # ── Header ────────────────────────────────────────────────────────────
        header = QHBoxLayout()
        title_label = QLabel(app_name)
        title_label.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #F2F2F7;")
        header.addWidget(title_label)
        header.addStretch()

        hotkey_label = QLabel(f"Горячая клавиша:  {hotkey.upper()}")
        hotkey_label.setFont(QFont("Segoe UI", 10))
        hotkey_label.setStyleSheet("color: #8E8E93; padding: 4px 10px; background:#2C2C2E; border-radius:6px;")
        header.addWidget(hotkey_label)
        layout.addLayout(header)

        # ── Divider ───────────────────────────────────────────────────────────
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background:#38383A; max-height:1px; border:none;")
        layout.addWidget(line)

        # ── History label ─────────────────────────────────────────────────────
        hist_label = QLabel("История записей")
        hist_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        hist_label.setStyleSheet("color: #EBEBF5;")
        layout.addWidget(hist_label)

        # ── List ──────────────────────────────────────────────────────────────
        self._list = QListWidget()
        self._list.setStyleSheet(_LIST_STYLE)
        self._list.setSpacing(2)
        self._list.setWordWrap(True)
        self._list.itemDoubleClicked.connect(self._copy_item)
        layout.addWidget(self._list, stretch=1)

        copy_hint = QLabel("Двойной клик — скопировать запись")
        copy_hint.setFont(QFont("Segoe UI", 9))
        copy_hint.setStyleSheet("color: #636366;")
        layout.addWidget(copy_hint)

        # ── Bottom buttons ────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        refresh_btn = QPushButton("Обновить")
        refresh_btn.setFixedHeight(36)
        refresh_btn.setStyleSheet(_BTN_SECONDARY)
        refresh_btn.clicked.connect(self.refresh)
        btn_row.addWidget(refresh_btn)

        btn_row.addStretch()

        hide_btn = QPushButton("Свернуть")
        hide_btn.setFixedHeight(36)
        hide_btn.setStyleSheet(_BTN_SECONDARY)
        hide_btn.clicked.connect(self.hide)
        btn_row.addWidget(hide_btn)

        exit_btn = QPushButton("Завершить")
        exit_btn.setFixedHeight(36)
        exit_btn.setMinimumWidth(100)
        exit_btn.setStyleSheet(_BTN_DANGER)
        exit_btn.clicked.connect(self._do_exit)
        btn_row.addWidget(exit_btn)

        layout.addLayout(btn_row)

        self._signals = _Signals(self)
        self._signals.refresh_requested.connect(self.refresh)

        self.refresh()

    # ── Public API ─────────────────────────────────────────────────────────────

    def show_and_raise(self) -> None:
        """Show window and bring it to front (called from any thread via signal)."""
        self._signals.refresh_requested.emit()
        self.show()
        self.raise_()
        self.activateWindow()

    def notify_new_entry(self) -> None:
        """Call after a new transcription completes to refresh if visible."""
        if self.isVisible():
            self._signals.refresh_requested.emit()

    # ── Qt overrides ───────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:  # noqa: N802
        event.ignore()
        self.hide()

    # ── Slots ──────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._list.clear()
        entries = self._load_entries()
        if not entries:
            placeholder = QListWidgetItem("Записей пока нет.")
            placeholder.setForeground(QColor("#636366"))
            placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._list.addItem(placeholder)
            return

        for entry in reversed(entries):
            ts = entry.get("created_at", "")[:16].replace("T", "  ")
            text = entry.get("cleaned_text") or entry.get("raw_text") or ""
            if not text:
                continue
            item = QListWidgetItem(f"{ts}\n{text}")
            item.setData(Qt.ItemDataRole.UserRole, text)
            item.setFont(QFont("Segoe UI", 10))
            self._list.addItem(item)

    def _copy_item(self, item: QListWidgetItem) -> None:
        text = item.data(Qt.ItemDataRole.UserRole)
        if text:
            QApplication.clipboard().setText(text)

    def _do_exit(self) -> None:
        self._logger.info("Exit requested from history window.")
        self._on_exit()
        QApplication.quit()

    # ── Helpers ────────────────────────────────────────────────────────────────

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

_WINDOW_STYLE = """
QMainWindow, QWidget {
    background-color: #1C1C1E;
}
"""

_LIST_STYLE = """
QListWidget {
    background-color: #2C2C2E;
    border: 1px solid #38383A;
    border-radius: 8px;
    padding: 4px;
    color: #F2F2F7;
    outline: none;
}
QListWidget::item {
    padding: 10px 12px;
    border-radius: 6px;
    margin: 2px 0;
    border-bottom: 1px solid #38383A;
}
QListWidget::item:selected {
    background-color: #3A3A3C;
    color: #FFFFFF;
}
QListWidget::item:hover {
    background-color: #323234;
}
"""

_BTN_SECONDARY = """
QPushButton {
    background-color: #3A3A3C;
    color: #EBEBF5;
    border: none;
    border-radius: 8px;
    padding: 0 16px;
    font-size: 13px;
}
QPushButton:hover { background-color: #48484A; }
QPushButton:pressed { background-color: #2C2C2E; }
"""

_BTN_DANGER = """
QPushButton {
    background-color: #3A1C1C;
    color: #FF453A;
    border: 1px solid #FF453A44;
    border-radius: 8px;
    padding: 0 16px;
    font-size: 13px;
    font-weight: 600;
}
QPushButton:hover { background-color: #FF453A; color: #FFFFFF; }
QPushButton:pressed { background-color: #D93025; color: #FFFFFF; }
"""
