from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from app.config import AppConfig
from app.state import AppState, StateSnapshot, StateStore


class _TraySignals(QObject):
    state_changed = Signal(object)  # StateSnapshot


class TrayApp(QSystemTrayIcon):
    """Qt system tray icon with context menu, dynamic state icons, and notifications."""

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        state_store: StateStore,
        notifier=None,          # kept for compat, not used – NotificationManager calls us
        on_ready: Callable[[], None] | None = None,
        on_exit: Callable[[], None] | None = None,
        on_open_settings: Callable[[], None] | None = None,
        on_open_history: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._logger = logger
        self._state_store = state_store
        self._on_exit = on_exit
        self._on_open_settings = on_open_settings
        self._on_open_history = on_open_history
        self._last_preview = ""

        # Pre-render one icon per state so tray updates are instant
        self._icons: dict[AppState, QIcon] = {s: _build_icon(s) for s in AppState}
        self.setIcon(self._icons[AppState.IDLE])
        self.setToolTip(config.tray.tooltip)

        # ── Context menu ──────────────────────────────────────────────────────
        menu = QMenu()
        menu.setStyleSheet(_MENU_STYLE)

        self._status_action = QAction("Voice Prompt Tool  —  Готов")
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)

        self._preview_action = QAction("")
        self._preview_action.setEnabled(False)
        self._preview_action.setVisible(False)
        menu.addAction(self._preview_action)

        menu.addSeparator()

        settings_act = QAction("⚙   Настройки...")
        settings_act.triggered.connect(self._open_settings)
        menu.addAction(settings_act)

        history_act = QAction("📋  История записей")
        history_act.triggered.connect(self._open_history)
        menu.addAction(history_act)

        menu.addSeparator()

        hotkey_act = QAction(f"Клавиши: {config.hotkey.combination.upper()}")
        hotkey_act.setEnabled(False)
        menu.addAction(hotkey_act)

        menu.addSeparator()

        exit_act = QAction("✕   Выход")
        exit_act.triggered.connect(self._do_exit)
        menu.addAction(exit_act)

        self.setContextMenu(menu)

        # ── Left-click opens history window ───────────────────────────────────
        self.activated.connect(self._on_activated)

        # ── State listener (thread-safe via Qt signal bridge) ─────────────────
        self._signals = _TraySignals(self)
        self._signals.state_changed.connect(self._on_state_changed)
        state_store.register_listener(
            lambda snap: self._signals.state_changed.emit(snap)
        )

        self.show()

        # Notify on_ready immediately (replaces pystray setup callback)
        if on_ready is not None:
            on_ready()

    # ── Public API (kept for compatibility) ───────────────────────────────────

    def run(self) -> None:
        """No-op: the Qt event loop is managed by main.py."""

    def notify(self, title: str, message: str, level: int = 0) -> None:
        try:
            icon_type = QSystemTrayIcon.MessageIcon.Information
            self.showMessage(title, message, icon_type, 3500)
        except Exception:
            pass

    def bind_tray_icon(self, _icon) -> None:
        """Compatibility shim – no longer needed."""

    def set_last_transcript_preview(self, text: str | None) -> None:
        if text:
            normalized = " ".join(text.split())[:80]
            self._last_preview = normalized
            self._preview_action.setText(f"   ↳ «{normalized}»")
            self._preview_action.setVisible(True)
        else:
            self._last_preview = ""
            self._preview_action.setVisible(False)

    # ── Qt slots ──────────────────────────────────────────────────────────────

    def _on_state_changed(self, snap: StateSnapshot) -> None:
        self.setIcon(self._icons[snap.state])
        label = {
            AppState.IDLE: "Готов",
            AppState.RECORDING: "Запись…",
            AppState.TRANSCRIBING: "Обработка…",
            AppState.ERROR: "Ошибка",
        }.get(snap.state, snap.state.value)
        self._status_action.setText(f"Voice Prompt Tool  —  {label}")
        self.setToolTip(f"{self._config.tray.tooltip}  —  {label}")

    def _open_settings(self) -> None:
        if self._on_open_settings:
            self._on_open_settings()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._open_history()

    def _open_history(self) -> None:
        if self._on_open_history:
            self._on_open_history()

    def _do_exit(self) -> None:
        self._logger.info("Exit requested from tray menu.")
        self._state_store.shutdown("Application is shutting down.")
        if self._on_exit:
            self._on_exit()
        QApplication.quit()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_icon(state: AppState) -> QIcon:
    """Draw a microphone icon whose colours reflect the current app state."""
    size = 64
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    bg_hex, fg_hex = {
        AppState.IDLE: ("#18202E", "#459FFF"),
        AppState.RECORDING: ("#2D0000", "#FF3B30"),
        AppState.TRANSCRIBING: ("#2A1800", "#FF9F0A"),
        AppState.ERROR: ("#1A1A1A", "#8E8E93"),
    }.get(state, ("#18202E", "#459FFF"))

    fg = QColor(fg_hex)

    # Background circle
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(bg_hex)))
    p.drawEllipse(2, 2, 60, 60)

    # Microphone body
    p.setBrush(QBrush(fg))
    body = QPainterPath()
    body.addRoundedRect(22, 10, 20, 28, 10, 10)
    p.fillPath(body, fg)

    # Stand
    p.fillRect(30, 38, 4, 8, fg)

    # Base
    base = QPainterPath()
    base.addRoundedRect(20, 46, 24, 5, 2, 2)
    p.fillPath(base, fg)

    # Acoustic arc
    arc_pen = QPen(fg, 3)
    arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(arc_pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(14, 10, 36, 40, 200 * 16, 140 * 16)

    p.end()
    return QIcon(pix)


_MENU_STYLE = """
QMenu {
    background-color: #2C2C2E;
    color: #EBEBF5;
    border: 1px solid #48484A;
    border-radius: 8px;
    padding: 4px 0;
}
QMenu::item {
    padding: 6px 20px 6px 12px;
    border-radius: 4px;
    margin: 1px 4px;
}
QMenu::item:selected {
    background-color: #3A3A3C;
}
QMenu::item:disabled {
    color: #636366;
}
QMenu::separator {
    height: 1px;
    background: #38383A;
    margin: 3px 8px;
}
"""
