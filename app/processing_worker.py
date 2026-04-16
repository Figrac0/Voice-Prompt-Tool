from __future__ import annotations

import logging
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Callable


@dataclass(frozen=True, slots=True)
class ProcessingJob:
    audio_path: str
    recording_duration_seconds: float
    sequence_id: int = 0


@dataclass(frozen=True, slots=True)
class ProcessingOutcome:
    success: bool
    detail: str
    error: str | None = None


class BackgroundProcessingWorker:
    def __init__(
        self,
        logger: logging.Logger,
        processor: Callable[[ProcessingJob], ProcessingOutcome],
        on_job_finished: Callable[[ProcessingJob, ProcessingOutcome, int], None] | None = None,
    ) -> None:
        self._logger = logger
        self._processor = processor
        self._on_job_finished = on_job_finished
        self._queue: Queue[ProcessingJob] = Queue()
        self._stop_event = Event()
        self._lock = Lock()
        self._active_jobs = 0
        self._thread = Thread(
            target=self._worker_loop,
            daemon=True,
            name="voice-prompt-processing-worker",
        )

    @property
    def pending_count(self) -> int:
        with self._lock:
            return self._active_jobs + self._queue.qsize()

    def start(self) -> None:
        if self._thread.is_alive():
            return
        self._thread.start()
        self._logger.info("Background processing worker started.")

    def stop(self, timeout_seconds: float = 5.0) -> None:
        self._stop_event.set()

        if not self._thread.is_alive():
            return

        self._thread.join(timeout_seconds)
        if self._thread.is_alive():
            self._logger.warning("Background processing worker did not stop within timeout.")
        else:
            self._logger.info("Background processing worker stopped.")

    def enqueue(self, job: ProcessingJob) -> int:
        self._queue.put(job)
        pending = self.pending_count
        self._logger.info(
            "Processing job queued | pending=%s | audio=%s",
            pending,
            job.audio_path,
        )
        return pending

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job = self._queue.get(timeout=0.25)
            except Empty:
                continue

            with self._lock:
                self._active_jobs += 1

            try:
                outcome = self._processor(job)
            except Exception as exc:
                self._logger.exception("Unhandled background processing error.")
                outcome = ProcessingOutcome(
                    success=False,
                    detail="Background processing failed.",
                    error=str(exc),
                )
            finally:
                with self._lock:
                    self._active_jobs -= 1
                    remaining = self._active_jobs + self._queue.qsize()
                self._queue.task_done()

            if self._on_job_finished is not None:
                try:
                    self._on_job_finished(job, outcome, remaining)
                except Exception:
                    self._logger.exception("Background processing completion callback failed.")
