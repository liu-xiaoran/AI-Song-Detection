"""Verify upload boundaries, cleanup, and concurrency independently of model quality."""

import asyncio
import threading
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_song_detection import server
from ai_song_detection.detector import AudioError


class RecordingDetector:
    def __init__(self):
        self.paths = []

    def analyze(self, path, filename=None, **kwargs):
        self.paths.append(Path(path))
        assert path.exists()
        return {
            "filename": filename,
            "assessment": "uncertain",
            "ai_score": 0.5,
            "threshold": 0.5,
            "upstream_binary_threshold": 0.5,
            "decision_policy": {
                "id": "fakeprint-screening-v1",
                "version": 1,
                "human_below": 0.4,
                "ai_above": 0.6,
                "uncertain_inclusive": [0.4, 0.6],
                "validated": False,
            },
            "input_sha256": "test",
            "input_size_bytes": 4,
            "application_version": "test",
            "analyzed_at": "test",
            "report_id": "test",
            "analyzed_start_seconds": 0,
            "analyzed_end_seconds": 12,
            "requested_duration_seconds": 300,
            "audio_duration_seconds": 12,
            "analyzed_duration_seconds": 12,
            "truncated": False,
            "processing_time_ms": 10,
            "model": {
                "name": "test",
                "version": "test",
                "sha256": "test",
                "upstream_commit": "test",
            },
            "warnings": [],
        }


@pytest.fixture
def client(monkeypatch):
    detector = RecordingDetector()
    monkeypatch.setattr(server, "Detector", lambda: detector)
    with TestClient(server.app) as test_client:
        yield test_client, detector


def test_page_health_and_openapi(client):
    api, _ = client
    page = api.get("/")
    assert page.status_code == 200
    assert "AI Song Detection" in page.text
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert api.get("/static/app.js").status_code == 200
    assert api.get("/health").json()["model_loaded"] is True
    schema = api.get("/openapi.json").json()
    body = schema["paths"]["/api/v1/detect"]["post"]["requestBody"]
    assert body["content"]["multipart/form-data"]["schema"]["required"] == ["file"]


def test_api_docs_use_local_assets(client):
    api, _ = client
    docs = api.get("/docs")
    assert docs.status_code == 200
    assert "/static/api-docs.js" in docs.text
    assert 'src="https://' not in docs.text
    assert api.get("/static/api-docs.js").status_code == 200


def test_health_identifies_the_app_without_disclosing_control_token(client):
    api, _ = client
    server.app.state.control_token = "private-control-token"
    health = api.get("/health")
    assert health.json()["app_id"] == "ai-song-detection"
    assert "instance_id" in health.json()
    assert "private-control-token" not in health.text
    assert health.headers["cache-control"] == "no-store"


def test_shutdown_is_disabled_for_unmanaged_service(client):
    api, _ = client
    assert api.post("/_control/stop").status_code == 404


def test_managed_shutdown_requires_private_token_and_no_browser_origin(client):
    calls = []
    server.app.state.control_token = "test-only-secret"
    server.app.state.request_shutdown = lambda: calls.append("stopping")

    async def scenario():
        transport = httpx.ASGITransport(app=server.app, client=("127.0.0.1", 12345))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
            assert (await api.post("/_control/stop")).status_code == 403
            headers = {"X-AI-Song-Control": "test-only-secret", "origin": "http://testserver"}
            assert (await api.post("/_control/stop", headers=headers)).status_code == 403
            assert calls == []
            response = await api.post(
                "/_control/stop", headers={"X-AI-Song-Control": "test-only-secret"}
            )
            assert response.status_code == 202
            assert response.json() == {"status": "stopping"}
            assert calls == ["stopping"]

    try:
        asyncio.run(scenario())
    finally:
        del server.app.state.request_shutdown


def test_success_sanitizes_filename_and_removes_temporary_file(client):
    api, detector = client
    response = api.post("/api/v1/detect", files={"file": ("../../song.wav", b"test", "audio/wav")})
    assert response.status_code == 200
    assert response.json()["filename"] == "song.wav"
    assert len(detector.paths) == 1
    assert not detector.paths[0].exists()
    assert not detector.paths[0].parent.exists()


@pytest.mark.parametrize(
    "files,status,code",
    [
        ({"file": ("file.txt", b"text")}, 415, "unsupported_format"),
        ({"file": ("file.wav", b"")}, 422, "empty_file"),
        ({"wrong": ("file.wav", b"data")}, 422, "missing_file"),
    ],
)
def test_rejected_uploads_never_reach_detector(client, files, status, code):
    api, detector = client
    result = api.post("/api/v1/detect", files=files)
    assert result.status_code == status
    assert result.json()["detail"]["code"] == code
    assert detector.paths == []
    assert not server.app.state.active_request


def test_file_size_limits_include_requests_without_content_length(client, monkeypatch):
    api, detector = client
    monkeypatch.setattr(server, "MAX_UPLOAD_BYTES", 4)
    monkeypatch.setattr(server, "MAX_REQUEST_BYTES", 1024)
    assert api.post("/api/v1/detect", files={"file": ("song.wav", b"12345")}).status_code == 413
    boundary = "test-boundary"
    payload = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="song.wav"\r\n\r\n'.encode()
        + b"x" * 2048
        + f"\r\n--{boundary}--\r\n".encode()
    )
    result = api.post(
        "/api/v1/detect",
        content=iter([payload[:500], payload[500:]]),
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )
    assert result.status_code == 413
    assert detector.paths == []


def test_multiple_files_and_cross_origin_requests_rejected(client):
    api, detector = client
    response = api.post(
        "/api/v1/detect", files=[("file", ("a.wav", b"a")), ("file", ("b.wav", b"b"))]
    )
    assert response.status_code == 400
    response = api.post(
        "/api/v1/detect",
        files={"file": ("a.wav", b"a")},
        headers={"origin": "https://unrelated.example"},
    )
    assert response.status_code == 403
    assert detector.paths == []


def test_detector_error_cleans_temporary_file(client, monkeypatch):
    api, detector = client

    def bad_audio(path, filename=None, **kwargs):
        detector.paths.append(Path(path))
        raise AudioError("Invalid audio", code="invalid_audio")

    monkeypatch.setattr(detector, "analyze", bad_audio)
    response = api.post("/api/v1/detect", files={"file": ("bad.wav", b"bad")})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_audio"
    assert not detector.paths[0].parent.exists()
    assert not server.app.state.active_request


def test_concurrent_analysis_returns_busy_instead_of_queueing(client, monkeypatch):
    _, detector = client
    entered, release = threading.Event(), threading.Event()

    def blocking(path, filename=None, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return RecordingDetector().analyze(path, filename=filename)

    monkeypatch.setattr(detector, "analyze", blocking)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://testserver"
        ) as api:
            first = asyncio.create_task(
                api.post("/api/v1/detect", files={"file": ("one.wav", b"test")})
            )
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                second = await api.post("/api/v1/detect", files={"file": ("two.wav", b"test")})
                assert second.status_code == 429
                assert second.json()["detail"]["code"] == "busy"
            finally:
                release.set()
            assert (await first).status_code == 200

    asyncio.run(scenario())
    assert not server.app.state.active_request


def wait_job(api, identifier, terminal=True):
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = api.get(f"/api/v1/jobs/{identifier}")
        assert response.headers["cache-control"] == "no-store"
        record = response.json()
        if (record["status"] in {"completed", "failed", "cancelled"}) == terminal:
            return record
        time.sleep(0.01)
    pytest.fail("Job did not reach the requested state")


def test_jobs_complete_and_cleanup_inputs(client):
    api, detector = client
    response = api.post(
        "/api/v1/jobs?start_seconds=2&duration_seconds=10", files={"file": ("song.wav", b"test")}
    )
    assert response.status_code == 202
    record = wait_job(api, response.json()["id"])
    assert record["status"] == "completed"
    assert record["stage"] == "complete"
    assert record["result"]["decision_policy"]["validated"] is False
    assert not detector.paths[0].parent.exists()
    assert server.app.state.jobs.pending == 0
    assert api.post(f"/api/v1/jobs/{record['id']}/cancel").json() == record


def test_job_error_retained_without_audio(client, monkeypatch):
    api, detector = client

    def fail_input(path, **kwargs):
        detector.paths.append(path)
        raise AudioError("Bad audio", "invalid_audio")

    monkeypatch.setattr(detector, "analyze", fail_input)
    identifier = api.post("/api/v1/jobs", files={"file": ("bad.wav", b"test")}).json()["id"]
    record = wait_job(api, identifier)
    assert record["status"] == "failed"
    assert record["error"] == {"code": "invalid_audio", "message": "Bad audio"}
    assert not detector.paths[0].parent.exists()


def test_queue_bound_and_real_cancellation(client, monkeypatch):
    from ai_song_detection import jobs
    from ai_song_detection.detector import AnalysisCancelled

    api, detector = client
    entered, release = threading.Event(), threading.Event()
    paths = []

    def blocked(path, cancel_event, **kwargs):
        paths.append(path)
        entered.set()
        assert release.wait(5)
        if cancel_event.is_set():
            raise AnalysisCancelled()
        return RecordingDetector().analyze(path, filename="song.wav")

    monkeypatch.setattr(detector, "analyze", blocked)
    monkeypatch.setattr(jobs, "MAX_PENDING_JOBS", 2)
    upload = {"file": ("song.wav", b"test")}
    first = api.post("/api/v1/jobs", files=upload).json()["id"]
    assert entered.wait(3)
    try:
        second = api.post("/api/v1/jobs", files=upload).json()["id"]
        assert api.post("/api/v1/jobs", files=upload).status_code == 429
        assert api.post("/api/v1/detect", files=upload).status_code == 429
        assert api.post(f"/api/v1/jobs/{first}/cancel").json()["status"] == "cancelling"
        assert paths[0].exists()  # Input remains owned until the actual thread exits.
        assert server.app.state.jobs.pending == 2
        assert api.post(f"/api/v1/jobs/{second}/cancel").json()["status"] == "cancelled"
        assert server.app.state.jobs.pending == 1
    finally:
        release.set()
    assert wait_job(api, first)["status"] == "cancelled"
    assert not paths[0].parent.exists()
    assert len(paths) == 1  # The queued cancellation never starts inference.
    assert server.app.state.jobs.pending == 0


@pytest.mark.parametrize(
    "query", ["start_seconds=-1", "duration_seconds=9", "duration_seconds=301", "start_seconds=nan"]
)
def test_invalid_window_never_uploads(client, query):
    api, detector = client
    for endpoint in ("detect", "jobs"):
        assert (
            api.post(
                f"/api/v1/{endpoint}?{query}", files={"file": ("song.wav", b"test")}
            ).status_code
            == 422
        )
    assert not detector.paths
    assert server.app.state.jobs.pending == 0


def test_missing_and_expired_jobs(client, monkeypatch):
    from ai_song_detection import jobs

    api, _ = client
    assert api.get("/api/v1/jobs/missing").status_code == 404
    assert api.post("/api/v1/jobs/missing/cancel").status_code == 404
    identifier = api.post("/api/v1/jobs", files={"file": ("song.wav", b"test")}).json()["id"]
    wait_job(api, identifier)
    monkeypatch.setattr(jobs, "REPORT_TTL_SECONDS", -1)
    assert api.get(f"/api/v1/jobs/{identifier}").status_code == 404


def test_foreground_restarts_have_distinct_instances_for_browser_recovery(monkeypatch):
    monkeypatch.delenv("AI_SONG_DETECTION_INSTANCE_ID", raising=False)
    monkeypatch.setattr(server, "Detector", RecordingDetector)

    async def scenario():
        identifiers = []
        for _ in range(2):
            foreground = server.FastAPI()
            async with server.lifespan(foreground):
                identifiers.append(foreground.state.instance_id)
        assert all(identifiers) and identifiers[0] != identifiers[1]

    asyncio.run(scenario())
