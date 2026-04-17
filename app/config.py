from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_GROQ: dict[str, Any] = {
    "enabled": False,
    "api_key": "",
    "model": "whisper-large-v3-turbo",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "app_name": "Voice Prompt Tool",
    "log_level": "INFO",
    "history_limit": 100,
    "paths": {
        "logs_dir": "logs",
        "history_file": "data/history.json",
        "temp_dir": "temp",
        "models_dir": "models",
    },
    "tray": {
        "tooltip": "Voice Prompt Tool",
        "startup_notification": True,
    },
    "notifications": {
        "enabled": True,
        "backend": "log",
    },
    "hotkey": {
        "combination": "ctrl+shift",
    },
    "audio": {
        "sample_rate": 16000,
        "channels": 1,
        "block_frames": 1024,
        "max_record_seconds": 120,
        "min_duration_seconds": 0.35,
        "stale_temp_file_age_hours": 24,
        "file_prefix": "recording",
    },
    "transcription": {
        "model_size": "small",
        "language_mode": "ru",
        "device": "auto",
        "compute_type": "float32",
        "cpu_threads": 2,
        "beam_size": 3,
        "best_of": 3,
        "condition_on_previous_text": False,
        "without_timestamps": True,
        "vad_filter": True,
        "initial_prompt": (
            "Это голосовая диктовка на русском и английском. "
            "Распознавай слова дословно. Не придумывай слова, которых нет в аудио. "
            "Сохраняй естественные точки, запятые и вопросительные знаки."
        ),
        "hotwords": "ChatGPT, OpenAI, React, TypeScript, Next.js",
        "language_detection_segments": 3,
    },
    "live_preview": {
        "enabled": True,
        "model_size": "tiny",
        "language_mode": "ru",
        "device": "auto",
        "compute_type": "float32",
        "beam_size": 2,
        "best_of": 2,
        "condition_on_previous_text": False,
        "without_timestamps": True,
        "vad_filter": True,
        "update_interval_seconds": 0.75,
        "min_audio_seconds": 0.9,
        "max_preview_window_seconds": 10.0,
    },
    "text_postprocess": {
        "auto_copy": True,
        "auto_paste": True,
        "custom_replacements": {},
    },
    "overlay": {
        "enabled": True,
        "size": 34,
        "margin": 12,
        "idle_alpha": 0.65,
        "recording_alpha": 0.95,
        "transcribing_alpha": 0.75,
        "idle_color": "#FFFFFF",
        "recording_color": "#2BFF59",
        "transcribing_color": "#FFFFFF",
    },
    "groq": DEFAULT_GROQ,
}


class ConfigError(RuntimeError):
    """Raised when the application configuration is invalid."""


@dataclass(frozen=True, slots=True)
class PathsConfig:
    root_dir: Path
    config_file: Path
    logs_dir: Path
    data_dir: Path
    history_file: Path
    temp_dir: Path
    models_dir: Path


@dataclass(frozen=True, slots=True)
class TrayConfig:
    tooltip: str
    startup_notification: bool


@dataclass(frozen=True, slots=True)
class NotificationsConfig:
    enabled: bool
    backend: str


@dataclass(frozen=True, slots=True)
class HotkeyConfig:
    combination: str
    tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AudioConfig:
    sample_rate: int
    channels: int
    block_frames: int
    max_record_seconds: int
    min_duration_seconds: float
    stale_temp_file_age_hours: int
    file_prefix: str


@dataclass(frozen=True, slots=True)
class TranscriptionConfig:
    model_size: str
    language_mode: str
    device: str
    compute_type: str
    cpu_threads: int
    beam_size: int
    best_of: int
    condition_on_previous_text: bool
    without_timestamps: bool
    vad_filter: bool
    initial_prompt: str
    hotwords: str
    language_detection_segments: int


@dataclass(frozen=True, slots=True)
class LivePreviewConfig:
    enabled: bool
    model_size: str
    language_mode: str
    device: str
    compute_type: str
    beam_size: int
    best_of: int
    condition_on_previous_text: bool
    without_timestamps: bool
    vad_filter: bool
    update_interval_seconds: float
    min_audio_seconds: float
    max_preview_window_seconds: float


@dataclass(frozen=True, slots=True)
class TextPostprocessConfig:
    auto_copy: bool
    auto_paste: bool
    custom_replacements: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class OverlayUiConfig:
    enabled: bool
    size: int
    margin: int
    idle_alpha: float
    recording_alpha: float
    transcribing_alpha: float
    idle_color: str
    recording_color: str
    transcribing_color: str


@dataclass(frozen=True, slots=True)
class GroqConfig:
    enabled: bool
    api_key: str
    model: str


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_name: str
    log_level: str
    history_limit: int
    paths: PathsConfig
    tray: TrayConfig
    notifications: NotificationsConfig
    hotkey: HotkeyConfig
    audio: AudioConfig
    transcription: TranscriptionConfig
    live_preview: LivePreviewConfig
    text_postprocess: TextPostprocessConfig
    overlay: OverlayUiConfig
    groq: GroqConfig

    @property
    def app_slug(self) -> str:
        return self.app_name.strip().lower().replace(" ", "_")


def _get_root_dir() -> Path:
    """Return project root — works both in dev and when frozen by PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def load_config(config_path: Path | None = None) -> AppConfig:
    root_dir = _get_root_dir()
    resolved_config_path = config_path or root_dir / "config.json"
    raw_config = _read_json_object(resolved_config_path) if resolved_config_path.exists() else {}
    merged_config = _merge_dicts(DEFAULT_CONFIG, raw_config)
    _normalize_legacy_values(merged_config, raw_config)

    if not resolved_config_path.exists():
        _write_json(resolved_config_path, merged_config)

    return _build_config(
        root_dir=root_dir,
        config_path=resolved_config_path,
        merged_config=merged_config,
    )


def ensure_runtime_paths(config: AppConfig) -> None:
    config.paths.logs_dir.mkdir(parents=True, exist_ok=True)
    config.paths.data_dir.mkdir(parents=True, exist_ok=True)
    config.paths.temp_dir.mkdir(parents=True, exist_ok=True)
    config.paths.models_dir.mkdir(parents=True, exist_ok=True)
    _ensure_history_file(config.paths.history_file)


def _build_config(root_dir: Path, config_path: Path, merged_config: dict[str, Any]) -> AppConfig:
    paths = _as_object(merged_config["paths"], "paths")
    tray = _as_object(merged_config["tray"], "tray")
    notifications = _as_object(merged_config["notifications"], "notifications")
    hotkey = _as_object(merged_config["hotkey"], "hotkey")
    audio = _as_object(merged_config["audio"], "audio")
    transcription = _as_object(merged_config["transcription"], "transcription")
    live_preview = _as_object(merged_config["live_preview"], "live_preview")
    text_postprocess = _as_object(merged_config["text_postprocess"], "text_postprocess")
    overlay = _as_object(merged_config["overlay"], "overlay")
    groq_section = _as_object(_merge_dicts(DEFAULT_GROQ, merged_config.get("groq", {})), "groq")

    history_path = _resolve_path(root_dir, _as_non_empty_string(paths["history_file"], "paths.history_file"))
    hotkey_combination = _as_non_empty_string(hotkey["combination"], "hotkey.combination")

    return AppConfig(
        app_name=_as_non_empty_string(merged_config["app_name"], "app_name"),
        log_level=_parse_log_level(merged_config["log_level"]),
        history_limit=_as_positive_int(merged_config["history_limit"], "history_limit"),
        paths=PathsConfig(
            root_dir=root_dir,
            config_file=config_path,
            logs_dir=_resolve_path(root_dir, _as_non_empty_string(paths["logs_dir"], "paths.logs_dir")),
            data_dir=history_path.parent,
            history_file=history_path,
            temp_dir=_resolve_path(root_dir, _as_non_empty_string(paths["temp_dir"], "paths.temp_dir")),
            models_dir=_resolve_path(
                root_dir,
                _as_non_empty_string(paths["models_dir"], "paths.models_dir"),
            ),
        ),
        tray=TrayConfig(
            tooltip=_as_non_empty_string(tray["tooltip"], "tray.tooltip"),
            startup_notification=_as_bool(tray["startup_notification"], "tray.startup_notification"),
        ),
        notifications=NotificationsConfig(
            enabled=_as_bool(notifications["enabled"], "notifications.enabled"),
            backend=_parse_notification_backend(notifications["backend"]),
        ),
        hotkey=HotkeyConfig(
            combination=hotkey_combination,
            tokens=_parse_hotkey_combination(hotkey_combination),
        ),
        audio=AudioConfig(
            sample_rate=_as_positive_int(audio["sample_rate"], "audio.sample_rate"),
            channels=_parse_audio_channels(audio["channels"]),
            block_frames=_as_positive_int(audio["block_frames"], "audio.block_frames"),
            max_record_seconds=_as_positive_int(audio["max_record_seconds"], "audio.max_record_seconds"),
            min_duration_seconds=_as_non_negative_float(
                audio["min_duration_seconds"],
                "audio.min_duration_seconds",
            ),
            stale_temp_file_age_hours=_as_non_negative_int(
                audio["stale_temp_file_age_hours"],
                "audio.stale_temp_file_age_hours",
            ),
            file_prefix=_as_non_empty_string(audio["file_prefix"], "audio.file_prefix"),
        ),
        transcription=TranscriptionConfig(
            model_size=_parse_model_size(transcription["model_size"], "transcription.model_size"),
            language_mode=_parse_language_mode(transcription["language_mode"], "transcription.language_mode"),
            device=_as_non_empty_string(transcription["device"], "transcription.device"),
            compute_type=_as_non_empty_string(transcription["compute_type"], "transcription.compute_type"),
            cpu_threads=_as_non_negative_int(transcription["cpu_threads"], "transcription.cpu_threads"),
            beam_size=_as_positive_int(transcription["beam_size"], "transcription.beam_size"),
            best_of=_as_positive_int(transcription["best_of"], "transcription.best_of"),
            condition_on_previous_text=_as_bool(
                transcription["condition_on_previous_text"],
                "transcription.condition_on_previous_text",
            ),
            without_timestamps=_as_bool(
                transcription["without_timestamps"],
                "transcription.without_timestamps",
            ),
            vad_filter=_as_bool(transcription["vad_filter"], "transcription.vad_filter"),
            initial_prompt=_as_string(transcription["initial_prompt"], "transcription.initial_prompt"),
            hotwords=_as_string(transcription["hotwords"], "transcription.hotwords"),
            language_detection_segments=_as_positive_int(
                transcription["language_detection_segments"],
                "transcription.language_detection_segments",
            ),
        ),
        live_preview=LivePreviewConfig(
            enabled=_as_bool(live_preview["enabled"], "live_preview.enabled"),
            model_size=_parse_model_size(live_preview["model_size"], "live_preview.model_size"),
            language_mode=_parse_language_mode(live_preview["language_mode"], "live_preview.language_mode"),
            device=_as_non_empty_string(live_preview["device"], "live_preview.device"),
            compute_type=_as_non_empty_string(live_preview["compute_type"], "live_preview.compute_type"),
            beam_size=_as_positive_int(live_preview["beam_size"], "live_preview.beam_size"),
            best_of=_as_positive_int(live_preview["best_of"], "live_preview.best_of"),
            condition_on_previous_text=_as_bool(
                live_preview["condition_on_previous_text"],
                "live_preview.condition_on_previous_text",
            ),
            without_timestamps=_as_bool(
                live_preview["without_timestamps"],
                "live_preview.without_timestamps",
            ),
            vad_filter=_as_bool(live_preview["vad_filter"], "live_preview.vad_filter"),
            update_interval_seconds=_as_positive_float(
                live_preview["update_interval_seconds"],
                "live_preview.update_interval_seconds",
            ),
            min_audio_seconds=_as_positive_float(
                live_preview["min_audio_seconds"],
                "live_preview.min_audio_seconds",
            ),
            max_preview_window_seconds=_as_positive_float(
                live_preview["max_preview_window_seconds"],
                "live_preview.max_preview_window_seconds",
            ),
        ),
        text_postprocess=TextPostprocessConfig(
            auto_copy=_as_bool(text_postprocess["auto_copy"], "text_postprocess.auto_copy"),
            auto_paste=_as_bool(text_postprocess["auto_paste"], "text_postprocess.auto_paste"),
            custom_replacements=_parse_custom_replacements(text_postprocess["custom_replacements"]),
        ),
        overlay=OverlayUiConfig(
            enabled=_as_bool(overlay["enabled"], "overlay.enabled"),
            size=_as_positive_int(overlay["size"], "overlay.size"),
            margin=_as_non_negative_int(overlay["margin"], "overlay.margin"),
            idle_alpha=_as_unit_float(overlay["idle_alpha"], "overlay.idle_alpha"),
            recording_alpha=_as_unit_float(overlay["recording_alpha"], "overlay.recording_alpha"),
            transcribing_alpha=_as_unit_float(overlay["transcribing_alpha"], "overlay.transcribing_alpha"),
            idle_color=_as_hex_color(overlay["idle_color"], "overlay.idle_color"),
            recording_color=_as_hex_color(overlay["recording_color"], "overlay.recording_color"),
            transcribing_color=_as_hex_color(overlay["transcribing_color"], "overlay.transcribing_color"),
        ),
        groq=GroqConfig(
            enabled=_as_bool(groq_section["enabled"], "groq.enabled"),
            api_key=_as_string(groq_section["api_key"], "groq.api_key")
                or os.environ.get("GROQ_API_KEY", ""),
            model=_as_non_empty_string(groq_section["model"], "groq.model"),
        ),
    )


def _ensure_history_file(history_path: Path) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    default_payload = {"entries": []}

    if not history_path.exists():
        _write_json(history_path, default_payload)
        return

    try:
        with history_path.open("r", encoding="utf-8") as handle:
            existing_payload = json.load(handle)
    except (json.JSONDecodeError, OSError):
        _backup_and_reset(history_path, default_payload)
        return

    if isinstance(existing_payload, list):
        _write_json(history_path, {"entries": existing_payload})
        return

    if not isinstance(existing_payload, dict) or not isinstance(existing_payload.get("entries"), list):
        _backup_and_reset(history_path, default_payload)


def _backup_and_reset(history_path: Path, payload: dict[str, Any]) -> None:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = history_path.with_name(f"{history_path.stem}.backup-{timestamp}{history_path.suffix}")
    try:
        history_path.replace(backup_path)
    except OSError:
        pass
    _write_json(history_path, payload)


def _normalize_legacy_values(merged_config: dict[str, Any], raw_config: dict[str, Any]) -> None:
    raw_audio = raw_config.get("audio")
    merged_audio = merged_config.get("audio")

    if isinstance(raw_audio, dict) and isinstance(merged_audio, dict):
        if "max_record_seconds" not in raw_audio and "max_duration_seconds" in raw_audio:
            merged_audio["max_record_seconds"] = raw_audio["max_duration_seconds"]

    raw_transcription = raw_config.get("transcription")
    merged_transcription = merged_config.get("transcription")
    raw_live_preview = raw_config.get("live_preview")
    merged_live_preview = merged_config.get("live_preview")

    if isinstance(raw_transcription, dict) and isinstance(merged_transcription, dict):
        if "model_size" in raw_transcription and not isinstance(raw_live_preview, dict):
            if isinstance(merged_live_preview, dict):
                merged_live_preview["language_mode"] = merged_transcription.get("language_mode", "ru")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in configuration file: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"Unable to read configuration file: {path}") from exc

    if not isinstance(payload, dict):
        raise ConfigError(f"Configuration file must contain a JSON object: {path}")

    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _resolve_path(root_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else root_dir / path


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)

    for key, value in override.items():
        if key not in merged:
            merged[key] = value
            continue

        if isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(merged[key], value)
            continue

        merged[key] = value

    return merged


def _as_object(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"Configuration field '{field_name}' must be an object.")
    return value


def _as_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Configuration field '{field_name}' must be a non-empty string.")
    return value.strip()


def _as_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"Configuration field '{field_name}' must be a string.")
    return value.strip()


def _as_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"Configuration field '{field_name}' must be a boolean.")
    return value


def _as_positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ConfigError(f"Configuration field '{field_name}' must be a positive integer.")
    return value


def _as_non_negative_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConfigError(f"Configuration field '{field_name}' must be a non-negative integer.")
    return value


def _as_non_negative_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0:
        raise ConfigError(f"Configuration field '{field_name}' must be a non-negative number.")
    return float(value)


def _as_positive_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise ConfigError(f"Configuration field '{field_name}' must be a positive number.")
    return float(value)


def _as_unit_float(value: Any, field_name: str) -> float:
    numeric = _as_positive_float(value, field_name)
    if numeric > 1.0:
        raise ConfigError(f"Configuration field '{field_name}' must be less than or equal to 1.0.")
    return numeric


def _parse_log_level(value: Any) -> str:
    normalized = _as_non_empty_string(value, "log_level").upper()
    if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError(
            "Configuration field 'log_level' must be DEBUG, INFO, WARNING, ERROR, or CRITICAL."
        )
    return normalized


def _parse_notification_backend(value: Any) -> str:
    normalized = _as_non_empty_string(value, "notifications.backend").lower()
    if normalized not in {"log"}:
        raise ConfigError("Configuration field 'notifications.backend' must be 'log'.")
    return normalized


def _parse_audio_channels(value: Any) -> int:
    channels = _as_positive_int(value, "audio.channels")
    if channels != 1:
        raise ConfigError("Configuration field 'audio.channels' must be 1 for this MVP.")
    return channels


def _parse_model_size(value: Any, field_name: str) -> str:
    return _as_non_empty_string(value, field_name)


def _parse_language_mode(value: Any, field_name: str) -> str:
    normalized = _as_non_empty_string(value, field_name).lower()
    if normalized not in {"auto", "ru", "en"}:
        raise ConfigError(f"Configuration field '{field_name}' must be 'auto', 'ru', or 'en'.")
    return normalized


def _parse_custom_replacements(value: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        raise ConfigError(
            "Configuration field 'text_postprocess.custom_replacements' must be an object."
        )

    normalized_items: list[tuple[str, str]] = []

    for raw_source, raw_target in value.items():
        if not isinstance(raw_source, str) or not raw_source.strip():
            raise ConfigError(
                "Replacement keys in 'text_postprocess.custom_replacements' must be non-empty strings."
            )

        if not isinstance(raw_target, str) or not raw_target.strip():
            raise ConfigError(
                "Replacement values in 'text_postprocess.custom_replacements' must be non-empty strings."
            )

        normalized_items.append((raw_source.strip(), raw_target.strip()))

    normalized_items.sort(key=lambda item: len(item[0]), reverse=True)
    return tuple(normalized_items)


def _as_hex_color(value: Any, field_name: str) -> str:
    raw = _as_non_empty_string(value, field_name)
    if len(raw) != 7 or not raw.startswith("#"):
        raise ConfigError(f"Configuration field '{field_name}' must look like #RRGGBB.")
    hex_part = raw[1:]
    if any(ch not in "0123456789abcdefABCDEF" for ch in hex_part):
        raise ConfigError(f"Configuration field '{field_name}' must look like #RRGGBB.")
    return raw.upper()


def _parse_hotkey_combination(combination: str) -> tuple[str, ...]:
    token_map = {
        "ctrl": "ctrl",
        "control": "ctrl",
        "alt": "alt",
        "shift": "shift",
        "win": "win",
        "windows": "win",
        "super": "win",
        "cmd": "win",
        "left_ctrl": "left_ctrl",
        "leftcontrol": "left_ctrl",
        "lctrl": "left_ctrl",
        "right_ctrl": "right_ctrl",
        "rctrl": "right_ctrl",
        "left_alt": "left_alt",
        "lalt": "left_alt",
        "right_alt": "right_alt",
        "ralt": "right_alt",
        "left_shift": "left_shift",
        "lshift": "left_shift",
        "right_shift": "right_shift",
        "rshift": "right_shift",
        "left_win": "left_win",
        "left_windows": "left_win",
        "lwin": "left_win",
        "left_cmd": "left_win",
        "right_win": "right_win",
        "right_windows": "right_win",
        "rwin": "right_win",
        "right_cmd": "right_win",
    }
    supported_tokens = {
        "ctrl",
        "alt",
        "shift",
        "win",
        "left_ctrl",
        "right_ctrl",
        "left_alt",
        "right_alt",
        "left_shift",
        "right_shift",
        "left_win",
        "right_win",
    }

    raw_tokens = [part.strip().lower().replace(" ", "_") for part in combination.split("+")]
    filtered_tokens = [token for token in raw_tokens if token]

    if not filtered_tokens:
        raise ConfigError("Configuration field 'hotkey.combination' must not be empty.")

    normalized_tokens: list[str] = []

    for token in filtered_tokens:
        normalized_token = token_map.get(token, token)

        if normalized_token in normalized_tokens:
            continue

        if normalized_token in supported_tokens:
            normalized_tokens.append(normalized_token)
            continue

        if len(normalized_token) == 1 and normalized_token.isprintable():
            normalized_tokens.append(normalized_token)
            continue

        raise ConfigError(
            f"Unsupported hotkey token '{token}' in configuration field 'hotkey.combination'."
        )

    return tuple(normalized_tokens)
