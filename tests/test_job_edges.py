"""Unusual cleanup and shutdown failures must not strand uploaded files or admission."""

import asyncio
import os
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from ai_song_detection.detector import AnalysisCancelled, AudioError, Detector, load_audio
from ai_song_detection.jobs import JobStore


async def wait_for(store, identifier, status):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        record = store.get(identifier)
        if record["status"] == status:
            return record
        await asyncio.sleep(0.01)
    raise AssertionError(f"Expected {status}; got {store.get(identifier)}")


def upload(store, directory=None):
    assert store.reserve()
    directory = directory or tempfile.TemporaryDirectory(prefix="job-edge-")
    path = Path(directory.name) / "song.wav"
    path.write_bytes(b"test")
    return store.submit(directory, path, "song.wav", 0, 300)["id"], path


def test_cleanup_failure_releases_admission_without_crashing_worker_and_retries():
    class Detector:
        def analyze(self, path, **kwargs):
            return {"filename": "song.wav"}

    class LockedDirectory:
        def __init__(self):
            self.directory = tempfile.TemporaryDirectory(prefix="job-locked-")
            self.name = self.directory.name
            self.locked = True

        def cleanup(self):
            if self.locked:
                raise PermissionError("File temporarily locked")
            self.directory.cleanup()

    async def scenario():
        directory = LockedDirectory()
        store = JobStore(Detector(), asyncio.Lock())
        try:
            identifier, path = upload(store, directory)
            record = await wait_for(store, identifier, "failed")
            assert record["error"]["code"] == "cleanup_failed"
            assert store.pending == 0
            assert not store.worker.done()
            assert path.exists()
            assert store.reserve() is False
            directory.locked = False
            second, next_path = upload(store)
            await wait_for(store, second, "completed")
            assert not path.exists()
            assert not next_path.exists()
            assert store.pending == 0
            assert not store.cleanup_pending
        finally:
            directory.locked = False
            await store.close()
            directory.cleanup()

    asyncio.run(scenario())


def test_cancel_while_waiting_for_legacy_lock_does_not_start_analysis_or_delete_early():
    calls = []

    class Detector:
        def analyze(self, path, **kwargs):
            calls.append(path)
            return {}

    async def scenario():
        lock = asyncio.Lock()
        await lock.acquire()
        store = JobStore(Detector(), lock)
        try:
            identifier, path = upload(store)
            await wait_for(store, identifier, "running")
            assert store.cancel(identifier)["status"] == "cancelling"
            assert store.pending == 1
            assert path.exists()
            lock.release()
            await wait_for(store, identifier, "cancelled")
            assert not path.exists()
            assert store.pending == 0
            assert calls == []
        finally:
            if lock.locked():
                lock.release()
            await store.close()

    asyncio.run(scenario())


def test_close_waits_for_cooperative_running_cancel_and_discards_waiting_job():
    entered = threading.Event()
    exited = threading.Event()
    calls = []

    class Detector:
        def analyze(self, path, cancel_event, **kwargs):
            calls.append(path)
            entered.set()
            try:
                assert cancel_event.wait(5)
                # The upload must remain until this worker has stopped reading it.
                assert path.exists()
                raise AnalysisCancelled()
            finally:
                exited.set()

    async def scenario():
        store = JobStore(Detector(), asyncio.Lock())
        first, first_path = upload(store)
        assert await asyncio.to_thread(entered.wait, 5)
        second, second_path = upload(store)
        await store.close()
        assert exited.is_set()
        assert store.get(first)["status"] == "cancelled"
        assert store.get(second)["status"] == "cancelled"
        assert not first_path.exists()
        assert not second_path.exists()
        assert store.pending == 0
        assert store.reserve() is False
        assert calls == [first_path]

    asyncio.run(scenario())


@pytest.mark.skipif(os.name == "nt", reason="Windows does not have POSIX FIFOs")
def test_cli_fifo_input_is_rejected_before_opening_or_hashing(tmp_path, monkeypatch):
    pipe = tmp_path / "song.wav"
    os.mkfifo(pipe)

    def reject_open(*args, **kwargs):
        pytest.fail("A nonregular audio input must never be opened")

    monkeypatch.setattr(Path, "open", reject_open)
    detector = Detector.__new__(Detector)
    with pytest.raises(AudioError):
        detector.analyze(pipe)


def test_extreme_finite_window_start_is_an_audio_error_instead_of_overflow(tmp_path):
    audio = tmp_path / "song.wav"
    sf.write(audio, np.zeros(16000 * 12, np.float32), 16000)
    with pytest.raises(AudioError) as error:
        load_audio(audio, start_seconds=1e308)
    assert error.value.code == "audio_too_short"
