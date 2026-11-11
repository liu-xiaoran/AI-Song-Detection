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

    def analyze(self, path, filename=None):
        self.paths.append(Path(path))
        assert path.exists()
        return {
            "filename": filename,
            "assessment": "uncertain",
            "ai_score": 0.5,
            "threshold": 0.5,
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

    def bad_audio(path, filename=None):
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

    def blocking(path, filename=None):
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
