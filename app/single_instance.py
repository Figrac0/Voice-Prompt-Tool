from __future__ import annotations

import logging
import msvcrt
import os
from pathlib import Path
from typing import TextIO


class SingleInstanceError(RuntimeError):
    """Raised when another Voice Prompt Tool instance is already running."""


class SingleInstanceGuard:
    def __init__(self, lock_file: Path, logger: logging.Logger) -> None:
        self._lock_file = lock_file
        self._logger = logger
        self._handle: TextIO | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            return

        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        handle = self._lock_file.open("a+", encoding="utf-8")

        try:
            handle.seek(0)
            handle.write("0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
        except OSError as exc:
            handle.close()
            raise SingleInstanceError(
                f"Another instance is already holding the lock file '{self._lock_file}'."
            ) from exc

        self._handle = handle
        self._logger.info("Single-instance lock acquired: %s", self._lock_file)

    def release(self) -> None:
        handle = self._handle
        self._handle = None

        if handle is None:
            return

        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            self._logger.exception("Unable to release single-instance lock: %s", self._lock_file)
        finally:
            handle.close()
            self._logger.info("Single-instance lock released: %s", self._lock_file)
