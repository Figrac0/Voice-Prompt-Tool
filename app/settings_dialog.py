from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)

# ── Model metadata shown in the combo ─────────────────────────────────────────
_MODELS = [
    ("tiny",   "tiny   — очень быстро, низкая точность (~150 MB)"),
    ("base",   "base   — быстро, средняя точность  (~150 MB)"),
    ("small",  "small  — хорошая точность           (~500 MB)  ✓ рекомендуется"),
    ("medium", "medium — отличная точность          (~1.5 GB)"),
]
_LANGS = [("ru", "Русский (ru)"), ("en", "English (en)"), ("auto", "Авто (auto)")]


class SettingsDialog(QDialog):
    """Dark-themed settings editor that reads/writes config.json directly."""

    def __init__(self, config_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config_path = config_path

        self.setWindowTitle("Настройки — Voice Prompt Tool")
        self.setMinimumWidth(480)
        self.setModal(True)
        self.setStyleSheet(_DARK_STYLE)

        self._build_ui()
        self._load_values()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(16, 16, 16, 16)

        # ── Recognition ──────────────────────────────────────────────────────
        rec_box = QGroupBox("Распознавание речи")
        rec_form = QFormLayout(rec_box)
        rec_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        rec_form.setVerticalSpacing(8)

        self._model_combo = QComboBox()
        for _, label in _MODELS:
            self._model_combo.addItem(label)
        rec_form.addRow("Модель:", self._model_combo)

        self._lang_combo = QComboBox()
        for _, label in _LANGS:
            self._lang_combo.addItem(label)
        rec_form.addRow("Язык:", self._lang_combo)

        beam_row = QWidget()
        beam_hl = QHBoxLayout(beam_row)
        beam_hl.setContentsMargins(0, 0, 0, 0)
        beam_hl.setSpacing(10)
        self._beam_spin = QSpinBox()
        self._beam_spin.setRange(1, 10)
        self._beam_spin.setFixedWidth(58)
        self._beam_label = QLabel()
        self._beam_label.setStyleSheet("color: #8E8E93;")
        self._beam_spin.valueChanged.connect(self._update_beam_label)
        beam_hl.addWidget(self._beam_spin)
        beam_hl.addWidget(self._beam_label, 1)
        rec_form.addRow("Качество (beam):", beam_row)

        root.addWidget(rec_box)

        # ── Hotkey ────────────────────────────────────────────────────────────
        hk_box = QGroupBox("Горячая клавиша")
        hk_form = QFormLayout(hk_box)
        hk_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._hotkey_edit = QLineEdit()
        self._hotkey_edit.setPlaceholderText("Например: ctrl+shift")
        hk_form.addRow("Комбинация:", self._hotkey_edit)

        hk_hint = QLabel("Доступные модификаторы: ctrl, shift, alt, win")
        hk_hint.setStyleSheet("color: #636366; font-size: 11px;")
        hk_form.addRow("", hk_hint)

        root.addWidget(hk_box)

        # ── Text injection ────────────────────────────────────────────────────
        txt_box = QGroupBox("Ввод текста")
        txt_vbox = QVBoxLayout(txt_box)
        txt_vbox.setSpacing(8)

        self._autopaste_cb = QCheckBox("Вставлять текст в активное поле автоматически")
        self._autocopy_cb = QCheckBox("Копировать результат в буфер обмена")
        txt_vbox.addWidget(self._autopaste_cb)
        txt_vbox.addWidget(self._autocopy_cb)

        root.addWidget(txt_box)

        # ── Info banner ───────────────────────────────────────────────────────
        note = QLabel(
            "ℹ  Изменение модели вступит в силу при следующем запуске приложения."
        )
        note.setStyleSheet("color: #636366; font-size: 11px; padding: 0 2px;")
        note.setWordWrap(True)
        root.addWidget(note)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_box = QDialogButtonBox()
        self._save_btn = btn_box.addButton("Сохранить", QDialogButtonBox.ButtonRole.AcceptRole)
        self._save_btn.setObjectName("primary")
        btn_box.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)
        btn_box.accepted.connect(self._save)
        btn_box.rejected.connect(self.reject)
        root.addWidget(btn_box)

    # ── Load / save ────────────────────────────────────────────────────────────

    def _load_values(self) -> None:
        raw = self._read_raw()
        t = raw.get("transcription", {})
        hk = raw.get("hotkey", {})
        pp = raw.get("text_postprocess", {})

        model_size = t.get("model_size", "small")
        model_idx = next((i for i, (k, _) in enumerate(_MODELS) if k == model_size), 2)
        self._model_combo.setCurrentIndex(model_idx)

        lang = t.get("language_mode", "ru")
        lang_idx = next((i for i, (k, _) in enumerate(_LANGS) if k == lang), 0)
        self._lang_combo.setCurrentIndex(lang_idx)

        beam = t.get("beam_size", 5)
        self._beam_spin.setValue(beam)
        self._update_beam_label(beam)

        self._hotkey_edit.setText(hk.get("combination", "ctrl+shift"))
        self._autopaste_cb.setChecked(pp.get("auto_paste", True))
        self._autocopy_cb.setChecked(pp.get("auto_copy", True))

    def _save(self) -> None:
        model_key = _MODELS[self._model_combo.currentIndex()][0]
        lang_key = _LANGS[self._lang_combo.currentIndex()][0]
        beam = self._beam_spin.value()
        hotkey = self._hotkey_edit.text().strip().lower() or "ctrl+shift"
        autopaste = self._autopaste_cb.isChecked()
        autocopy = self._autocopy_cb.isChecked()

        raw = self._read_raw()

        raw.setdefault("transcription", {}).update(
            model_size=model_key,
            language_mode=lang_key,
            beam_size=beam,
            best_of=beam,
        )
        raw.setdefault("live_preview", {})["language_mode"] = lang_key
        raw.setdefault("hotkey", {})["combination"] = hotkey
        raw.setdefault("text_postprocess", {}).update(
            auto_paste=autopaste,
            auto_copy=autocopy,
        )

        try:
            with self._config_path.open("w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
                f.write("\n")
        except OSError as exc:
            log.exception("Failed to save settings.")
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить настройки:\n{exc}")
            return

        log.info("Settings saved to %s", self._config_path)
        self.accept()

    def _read_raw(self) -> dict:
        try:
            with self._config_path.open(encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _update_beam_label(self, value: int) -> None:
        desc = {
            1: "минимальная точность, максимальная скорость",
            2: "быстро",
            3: "хорошо",
            4: "хорошо",
            5: "рекомендуется",
            6: "высокая точность",
            7: "высокая точность",
            8: "очень высокая точность",
            9: "очень высокая точность",
            10: "максимальная точность, медленнее",
        }.get(value, "")
        self._beam_label.setText(desc)


# ── Stylesheet ─────────────────────────────────────────────────────────────────

_DARK_STYLE = """
QDialog {
    background-color: #1C1C1E;
    color: #EBEBF5;
    font-family: "Segoe UI";
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #38383A;
    border-radius: 8px;
    margin-top: 16px;
    padding: 10px 10px 12px 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #8E8E93;
    font-size: 12px;
}
QLabel {
    color: #EBEBF5;
}
QComboBox, QSpinBox, QLineEdit {
    background-color: #2C2C2E;
    color: #FFFFFF;
    border: 1px solid #48484A;
    border-radius: 6px;
    padding: 5px 10px;
    min-height: 26px;
    selection-background-color: #0A84FF;
}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {
    border-color: #0A84FF;
}
QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: #2C2C2E;
    color: #FFFFFF;
    border: 1px solid #48484A;
    border-radius: 6px;
    selection-background-color: #3A3A3C;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 18px;
    background: #3A3A3C;
    border: none;
    border-radius: 3px;
}
QCheckBox {
    color: #EBEBF5;
    spacing: 10px;
    min-height: 24px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1.5px solid #48484A;
    background-color: #2C2C2E;
}
QCheckBox::indicator:checked {
    background-color: #0A84FF;
    border-color: #0A84FF;
}
QPushButton {
    background-color: #2C2C2E;
    color: #FFFFFF;
    border: 1px solid #48484A;
    border-radius: 7px;
    padding: 7px 20px;
    min-width: 90px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #3A3A3C;
    border-color: #636366;
}
QPushButton#primary {
    background-color: #0A84FF;
    border-color: #0A84FF;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton#primary:hover {
    background-color: #2997FF;
    border-color: #2997FF;
}
"""
