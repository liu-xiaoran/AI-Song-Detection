"""User-level, single-instance service management for desktop and CLI launchers."""

from __future__ import annotations

import errno
import http.client
import json
import math
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from contextlib import contextmanager
from pathlib import Path

from . import __version__

APP_ID = "ai-song-detection"
STATE_ENV = "AI_SONG_DETECTION_STATE_DIR"


class LauncherError(RuntimeError):
    """An actionable installation or lifecycle error."""


def state_directory() -> Path:
    """Return a private per-user directory, independent of the current checkout."""
    override = os.environ.get(STATE_ENV)
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/AI Song Detection/state"
    if os.name == "nt":
        return (
            Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
            / "AI Song Detection/state"
        )
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / APP_ID


def _prepare_directory() -> Path:
    directory = state_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        directory.chmod(0o700)
    return directory


@contextmanager
def _lock(timeout: float = 120, name: str = "launcher.lock"):
    """Lock the same persistent byte/file on both Windows and POSIX."""
    directory = _prepare_directory()
    descriptor = os.open(directory / name, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "r+b", buffering=0) as lock:
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b"0")
        deadline = time.monotonic() + timeout
        while True:
            lock.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                if time.monotonic() >= deadline:
                    raise LauncherError(
                        "Another install/start/stop operation is still running. Try again shortly."
                    ) from exc
                time.sleep(0.1)
        try:
            yield directory
        finally:
            lock.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


@contextmanager
def service_lease():
    """Hold a separate singleton lease throughout the managed server's lifetime."""
    with _lock(timeout=0, name="service.lock"):
        yield


def _service_lease_held() -> bool:
    try:
        with service_lease():
            return False
    except LauncherError:
        return True


def _read_state(directory: Path) -> dict | None:
    try:
        state = json.loads((directory / "instance.json").read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            return None
        if not isinstance(state.get("port"), int) or not 1 <= state["port"] <= 65535:
            return None
        if not isinstance(state.get("pid"), int) or state["pid"] <= 0:
            return None
        if not all(
            isinstance(state.get(key), str) and state[key]
            for key in ("instance_id", "control_token", "version")
        ):
            return None
        # Never trust a persisted URL to choose a remote request destination.
        state["url"] = f"http://127.0.0.1:{state['port']}"
        return state
    except (OSError, ValueError, TypeError):
        return None


def _write_state(directory: Path, state: dict) -> None:
    temporary = directory / "instance.json.new"
    descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        json.dump(state, target, indent=2)
        target.write("\n")
    temporary.replace(directory / "instance.json")
    if os.name != "nt":
        (directory / "instance.json").chmod(0o600)


def _request(url: str, *, token: str | None = None) -> tuple[int, dict] | None:
    headers = {"X-AI-Song-Control": token} if token else {}
    request = urllib.request.Request(
        url, headers=headers, method="POST" if token else "GET", data=b"" if token else None
    )
    # Ignore HTTP_PROXY/HTTPS_PROXY even on corporate desktops: control stays local.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=1) as response:
            return response.status, json.loads(response.read(65536))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read(65536))
        except (ValueError, OSError):
            return None
    except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException):
        return None


def _health(state: dict) -> dict | None:
    response = _request(state["url"] + "/health")
    if not response or not isinstance(response[1], dict):
        return None
    health = response[1]
    if (
        health.get("app_id") != APP_ID
        or health.get("instance_id") != state["instance_id"]
        or health.get("version") != state["version"]
        or health.get("pid") != state["pid"]
    ):
        return None
    return health


def _ready(health: dict) -> bool:
    return (
        health.get("status") == "ok"
        and health.get("model_loaded") is True
        and health.get("ffmpeg_available") is True
    )


def _public(state: dict, directory: Path, **extra) -> dict:
    return {
        "status": "running",
        "url": state["url"],
        "pid": state.get("pid"),
        "version": state["version"],
        "log_file": str(directory / "service.log"),
        **extra,
    }


def _port_available(port: int) -> bool:
    with socket.socket() as listener:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _candidate_ports(preferred: int):
    yield from range(preferred, min(preferred + 20, 65536))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        available = listener.getsockname()[1]
    yield available


def _server_command(port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "ai_song_detection",
        "_managed-serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]


def _open_browser(url: str, enabled: bool) -> bool:
    if not enabled:
        return False
    try:
        return bool(webbrowser.open(url, new=2))
    except (webbrowser.Error, OSError):
        return False


def _require_decoder() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise LauncherError(
            "FFmpeg/ffprobe are missing from this installation. Run the installer again to repair it."
        )


def launch(port: int = 8000, open_browser: bool = True, timeout: float = 45) -> dict:
    """Start/reuse this user's instance and open its page only after readiness."""
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise LauncherError("The port must be between 1 and 65535.")
    if not math.isfinite(timeout) or timeout <= 0:
        raise LauncherError("The startup timeout must be greater than zero.")
    with _lock(timeout=max(120, timeout + 10)) as directory:
        state = _read_state(directory)
        if state and (health := _health(state)):
            if state["version"] != __version__:
                raise LauncherError(
                    "A different version is already running. Stop it before launching this version."
                )
            if not _ready(health):
                raise LauncherError(
                    "The running detector is not ready. Stop it and run the installer again to repair dependencies."
                )
            return _public(
                state,
                directory,
                reused=True,
                browser_opened=_open_browser(state["url"], open_browser),
            )
        if _service_lease_held():
            raise LauncherError(
                f"A detector is already running but is not responding. No second instance was started. See {directory / 'service.log'}"
            )
        _require_decoder()
        deadline = time.monotonic() + timeout
        for candidate in _candidate_ports(port):
            if not _port_available(candidate):
                continue
            state = {
                "instance_id": secrets.token_hex(16),
                "control_token": secrets.token_urlsafe(32),
                "port": candidate,
                "url": f"http://127.0.0.1:{candidate}",
                "version": __version__,
                "created": time.time(),
            }
            environment = os.environ.copy()
            environment.update(
                {
                    STATE_ENV: str(directory),
                    "AI_SONG_DETECTION_INSTANCE_ID": state["instance_id"],
                    "AI_SONG_DETECTION_CONTROL_TOKEN": state["control_token"],
                    "PYTHONUNBUFFERED": "1",
                }
            )
            log_path = directory / "service.log"
            if log_path.exists() and log_path.stat().st_size > 5 * 1024 * 1024:
                log_path.replace(directory / "service.log.1")
            descriptor = os.open(log_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "ab", buffering=0) as log:
                options = (
                    {"start_new_session": True}
                    if os.name != "nt"
                    else {"creationflags": subprocess.CREATE_NO_WINDOW}
                )
                child = subprocess.Popen(
                    _server_command(candidate),
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    cwd=str(directory),
                    **options,
                )
            state["pid"] = child.pid
            try:
                _write_state(directory, state)
                while time.monotonic() < deadline:
                    health = _health(state)
                    if health and _ready(health):
                        return _public(
                            state,
                            directory,
                            reused=False,
                            browser_opened=_open_browser(state["url"], open_browser),
                        )
                    if child.poll() is not None:
                        if not _port_available(candidate):
                            break  # Another process won the bind race; try another port.
                        raise LauncherError(f"The detector stopped during startup. See {log_path}")
                    time.sleep(0.15)
                else:
                    raise LauncherError(
                        f"The detector did not become ready within {timeout:g} seconds. See {log_path}"
                    )
            except BaseException:
                # This handle belongs to the child just created, never a saved/reused PID.
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
                (directory / "instance.json").unlink(missing_ok=True)
                raise
            (directory / "instance.json").unlink(missing_ok=True)
        raise LauncherError(
            "No available local port was found. Close a detector instance and retry."
        )


def status() -> dict:
    """Describe an identity-verified instance without exposing its control token."""
    with _lock() as directory:
        state = _read_state(directory)
        if state and (health := _health(state)):
            return _public(state, directory, ready=_ready(health))
        if _service_lease_held():
            return {
                "status": "running",
                "ready": False,
                "log_file": str(directory / "service.log"),
                "message": "A managed detector is running but is not responding.",
            }
        return {"status": "stopped", "log_file": str(directory / "service.log")}


def _process_running(pid: int) -> bool:
    """Wait/check an already identity-verified PID; never signal a Windows process."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only.
        if not handle:
            return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER: PID gone.
        try:
            return kernel.WaitForSingleObject(handle, 0) != 0  # WAIT_OBJECT_0: exited.
        finally:
            kernel.CloseHandle(handle)
    try:
        # Reap children owned by this invocation; another CLI's child cannot be waited.
        waited, _ = os.waitpid(pid, os.WNOHANG)
        if waited:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)  # POSIX existence probe, not a termination signal.
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def stop(timeout: float = 90) -> dict:
    """Gracefully stop only the instance that proves the saved app/instance identity."""
    if not math.isfinite(timeout) or timeout <= 0:
        raise LauncherError("The shutdown timeout must be a finite value greater than zero.")
    with _lock(timeout=max(120, timeout + 10)) as directory:
        state = _read_state(directory)
        if not state or not _health(state):
            if _service_lease_held():
                raise LauncherError(
                    f"The detector is still running but its control service is unreachable. No process was killed and the instance record was preserved. See {directory / 'service.log'}"
                )
            (directory / "instance.json").unlink(missing_ok=True)
            return {"status": "stopped", "was_running": False}
        response = _request(state["url"] + "/_control/stop", token=state["control_token"])
        if not response or response[0] != 202:
            raise LauncherError(
                "The running instance did not accept the stop request. No process was killed."
            )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _health(state) and not _process_running(state["pid"]):
                (directory / "instance.json").unlink(missing_ok=True)
                return {"status": "stopped", "was_running": True}
            time.sleep(0.2)
        raise LauncherError(
            "The detector is still finishing an active request. Try stop again shortly."
        )
