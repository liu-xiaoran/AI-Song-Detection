"""Explicit, per-user maintenance operations for the desktop installation."""

from __future__ import annotations

import json
import os
import platform
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, installer, launcher

REPOSITORY = "liu-xiaoran/AI-Song-Detection"
OWNED_DIRECTORIES = (
    "releases",
    "tools",
    "runtime",
    "bootstrap",
    "cache",
    "downloads",
    "bin",
    "state",
)
OWNED_FILES = ("current.json", "shell-links.json", "update.json", "uninstall-request.json")


class MaintenanceError(RuntimeError):
    """An actionable maintenance failure."""


def _installation() -> tuple[Path, dict]:
    root = installer.install_directory().expanduser().resolve()
    if root == root.parent or root == Path.home().resolve():
        raise MaintenanceError("The installation directory is not a safe application directory.")
    if (root / "uninstall-request.json").exists():
        raise MaintenanceError("An uninstall is pending. Wait for its cleanup to finish.")
    try:
        path = root / "current.json"
        if path.is_symlink():
            raise ValueError("linked installation record")
        current = json.loads(path.read_text(encoding="utf-8"))
        release = Path(current["release"])
        if (
            release.parent != root / "releases"
            or release.is_symlink()
            or not _marked_release(release)
            or Path(current["python"]).parent.parent != release / ".venv"
            or not re.fullmatch(r"[0-9a-f]{64}", current["source_sha256"])
        ):
            raise ValueError("invalid installation boundaries")
        marker = json.loads((release / "installed.json").read_text(encoding="utf-8"))
        if marker["source_sha256"] != current["source_sha256"]:
            raise ValueError("inconsistent installation records")
        # Also reject a linked parent, rather than following it during deletion.
        for name in OWNED_DIRECTORIES:
            if (root / name).is_symlink():
                raise ValueError("linked application directory")
        return root, current
    except (OSError, KeyError, ValueError, TypeError) as exc:
        raise MaintenanceError(
            "A valid desktop installation was not found. Run the installer to create or repair it."
        ) from exc


def _marked_release(path: Path) -> bool:
    marker = path / "installed.json"
    if path.is_symlink() or marker.is_symlink():
        return False
    try:
        information = json.loads(marker.read_text(encoding="utf-8"))
        return (
            information["release"] == str(path)
            and re.fullmatch(r"[0-9a-f]{64}", information["source_sha256"]) is not None
            and Path(information["python"]).parent.parent == path / ".venv"
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


@contextmanager
def _installed_state(root: Path):
    """Maintenance must operate on this installation, regardless of caller overrides."""
    previous = os.environ.get(launcher.STATE_ENV)
    os.environ[launcher.STATE_ENV] = str(root / "state")
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(launcher.STATE_ENV, None)
        else:
            os.environ[launcher.STATE_ENV] = previous


def _size(path: Path) -> int:
    if path.is_symlink():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for directory, names, files in os.walk(path, followlinks=False):
        names[:] = [name for name in names if not (Path(directory) / name).is_symlink()]
        for name in files:
            item = Path(directory) / name
            if not item.is_symlink():
                total += item.stat().st_size
    return total


def doctor() -> dict:
    """Check this interpreter, model, decoder and identity-verified service."""
    checks = []

    def check(name, function):
        try:
            detail = function()
            checks.append({"name": name, "ok": True, "detail": detail})
        except Exception as exc:
            checks.append({"name": name, "ok": False, "detail": str(exc)})

    check("python", lambda: {"version": platform.python_version(), "executable": sys.executable})

    def model():
        from .detector import Detector

        detector = Detector()
        return {"loaded": True, "provider": "CPUExecutionProvider", "model": detector.model}

    check("model", model)
    for command in ("ffmpeg", "ffprobe"):

        def audio_tool(command=command):
            executable = shutil.which(command)
            if not executable:
                raise MaintenanceError(f"{command} is missing. Run the installer to repair it.")
            completed = subprocess.run(
                [executable, "-version"], capture_output=True, text=True, timeout=10, check=True
            )
            return {"path": executable, "version": completed.stdout.splitlines()[0]}

        check(command, audio_tool)

    def service():
        information = launcher.status()
        if information["status"] == "running" and not information.get("ready"):
            raise MaintenanceError(
                "The managed service is running but is not ready. Read the service log, then stop and repair it."
            )
        return information

    check("service", service)
    try:
        root, current = _installation()
        checks.append(
            {
                "name": "installation",
                "ok": True,
                "detail": {
                    "root": str(root),
                    "release": current["release"],
                    "source_sha256": current["source_sha256"],
                    "platform": current.get("platform"),
                },
            }
        )
    except MaintenanceError as exc:
        checks.append({"name": "installation", "ok": False, "detail": str(exc)})
    return {
        "ok": all(check["ok"] for check in checks),
        "application_version": __version__,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }


def logs(*, follow: bool = False, lines: int = 100) -> None:
    """Print the managed service log; do not include the private instance record."""
    if not 1 <= lines <= 10000:
        raise MaintenanceError("Log lines must be between 1 and 10000.")
    path = launcher.state_directory() / "service.log"
    if not path.is_file():
        raise MaintenanceError("No service log exists yet. Start the desktop application first.")
    with path.open("r", encoding="utf-8", errors="replace") as source:
        # Bound initial reads even if an old/manual runtime produced a large log.
        source.seek(max(0, path.stat().st_size - 2 * 1024 * 1024))
        if source.tell():
            source.readline()
        print("".join(source.readlines()[-lines:]), end="", flush=True)
        if follow:
            try:
                while True:
                    line = source.readline()
                    if line:
                        print(line, end="", flush=True)
                    else:
                        time.sleep(0.25)
            except KeyboardInterrupt:
                return


def diagnostics(output: Path) -> dict:
    """Export health facts only; omit raw logs, audio, environment and control state."""
    output = output.expanduser().resolve()
    if output.exists():
        raise MaintenanceError("The diagnostic output already exists. Choose a new file.")
    report = doctor()
    # Do not put usernames or private installation paths into an artifact for sharing.
    private_paths = sorted(
        {str(Path.home()), str(installer.install_directory()), str(launcher.state_directory())},
        key=len,
        reverse=True,
    )

    def redact(value):
        if isinstance(value, dict):
            return {key: redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, str):
            for private in private_paths:
                value = value.replace(private, "<private-directory>")
            return value
        return value

    raw = json.dumps(redact(report), indent=2)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with (
        os.fdopen(descriptor, "wb") as target,
        zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive,
    ):
        archive.writestr("doctor.json", raw + "\n")
        archive.writestr(
            "README.txt",
            "Contains model/decoder/installation health facts with private directory prefixes removed.\n"
            "Raw service logs, environment variables, audio, reports and instance control tokens are omitted.\n"
            "Review doctor.json before sharing.\n",
        )
    return {"output": str(output), "ok": report["ok"], "includes_raw_logs": False}


def _private_uv(root: Path, current: dict, source: Path) -> Path:
    manifest = json.loads((source / "install/dependencies.json").read_text(encoding="utf-8"))
    specification = manifest["platforms"][current["platform"]]
    version, target = manifest["uv_version"], specification["uv_target"]
    if not re.fullmatch(r"[0-9.]+", version) or not re.fullmatch(r"[a-zA-Z0-9_-]+", target):
        raise MaintenanceError("Invalid private installer metadata.")
    executable = (
        root
        / "bootstrap"
        / f"uv-{version}-{target}"
        / ("uv.exe" if current["platform"].startswith("win32") else "uv")
    )
    if executable.is_symlink() or not executable.is_file():
        raise MaintenanceError(
            "The required private installer version is not installed. Download this version and run Install again."
        )
    return executable


def _fetch(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "AI-Song-Detection-Updater"})
    with urllib.request.urlopen(request, timeout=60) as response:
        if not response.url.startswith("https://"):
            raise MaintenanceError("The update redirected to an insecure address.")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise MaintenanceError("The update exceeded its download size limit.")
        return data


def _extract_source(payload: bytes, destination: Path) -> Path:
    import io

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.infolist()
        roots = set()
        total = 0
        if len(names) > 20000:
            raise MaintenanceError("The update archive contains too many files.")
        for info in names:
            path = Path(info.filename)
            mode = info.external_attr >> 16
            total += info.file_size
            if (
                not path.parts
                or path.is_absolute()
                or ".." in path.parts
                or "\\" in info.filename
                or ":" in info.filename
                or stat.S_ISLNK(mode)
                or total > 600 * 1024 * 1024
            ):
                raise MaintenanceError("The update archive contains an unsafe file.")
            roots.add(path.parts[0])
        if len(roots) != 1:
            raise MaintenanceError("The update archive must contain exactly one project directory.")
        archive.extractall(destination)
    source = destination / roots.pop()
    installer.payload_digest(source)
    return source


def update(*, source: Path | None = None, launch: bool = True) -> dict:
    """Install a checked local source, or the HTTPS-pinned head of our own repository."""
    root, current = _installation()
    if source is not None:
        source = source.expanduser().resolve()
        installer.payload_digest(source)
        uv = _private_uv(root, current, source)
        return installer.install(source, uv, root, Path(current["desktop"]), launch=launch)
    try:
        metadata = json.loads(
            _fetch(f"https://api.github.com/repos/{REPOSITORY}/commits/main", 1024 * 1024)
        )
        commit = metadata.get("sha", "")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise MaintenanceError("GitHub did not provide a valid update revision.")
        payload = _fetch(
            f"https://codeload.github.com/{REPOSITORY}/zip/{commit}", 200 * 1024 * 1024
        )
        with tempfile.TemporaryDirectory(prefix="ai-song-update-") as temporary:
            source = _extract_source(payload, Path(temporary))
            uv = _private_uv(root, current, source)
            result = installer.install(source, uv, root, Path(current["desktop"]), launch=launch)
        installer.write_atomic(
            root / "update.json",
            json.dumps({"repository": REPOSITORY, "commit": commit}, indent=2) + "\n",
        )
        return result | {"repository": REPOSITORY, "commit": commit}
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise MaintenanceError(f"The update could not be prepared: {exc}") from exc


def cleanup(*, keep: int = 2, apply: bool = False, cache: bool = False) -> dict:
    """Preview/remove old marked releases while always protecting current/caller versions."""
    if keep < 1:
        raise MaintenanceError("Keep must be at least 1, including the current release.")
    root, current = _installation()
    with installer.install_lock(root), _installed_state(root), launcher._lock() as directory:
        # Re-read under the install lock to avoid deleting a newly selected version.
        root, current = _installation()
        protected = {Path(current["release"]).resolve()}
        own = Path(__file__).resolve()
        releases = []
        for path in (root / "releases").iterdir():
            if not path.is_dir() or not _marked_release(path):
                continue
            if path in own.parents:
                protected.add(path.resolve())
            releases.append(path)
        state = launcher._read_state(directory)
        health = launcher._health(state) if state else None
        running = bool(health) or launcher._service_lease_held()
        active = Path(state.get("source_directory", "")) if state else None
        if running:
            if health and active in releases:
                protected.add(active.resolve())
            else:
                # Old/unresponsive workers have no trustworthy source directory.
                protected.update(path.resolve() for path in releases)
        releases.sort(key=lambda path: path.stat().st_mtime_ns, reverse=True)
        retained = set(protected)
        for path in releases:
            if len(retained) >= keep:
                break
            retained.add(path.resolve())
        selected = [path for path in releases if path.resolve() not in retained]
        if cache:
            selected.extend(path for path in (root / "cache", root / "downloads") if path.exists())
        items = [{"path": str(path), "size_bytes": _size(path)} for path in selected]
        if apply:
            for path in selected:
                shutil.rmtree(path)
        return {
            "applied": apply,
            "keep": keep,
            "items": items,
            "size_bytes": sum(item["size_bytes"] for item in items),
            "service_running": running,
            "message": "Stop the detector to remove releases retained for an unidentified active runtime."
            if running and not (health and active in releases)
            else "Current and executing releases are always retained.",
        }


def shell_setup(directory: Path) -> dict:
    """Create a user-selected command entry without changing PATH or shell profiles."""
    root, current = _installation()
    with installer.install_lock(root):
        root, current = _installation()
        windows = current["platform"].startswith("win32")
        wrapper = root / "bin" / ("ai-song-detection.cmd" if windows else "ai-song-detection")
        directory = directory.expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        entry = directory / wrapper.name
        if entry == wrapper:
            return {"command": str(entry), "directory": str(directory), "path_modified": False}
        text = installer.shortcut_text(wrapper, "", True) if windows else None
        if entry.exists() or entry.is_symlink():
            owned = (
                entry.is_symlink() and entry.resolve() == wrapper.resolve()
                if not windows
                else entry.is_file() and entry.read_text(encoding="utf-8") == text
            )
            if not owned:
                raise MaintenanceError(
                    "A different command already exists at the selected location."
                )
        elif windows:
            installer.write_atomic(entry, text, executable=True)
        else:
            entry.symlink_to(wrapper)
        record = root / "shell-links.json"
        try:
            links = json.loads(record.read_text())
        except (OSError, ValueError):
            links = []
        if str(entry) not in links:
            links.append(str(entry))
        installer.write_atomic(record, json.dumps(links, indent=2) + "\n")
    return {"command": str(entry), "directory": str(directory), "path_modified": False}


def _owned_entries(root: Path, current: dict) -> list[Path]:
    entries = []
    windows = current["platform"].startswith("win32")
    suffix = ".lnk" if windows else ".command"
    for label, action in ((installer.APP_NAME, "launch"), ("Stop " + installer.APP_NAME, "stop")):
        path = Path(current["desktop"]) / (label + suffix)
        if not path.is_file() or path.is_symlink():
            continue
        recorded = current.get("desktop_entries", {}).get(str(path))
        if recorded and installer.digest(path) == recorded:
            entries.append(path)
        elif not windows:
            text = path.read_text(encoding="utf-8", errors="replace")
            if text == installer.shortcut_text(root / "bin/ai-song-detection", action, False):
                entries.append(path)
    try:
        links = json.loads((root / "shell-links.json").read_text())
        for name in links:
            path = Path(name)
            wrapper = root / "bin" / ("ai-song-detection.cmd" if windows else "ai-song-detection")
            if (not windows and path.is_symlink() and path.resolve() == wrapper.resolve()) or (
                windows
                and path.is_file()
                and not path.is_symlink()
                and path.read_text(encoding="utf-8") == installer.shortcut_text(wrapper, "", True)
            ):
                entries.append(path)
    except (OSError, ValueError, TypeError):
        pass
    return entries


def _schedule_windows_removal(root: Path, paths: list[Path], marker: str) -> Path:
    """Let native PowerShell remove locked Python DLLs after this CLI exits."""
    directory = Path(tempfile.mkdtemp(prefix="ai-song-uninstall-"))
    script = directory / "remove.ps1"
    result = directory / "result.json"
    payload = json.dumps(
        {"root": str(root), "paths": [str(path) for path in paths], "nonce": marker},
        ensure_ascii=False,
    )
    (directory / "request.json").write_text(payload, encoding="utf-8")
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "$request = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'request.json') -Raw -Encoding UTF8 | ConvertFrom-Json\n"
        f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue\n"
        "$markerPath = Join-Path $request.root 'uninstall-request.json'\n"
        "$marker = Get-Content -LiteralPath $markerPath -Raw -Encoding UTF8 | ConvertFrom-Json\n"
        "if ($marker.nonce -ne $request.nonce) { throw 'Uninstall request changed.' }\n"
        "$remaining = @()\n"
        "function Remove-OwnedPath([string]$path) {\n"
        "  if (-not (Test-Path -LiteralPath $path)) { return }\n"
        "  $item = Get-Item -LiteralPath $path -Force\n"
        "  if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {\n"
        "    $item.Delete(); return\n"
        "  }\n"
        "  if ($item.PSIsContainer) {\n"
        "    Get-ChildItem -LiteralPath $path -Force | ForEach-Object { Remove-OwnedPath $_.FullName }\n"
        "    [IO.Directory]::Delete($path, $false)\n"
        "  } else { [IO.File]::SetAttributes($path, [IO.FileAttributes]::Normal); [IO.File]::Delete($path) }\n"
        "}\n"
        "foreach ($item in $request.paths) {\n"
        "  for ($attempt = 0; $attempt -lt 30; $attempt++) {\n"
        "    try { Remove-OwnedPath $item; break }\n"
        "    catch { if ($attempt -eq 29) { $remaining += $item } else { Start-Sleep -Milliseconds 500 } }\n"
        "  }\n"
        "}\n"
        "Remove-Item -LiteralPath $markerPath -Force\n"
        "@{ remaining = $remaining } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'result.json') -Encoding UTF8\n"
        "try { if ((Get-ChildItem -LiteralPath $request.root -Force).Count -eq 0) { Remove-Item -LiteralPath $request.root -Force } } catch {}\n",
        encoding="utf-8-sig",
    )
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        cwd=str(directory),
    )
    return result


def uninstall(*, apply: bool = False) -> dict:
    """Preview/remove owned application paths; preserve unrelated files and shortcuts."""
    root, current = _installation()
    with installer.install_lock(root), _installed_state(root):
        root, current = _installation()
        entries = _owned_entries(root, current)
        paths = [
            root / name for name in (*OWNED_DIRECTORIES, *OWNED_FILES) if (root / name).exists()
        ]
        # The lock cannot be removed until released; it is included in deferred Windows cleanup.
        items = [{"path": str(path), "size_bytes": _size(path)} for path in paths + entries]
        result = {
            "applied": apply,
            "items": items,
            "size_bytes": sum(item["size_bytes"] for item in items),
            "preserves_unrelated_files": True,
        }
        if not apply:
            return result
        nonce = secrets.token_hex(24)
        marker = root / "uninstall-request.json"
        installer.write_atomic(marker, json.dumps({"nonce": nonce}))
        try:
            launcher.stop()
        except BaseException:
            marker.unlink(missing_ok=True)
            raise
        if os.name == "nt":
            try:
                record = _schedule_windows_removal(
                    root, paths + entries + [root / "install.lock"], nonce
                )
            except Exception:
                (root / "uninstall-request.json").unlink(missing_ok=True)
                raise
            return result | {"scheduled_after_exit": True, "result_file": str(record)}
        try:
            for path in paths + entries:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
        finally:
            marker.unlink(missing_ok=True)
    (root / "install.lock").unlink(missing_ok=True)
    try:
        root.rmdir()
    except OSError:
        pass
    return result | {"scheduled_after_exit": False}
