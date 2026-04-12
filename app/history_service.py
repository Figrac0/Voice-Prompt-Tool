from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock
from uuid import uuid4


class HistoryServiceError(RuntimeError):
    """Raised when local history storage fails."""


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    timestamp: str
    raw_text: str
    cleaned_text: str
    language_mode: str
    recording_duration_seconds: float


class HistoryService:
    def __init__(self, history_file: Path, limit: int, logger: logging.Logger) -> None:
        if limit <= 0:
            raise HistoryServiceError("History limit must be a positive integer.")

        self._history_file = history_file
        self._limit = limit
        self._logger = logger
        self._lock = RLock()
        self._last_entries: tuple[HistoryEntry, ...] = ()

    @property
    def last_entries(self) -> tuple[HistoryEntry, ...]:
        with self._lock:
            return self._last_entries

    def ensure_ready(self) -> tuple[HistoryEntry, ...]:
        with self._lock:
            entries = self._load_entries_locked()
            self._last_entries = entries
            return entries

    def append_entry(self, entry: HistoryEntry) -> HistoryEntry:
        with self._lock:
            entries = list(self._load_entries_locked())

            if entries and self._is_duplicate_entry(entries[-1], entry):
                self._last_entries = tuple(entries[-self._limit :])
                self._logger.warning(
                    "Duplicate history entry skipped | path=%s | text=%s",
                    self._history_file,
                    entry.cleaned_text,
                )
                return entries[-1]

            entries.append(entry)
            trimmed_entries = tuple(entries[-self._limit :])
            payload = {"entries": [asdict(item) for item in trimmed_entries]}
            self._write_payload_locked(payload)
            self._last_entries = trimmed_entries

        self._logger.info(
            "History entry saved | entries=%s | path=%s",
            len(trimmed_entries),
            self._history_file,
        )
        return entry

    def build_entry(
        self,
        raw_text: str,
        cleaned_text: str,
        language_mode: str,
        recording_duration_seconds: float,
    ) -> HistoryEntry:
        return HistoryEntry(
            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
            raw_text=raw_text,
            cleaned_text=cleaned_text,
            language_mode=language_mode,
            recording_duration_seconds=round(float(recording_duration_seconds), 3),
        )

    def _load_entries_locked(self) -> tuple[HistoryEntry, ...]:
        self._history_file.parent.mkdir(parents=True, exist_ok=True)

        if not self._history_file.exists():
            self._write_payload_locked({"entries": []})
            return ()

        try:
            with self._history_file.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            self._recover_corrupted_history_locked(exc)
            return ()

        entries_data = self._extract_entries(payload)
        entries = tuple(self._normalize_entries(entries_data))
        trimmed_entries = entries[-self._limit :]

        if payload != {"entries": [asdict(item) for item in trimmed_entries]}:
            self._write_payload_locked({"entries": [asdict(item) for item in trimmed_entries]})

        return trimmed_entries

    def _extract_entries(self, payload: object) -> list[object]:
        if isinstance(payload, dict) and isinstance(payload.get("entries"), list):
            return list(payload["entries"])
        if isinstance(payload, list):
            return list(payload)
        return []

    def _normalize_entries(self, entries_data: list[object]) -> list[HistoryEntry]:
        normalized_entries: list[HistoryEntry] = []

        for item in entries_data:
            if not isinstance(item, dict):
                continue

            timestamp = item.get("timestamp")
            raw_text = item.get("raw_text")
            cleaned_text = item.get("cleaned_text")
            language_mode = item.get("language_mode")
            recording_duration_seconds = item.get("recording_duration_seconds")

            if not isinstance(timestamp, str) or not timestamp.strip():
                continue
            if not isinstance(raw_text, str):
                continue
            if not isinstance(cleaned_text, str):
                continue
            if not isinstance(language_mode, str) or not language_mode.strip():
                continue
            if isinstance(recording_duration_seconds, bool) or not isinstance(
                recording_duration_seconds,
                (int, float),
            ):
                continue

            normalized_entries.append(
                HistoryEntry(
                    timestamp=timestamp.strip(),
                    raw_text=raw_text,
                    cleaned_text=cleaned_text,
                    language_mode=language_mode.strip(),
                    recording_duration_seconds=round(float(recording_duration_seconds), 3),
                )
            )

        return normalized_entries

    def _recover_corrupted_history_locked(self, exc: Exception) -> None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = self._history_file.with_name(
            f"{self._history_file.stem}.corrupt-{timestamp}{self._history_file.suffix}"
        )

        try:
            self._history_file.replace(backup_path)
        except OSError:
            self._logger.exception("Unable to backup corrupted history file: %s", self._history_file)

        self._logger.warning(
            "History file was corrupted and has been reset | path=%s | backup=%s | error=%s",
            self._history_file,
            backup_path,
            exc,
        )
        self._write_payload_locked({"entries": []})

    def _write_payload_locked(self, payload: dict[str, object]) -> None:
        temp_path = self._history_file.with_name(f"{self._history_file.name}.{uuid4().hex}.tmp")

        try:
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            temp_path.replace(self._history_file)
        except OSError as exc:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                self._logger.exception("Unable to remove temporary history file: %s", temp_path)
            raise HistoryServiceError(f"Unable to write history file '{self._history_file}'.") from exc

    @staticmethod
    def _is_duplicate_entry(previous: HistoryEntry, current: HistoryEntry) -> bool:
        if previous.raw_text != current.raw_text:
            return False
        if previous.cleaned_text != current.cleaned_text:
            return False
        if previous.language_mode != current.language_mode:
            return False
        if abs(previous.recording_duration_seconds - current.recording_duration_seconds) > 0.1:
            return False

        try:
            previous_timestamp = datetime.fromisoformat(previous.timestamp)
            current_timestamp = datetime.fromisoformat(current.timestamp)
        except ValueError:
            return True

        return abs((current_timestamp - previous_timestamp).total_seconds()) <= 10
