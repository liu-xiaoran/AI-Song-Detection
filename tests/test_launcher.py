"""Exercise real service processes and identity/cleanup contracts on every OS."""

import json
import os
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from ai_song_detection import __version__, launcher


@pytest.fixture
def managed_service(tmp_path, monkeypatch):
    state = tmp_path / "中文 app state"
    monkeypatch.setenv(launcher.STATE_ENV, str(state))
    monkeypatch.setenv("LAUNCHER_TEST_VERSION", __version__)
    script = tmp_path / "fake service.py"
    script.write_text(
        """
import json, os, sys, threading, time, socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ai_song_detection.launcher import service_lease
started = time.monotonic()
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        ready = time.monotonic() - started >= float(os.environ.get("LAUNCHER_TEST_READY_DELAY", "0"))
        data = {"status": "ok" if ready else "degraded", "app_id": "ai-song-detection",
                "instance_id": os.environ["AI_SONG_DETECTION_INSTANCE_ID"],
                "version": os.environ["LAUNCHER_TEST_VERSION"], "pid": os.getpid(),
                "model_loaded": ready, "ffmpeg_available": True}
        body = json.dumps(data).encode()
        self.send_response(200 if ready else 503)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        if self.headers.get("X-AI-Song-Control") != os.environ["AI_SONG_DETECTION_CONTROL_TOKEN"]:
            self.send_response(403); self.end_headers(); return
        self.send_response(202); self.end_headers(); self.wfile.write(b"{}")
        def finish():
            server.shutdown()
        threading.Thread(target=finish, daemon=True).start()
class LocalServer(ThreadingHTTPServer):
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]
with service_lease():
    server = LocalServer(("127.0.0.1", int(sys.argv[1])), Handler)
    server.serve_forever(poll_interval=.02)
    server.server_close()
    # Simulate a worker completing after the listener has already closed.
    time.sleep(float(os.environ.get("LAUNCHER_TEST_EXIT_DELAY", "0")))
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        launcher, "_server_command", lambda port: [sys.executable, str(script), str(port)]
    )
    monkeypatch.setattr(launcher, "_require_decoder", lambda: None)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    yield state, port
    launcher.stop(timeout=5)


def test_start_reuse_status_stop_and_secret_privacy(managed_service):
    state_dir, port = managed_service
    first = launcher.launch(port=port, open_browser=False, timeout=5)
    assert first["status"] == "running" and first["reused"] is False
    assert first["browser_opened"] is False
    assert "control_token" not in first
    second = launcher.launch(port=port, open_browser=False, timeout=5)
    assert second["reused"] is True
    assert second["pid"] == first["pid"]
    assert launcher.status()["ready"] is True
    state = json.loads((state_dir / "instance.json").read_text())
    assert state["control_token"] not in json.dumps(first)
    if os.name != "nt":
        assert (state_dir / "instance.json").stat().st_mode & 0o777 == 0o600
    assert launcher.stop(timeout=5) == {"status": "stopped", "was_running": True}
    assert launcher.status()["status"] == "stopped"
    assert launcher.stop()["was_running"] is False


def test_open_browser_only_after_ready_and_on_reuse(managed_service, monkeypatch):
    _, port = managed_service
    monkeypatch.setenv("LAUNCHER_TEST_READY_DELAY", "0.25")
    opened = []

    def browser(url, new):
        assert launcher._request(url + "/health")[1]["model_loaded"] is True
        opened.append(url)
        return True

    monkeypatch.setattr(launcher.webbrowser, "open", browser)
    first = launcher.launch(port=port, timeout=5)
    second = launcher.launch(port=port, timeout=5)
    assert first["browser_opened"] and second["browser_opened"]
    assert opened == [first["url"], first["url"]]


def test_port_occupied_by_foreign_service_is_not_reused(managed_service):
    _, port = managed_service
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", port))
        occupied.listen()
        result = launcher.launch(port=port, open_browser=False, timeout=5)
        assert result["url"] != f"http://127.0.0.1:{port}"
        assert occupied.fileno() != -1


def test_repeated_concurrent_launch_uses_one_instance(managed_service):
    _, port = managed_service
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: launcher.launch(port=port, open_browser=False, timeout=5), range(2))
        )
    assert results[0]["pid"] == results[1]["pid"]
    assert sorted(result["reused"] for result in results) == [False, True]


def test_graceful_stop_waits_for_worker_after_listener_closes(managed_service, monkeypatch):
    _, port = managed_service
    monkeypatch.setenv("LAUNCHER_TEST_EXIT_DELAY", "0.5")
    launcher.launch(port=port, open_browser=False, timeout=5)
    before = time.monotonic()
    assert launcher.stop(timeout=5)["was_running"] is True
    assert time.monotonic() - before >= 0.45


def test_failed_start_cleans_owned_process_and_saved_state(managed_service, monkeypatch):
    state_dir, port = managed_service
    monkeypatch.setattr(
        launcher, "_server_command", lambda _: [sys.executable, "-c", "raise SystemExit(9)"]
    )
    with pytest.raises(launcher.LauncherError, match="stopped during startup"):
        launcher.launch(port=port, open_browser=False, timeout=5)
    assert not (state_dir / "instance.json").exists()
    assert launcher.status()["status"] == "stopped"


def test_timeout_cleans_owned_process_without_opening_browser(managed_service, monkeypatch):
    state_dir, port = managed_service
    monkeypatch.setenv("LAUNCHER_TEST_READY_DELAY", "60")
    monkeypatch.setattr(
        launcher.webbrowser,
        "open",
        lambda *args, **kwargs: pytest.fail("Browser opened before readiness"),
    )
    with pytest.raises(launcher.LauncherError, match="did not become ready"):
        launcher.launch(port=port, timeout=0.35)
    assert not (state_dir / "instance.json").exists()


def test_stale_state_never_stops_unrelated_pid(tmp_path, monkeypatch):
    monkeypatch.setenv(launcher.STATE_ENV, str(tmp_path))
    launcher._write_state(
        tmp_path,
        {
            "pid": os.getpid(),
            "port": 65530,
            "version": __version__,
            "instance_id": "stale",
            "control_token": "stale",
        },
    )
    monkeypatch.setattr(
        launcher, "_request", lambda *args, **kwargs: (200, {"app_id": "another-app"})
    )
    monkeypatch.setattr(
        launcher, "_process_running", lambda _: pytest.fail("Touched unrelated process")
    )
    assert launcher.stop() == {"status": "stopped", "was_running": False}


def test_browser_failure_leaves_healthy_service_and_reports_url(managed_service, monkeypatch):
    _, port = managed_service
    monkeypatch.setattr(launcher.webbrowser, "open", lambda *args, **kwargs: False)
    result = launcher.launch(port=port, timeout=5)
    assert result["browser_opened"] is False
    assert launcher.status()["ready"] is True


def test_file_lock_blocks_second_operation(tmp_path, monkeypatch):
    monkeypatch.setenv(launcher.STATE_ENV, str(tmp_path))
    entered, release = threading.Event(), threading.Event()

    def holding_lock():
        with launcher._lock():
            entered.set()
            release.wait(3)

    thread = threading.Thread(target=holding_lock)
    thread.start()
    try:
        assert entered.wait(1)
        with pytest.raises(launcher.LauncherError, match="operation is still running"):
            with launcher._lock(timeout=0.1):
                pytest.fail("Acquired another active lock")
    finally:
        release.set()
        thread.join(3)


def test_request_ignores_proxy_and_saved_external_url(managed_service, monkeypatch):
    state_dir, port = managed_service
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    result = launcher.launch(port=port, open_browser=False, timeout=5)
    state = json.loads((state_dir / "instance.json").read_text())
    state["url"] = "https://unrelated.example"
    launcher._write_state(state_dir, state)
    assert launcher.status()["url"] == result["url"]


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeouts_are_rejected_without_starting(timeout, tmp_path, monkeypatch):
    monkeypatch.setenv(launcher.STATE_ENV, str(tmp_path))
    with pytest.raises(launcher.LauncherError, match="timeout"):
        launcher.launch(timeout=timeout)
    with pytest.raises(launcher.LauncherError, match="timeout"):
        launcher.stop(timeout=timeout)
    assert not (tmp_path / "instance.json").exists()


@pytest.mark.parametrize("pid", [None, -1, 0, "123"])
def test_invalid_saved_pid_is_discarded(pid, tmp_path):
    launcher._write_state(
        tmp_path,
        {
            "pid": pid,
            "port": 8000,
            "version": __version__,
            "instance_id": "stale",
            "control_token": "stale",
        },
    )
    assert launcher._read_state(tmp_path) is None


def test_missing_decoders_fail_before_creating_process_or_browser(tmp_path, monkeypatch):
    monkeypatch.setenv(launcher.STATE_ENV, str(tmp_path))
    monkeypatch.setattr(launcher.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        launcher.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Started without decoder")
    )
    monkeypatch.setattr(
        launcher.webbrowser, "open", lambda *args, **kwargs: pytest.fail("Opened without decoder")
    )
    with pytest.raises(launcher.LauncherError, match="installer again"):
        launcher.launch()
    assert not (tmp_path / "instance.json").exists()


def test_health_pid_mismatch_cannot_be_mistaken_for_our_instance(monkeypatch):
    state = {
        "url": "http://127.0.0.1:8000",
        "instance_id": "same-id",
        "pid": 123,
        "version": __version__,
    }
    monkeypatch.setattr(
        launcher,
        "_request",
        lambda _: (
            200,
            {
                "app_id": launcher.APP_ID,
                "instance_id": "same-id",
                "pid": 124,
                "version": __version__,
            },
        ),
    )
    assert launcher._health(state) is None


def test_running_lease_without_health_prevents_duplicate_and_preserves_state(
    managed_service, monkeypatch
):
    state_dir, port = managed_service
    first = launcher.launch(port=port, open_browser=False, timeout=5)
    saved = (state_dir / "instance.json").read_text()
    with monkeypatch.context() as temporary:
        temporary.setattr(launcher, "_health", lambda _: None)
        temporary.setattr(
            launcher.subprocess,
            "Popen",
            lambda *args, **kwargs: pytest.fail("Duplicate instance started"),
        )
        assert launcher.status()["status"] == "running"
        assert launcher.status()["ready"] is False
        with pytest.raises(launcher.LauncherError, match="already running"):
            launcher.launch(open_browser=False)
        with pytest.raises(launcher.LauncherError, match="unreachable"):
            launcher.stop()
        assert (state_dir / "instance.json").read_text() == saved
    assert launcher.status()["pid"] == first["pid"]


def test_running_lease_with_lost_state_does_not_report_stopped_or_spawn(tmp_path, monkeypatch):
    monkeypatch.setenv(launcher.STATE_ENV, str(tmp_path))
    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("Duplicate instance started"),
    )
    with launcher.service_lease():
        assert launcher.status()["status"] == "running"
        assert launcher.status()["ready"] is False
        with pytest.raises(launcher.LauncherError, match="already running"):
            launcher.launch(open_browser=False)
        with pytest.raises(launcher.LauncherError, match="unreachable"):
            launcher.stop()
    assert launcher.status()["status"] == "stopped"
