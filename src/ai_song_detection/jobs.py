"""Bounded in-memory FIFO jobs; uploaded bytes live only until work ends."""

import asyncio
import logging
import secrets
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi.concurrency import run_in_threadpool

from .detector import AnalysisCancelled, AudioError

logger = logging.getLogger(__name__)
MAX_PENDING_JOBS = 9  # One running and at most eight waiting/uploading.
MAX_REPORTS = 100
REPORT_TTL_SECONDS = 3600
TERMINAL = {"completed", "failed", "cancelled"}


def now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    record: dict
    directory: tempfile.TemporaryDirectory
    path: Path
    filename: str
    start: float
    duration: float
    cancel: threading.Event = field(default_factory=threading.Event)
    touched: float = field(default_factory=time.monotonic)


class JobStore:
    def __init__(self, detector, analysis_lock):
        self.detector = detector
        self.analysis_lock = analysis_lock
        self.jobs: dict[str, Job] = {}
        self.queue = deque()
        self.wake = asyncio.Event()
        self.pending = 0
        self.closing = False
        self.cleanup_pending = []
        self.worker = asyncio.create_task(self.run())

    def prune(self):
        terminal = [j for j in self.jobs.values() if j.record["status"] in TERMINAL]
        terminal.sort(key=lambda j: j.touched)
        for i, job in enumerate(terminal):
            if (
                time.monotonic() - job.touched > REPORT_TTL_SECONDS
                or i < len(terminal) - MAX_REPORTS
            ):
                self.jobs.pop(job.record["id"], None)

    def retry_cleanup(self):
        remaining = []
        for directory in self.cleanup_pending:
            try:
                directory.cleanup()
            except OSError:
                remaining.append(directory)
        self.cleanup_pending = remaining

    def reserve(self):
        self.prune()
        self.retry_cleanup()
        if self.cleanup_pending or self.closing or self.pending >= MAX_PENDING_JOBS:
            return False
        self.pending += 1
        return True

    def submit(self, directory, path, filename, start, duration):
        identifier = secrets.token_urlsafe(24)
        timestamp = now()
        job = Job(
            {
                "id": identifier,
                "status": "queued",
                "stage": "queued",
                "created_at": timestamp,
                "updated_at": timestamp,
                "result": None,
                "error": None,
            },
            directory,
            path,
            filename,
            start,
            duration,
        )
        self.jobs[identifier] = job
        self.queue.append(job)
        self.wake.set()
        return dict(job.record)

    def get(self, identifier):
        self.prune()
        job = self.jobs.get(identifier)
        return dict(job.record) if job else None

    def update(self, job, **values):
        job.record.update(values, updated_at=now())
        job.touched = time.monotonic()

    def finish(self, job, status, **values):
        # This is called only after the analysis thread has returned, or before it starts.
        try:
            job.directory.cleanup()
        except OSError:
            logger.exception(
                "Could not remove a job upload; admission paused until cleanup succeeds"
            )
            self.cleanup_pending.append(job.directory)
            status = "failed"
            values = {
                "result": None,
                "error": {
                    "code": "cleanup_failed",
                    "message": "Temporary upload cleanup failed. Check disk permissions and restart the service.",
                },
            }
        finally:
            self.update(job, status=status, **values)
            self.pending -= 1
            self.prune()

    def cancel(self, identifier):
        job = self.jobs.get(identifier)
        if job is None:
            return None
        if job.record["status"] not in TERMINAL:
            job.cancel.set()
            if job.record["status"] == "queued":
                self.queue.remove(job)
                self.finish(job, "cancelled")
            else:
                self.update(job, status="cancelling")
        return dict(job.record)

    async def run(self):
        loop = asyncio.get_running_loop()
        while True:
            await self.wake.wait()
            if not self.queue:
                self.wake.clear()
                if self.closing:
                    return
                continue
            job = self.queue.popleft()
            # Set running before waiting for the legacy endpoint's shared analysis lock.
            self.update(job, status="running")

            def progress(stage, current=job):
                def apply():
                    if current.record["status"] not in TERMINAL:
                        self.update(current, stage=stage)

                loop.call_soon_threadsafe(apply)

            try:
                async with self.analysis_lock:
                    if job.cancel.is_set():
                        raise AnalysisCancelled()
                    result = await run_in_threadpool(
                        self.detector.analyze,
                        job.path,
                        filename=job.filename,
                        start_seconds=job.start,
                        duration_seconds=job.duration,
                        cancel_event=job.cancel,
                        progress=progress,
                    )
                if job.cancel.is_set():
                    self.finish(job, "cancelled")
                else:
                    self.finish(job, "completed", result=result, stage="complete")
            except AnalysisCancelled:
                self.finish(job, "cancelled")
            except AudioError as exc:
                self.finish(job, "failed", error={"code": exc.code, "message": str(exc)})
            except Exception:
                logger.exception("Queued analysis failed")
                self.finish(
                    job,
                    "failed",
                    error={
                        "code": "analysis_failed",
                        "message": "Audio analysis failed. Please try another file.",
                    },
                )

    async def close(self):
        self.closing = True
        for job in list(self.jobs.values()):
            if job.record["status"] not in TERMINAL:
                self.cancel(job.record["id"])
        self.wake.set()
        await self.worker
        self.retry_cleanup()
