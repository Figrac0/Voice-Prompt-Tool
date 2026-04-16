from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes


class ClipboardServiceError(RuntimeError):
    """Raised when clipboard access fails."""


class ClipboardService:
    _cf_unicode_text = 13
    _gmem_movable = 0x0002
    _open_attempts = 10
    _open_retry_delay_seconds = 0.05

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._last_copied_text: str | None = None

        if sys.platform != "win32":
            raise ClipboardServiceError("ClipboardService supports Windows only.")

        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure_api()

    @property
    def last_copied_text(self) -> str | None:
        return self._last_copied_text

    def copy_text(self, text: str) -> None:
        normalized_text = text.replace("\r\n", "\n").replace("\r", "\n").strip()

        if not normalized_text:
            raise ClipboardServiceError("Clipboard text is empty.")

        clipboard_text = normalized_text.replace("\n", "\r\n")
        memory_handle: ctypes.c_void_p | None = None

        self._open_clipboard()

        try:
            if not self._user32.EmptyClipboard():
                raise self._build_os_error("Unable to empty Windows clipboard.")

            buffer = ctypes.create_unicode_buffer(clipboard_text)
            size_bytes = ctypes.sizeof(buffer)
            memory_handle = ctypes.c_void_p(self._kernel32.GlobalAlloc(self._gmem_movable, size_bytes))

            if not memory_handle.value:
                raise self._build_os_error("Unable to allocate clipboard memory.")

            locked_pointer = ctypes.c_void_p(self._kernel32.GlobalLock(memory_handle))
            if not locked_pointer.value:
                raise self._build_os_error("Unable to lock clipboard memory.")

            try:
                ctypes.memmove(locked_pointer.value, ctypes.addressof(buffer), size_bytes)
            finally:
                self._kernel32.GlobalUnlock(memory_handle)

            if not self._user32.SetClipboardData(self._cf_unicode_text, memory_handle):
                raise self._build_os_error("Unable to set clipboard data.")

            memory_handle = None
            self._last_copied_text = normalized_text
            self._logger.info("Clipboard copy succeeded | characters=%s", len(normalized_text))
        except Exception:
            self._logger.exception("Clipboard copy failed.")
            raise
        finally:
            self._user32.CloseClipboard()

            if memory_handle is not None and memory_handle.value:
                self._kernel32.GlobalFree(memory_handle)

    def clear(self) -> None:
        self._open_clipboard()
        try:
            if not self._user32.EmptyClipboard():
                raise self._build_os_error("Unable to empty Windows clipboard.")
            self._last_copied_text = None
            self._logger.info("Clipboard cleared.")
        except Exception:
            self._logger.exception("Clipboard clear failed.")
            raise
        finally:
            self._user32.CloseClipboard()

    def _open_clipboard(self) -> None:
        for _ in range(self._open_attempts):
            if self._user32.OpenClipboard(None):
                return
            time.sleep(self._open_retry_delay_seconds)

        raise self._build_os_error("Unable to open Windows clipboard.")

    def _configure_api(self) -> None:
        self._user32.OpenClipboard.argtypes = [wintypes.HWND]
        self._user32.OpenClipboard.restype = wintypes.BOOL
        self._user32.CloseClipboard.argtypes = []
        self._user32.CloseClipboard.restype = wintypes.BOOL
        self._user32.EmptyClipboard.argtypes = []
        self._user32.EmptyClipboard.restype = wintypes.BOOL
        self._user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
        self._user32.SetClipboardData.restype = ctypes.c_void_p

        self._kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        self._kernel32.GlobalAlloc.restype = ctypes.c_void_p
        self._kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        self._kernel32.GlobalLock.restype = ctypes.c_void_p
        self._kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        self._kernel32.GlobalUnlock.restype = wintypes.BOOL
        self._kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.GlobalFree.restype = ctypes.c_void_p

    @staticmethod
    def _build_os_error(message: str) -> ClipboardServiceError:
        error_code = ctypes.get_last_error()
        error_text = ctypes.FormatError(error_code).strip() if error_code else "Unknown error"
        return ClipboardServiceError(f"{message} [WinError {error_code}] {error_text}")
