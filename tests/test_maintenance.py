"""Maintenance must preserve unknown files and never trust arbitrary deletion paths."""

import io
import json
import os
import stat
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

from ai_song_detection import installer, maintenance


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root, desktop = tmp_path / "App", tmp_path / "Desktop"
    release = root / "releases/current"
    python = release / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("private runtime")
    desktop.mkdir()
    info = {
        "release": str(release),
        "python": str(python),
        "ffmpeg_directory": str(root / "tools/bin"),
        "platform": "darwin-arm64",
        "desktop": str(desktop),
        "source_sha256": "a" * 64,
    }
    (release / "installed.json").write_text(json.dumps(info))
    (root / "current.json").write_text(json.dumps(info))
    (root / "bin").mkdir()
    (root / "bin/ai-song-detection").write_text("#!/bin/sh\n")
    monkeypatch.setenv("AI_SONG_DETECTION_INSTALL_DIR", str(root))
    monkeypatch.setattr(maintenance.launcher, "status", lambda: {"status": "stopped"})
    monkeypatch.setattr(maintenance.launcher, "stop", lambda: {"status": "stopped"})
    return root, desktop, info


def test_cleanup_is_preview_and_protects_current_and_unmarked(installed):
    root, _, info = installed
    old = root / "releases/old"
    old.mkdir()
    (old / "installed.json").write_text(
        json.dumps(info | {"release": str(old), "python": str(old / ".venv/bin/python")})
    )
    (old / "file").write_bytes(b"123")
    unmarked = root / "releases/my-notes"
    unmarked.mkdir()
    (unmarked / "installed.json").write_text("{}")
    preview = maintenance.cleanup(keep=1)
    assert [item["path"] for item in preview["items"]] == [str(old)]
    assert old.exists()
    applied = maintenance.cleanup(keep=1, apply=True)
    assert applied["size_bytes"] == preview["size_bytes"]
    assert not old.exists()
    assert unmarked.exists()
    assert (root / "releases/current").exists()


def test_cleanup_keeps_active_unknown_release_and_explicit_cache(installed, monkeypatch):
    root, _, info = installed
    old = root / "releases/old"
    old.mkdir()
    (old / "installed.json").write_text(
        json.dumps(info | {"release": str(old), "python": str(old / ".venv/bin/python")})
    )
    (root / "cache").mkdir()
    (root / "cache/unused").write_bytes(b"cache")
    monkeypatch.setattr(maintenance.launcher, "_service_lease_held", lambda: True)
    report = maintenance.cleanup(keep=1, apply=True)
    assert report["items"] == []
    assert old.exists()
    assert (root / "cache/unused").exists()
    maintenance.cleanup(keep=1, apply=True, cache=True)
    assert old.exists()
    assert not (root / "cache").exists()


def test_cleanup_can_remove_inactive_releases_when_active_source_is_identified(
    installed, monkeypatch
):
    root, _, info = installed
    active, inactive = root / "releases/active", root / "releases/inactive"
    for path in (active, inactive):
        path.mkdir()
        (path / "installed.json").write_text(
            json.dumps(info | {"release": str(path), "python": str(path / ".venv/bin/python")})
        )
    monkeypatch.setattr(
        maintenance.launcher,
        "_read_state",
        lambda directory: {"source_directory": str(active)},
    )
    monkeypatch.setattr(maintenance.launcher, "_health", lambda state: {"status": "ok"})
    report = maintenance.cleanup(keep=1, apply=True)
    assert report["service_running"] is True
    assert active.exists()
    assert not inactive.exists()
    assert Path(info["release"]).exists()


def test_maintenance_rejects_forged_release_boundary(installed, tmp_path):
    root, _, info = installed
    outside = tmp_path / "other-project"
    outside.mkdir()
    info["release"] = str(outside)
    (root / "current.json").write_text(json.dumps(info))
    with pytest.raises(maintenance.MaintenanceError, match="valid desktop installation"):
        maintenance.cleanup(apply=True)
    assert outside.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink boundary")
def test_maintenance_rejects_linked_managed_parent(installed, tmp_path):
    root, _, _ = installed
    other = tmp_path / "other-tools"
    other.mkdir()
    (other / "private").write_text("preserve")
    (root / "tools").symlink_to(other, target_is_directory=True)
    with pytest.raises(maintenance.MaintenanceError):
        maintenance.uninstall(apply=True)
    assert (other / "private").read_text() == "preserve"


@pytest.mark.skipif(os.name == "nt", reason="native Windows remover runs after CLI exit")
def test_uninstall_preview_and_scoped_removal(installed, monkeypatch):
    root, desktop, _ = installed
    (root / "my-recording.wav").write_bytes(b"unrelated")
    owned = desktop / "AI Song Detection.command"
    owned.write_text(installer.shortcut_text(root / "bin/ai-song-detection", "launch", False))
    foreign = desktop / "Stop AI Song Detection.command"
    foreign.write_text("unrelated user script")
    stopped = []
    monkeypatch.setattr(maintenance.launcher, "stop", lambda: stopped.append(True))
    preview = maintenance.uninstall()
    assert not stopped
    assert owned.exists() and (root / "current.json").exists()
    assert str(owned) in [item["path"] for item in preview["items"]]
    maintenance.uninstall(apply=True)
    assert stopped == [True]
    assert not owned.exists()
    assert not (root / "current.json").exists()
    assert foreign.read_text() == "unrelated user script"
    assert (root / "my-recording.wav").read_bytes() == b"unrelated"


def test_uninstall_does_not_remove_when_authenticated_stop_fails(installed, monkeypatch):
    root, _, _ = installed

    def stop():
        raise maintenance.launcher.LauncherError("Unreachable owned worker")

    monkeypatch.setattr(maintenance.launcher, "stop", stop)
    with pytest.raises(maintenance.launcher.LauncherError, match="Unreachable"):
        maintenance.uninstall(apply=True)
    assert (root / "current.json").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX command-link integration")
def test_shell_setup_is_opt_in_idempotent_and_never_overwrites(installed, tmp_path):
    root, _, _ = installed
    directory = tmp_path / "commands"
    entry = directory / "ai-song-detection"
    maintenance.shell_setup(directory)
    assert entry.is_symlink()
    assert entry.resolve() == root / "bin/ai-song-detection"
    maintenance.shell_setup(directory)
    assert json.loads((root / "shell-links.json").read_text()) == [str(entry)]
    entry.unlink()
    entry.write_text("my command")
    with pytest.raises(maintenance.MaintenanceError, match="different command"):
        maintenance.shell_setup(directory)
    assert entry.read_text() == "my command"


def test_diagnostics_omits_raw_sensitive_files(installed, monkeypatch, tmp_path):
    root, _, _ = installed
    (root / "state").mkdir()
    (root / "state/instance.json").write_text('{"control_token":"secret"}')
    (root / "state/service.log").write_text("private recording.mp3 secret")
    monkeypatch.setattr(
        maintenance,
        "doctor",
        lambda: {"ok": True, "checks": [{"root": str(root), "home": str(Path.home())}]},
    )
    output = tmp_path / "diagnostics.zip"
    maintenance.diagnostics(output)
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"doctor.json", "README.txt"}
        content = archive.read("doctor.json").decode()
    assert str(root) not in content
    assert str(Path.home()) not in content
    assert "private recording" not in content
    assert "secret" not in content
    with pytest.raises(maintenance.MaintenanceError, match="already exists"):
        maintenance.diagnostics(output)


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute/file", "folder/../../escape", "C:/file", "root\\escape"]
)
def test_update_rejects_archive_path_escape(name, tmp_path):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(name, "escape")
    with pytest.raises(maintenance.MaintenanceError, match="unsafe"):
        maintenance._extract_source(payload.getvalue(), tmp_path / "extract")


def test_update_pins_commit_to_own_repository_before_install(installed, monkeypatch, tmp_path):
    root, desktop, info = installed
    source = tmp_path / "source"
    source.mkdir()
    calls = []
    commit = "b" * 40

    def fetch(url, limit):
        calls.append(url)
        return json.dumps({"sha": commit}).encode() if len(calls) == 1 else b"archive"

    monkeypatch.setattr(maintenance, "_fetch", fetch)
    monkeypatch.setattr(maintenance, "_extract_source", lambda *a: source)
    monkeypatch.setattr(maintenance, "_private_uv", lambda *a: root / "bootstrap/uv")
    monkeypatch.setattr(
        installer,
        "install",
        lambda candidate, uv, candidate_root, candidate_desktop, **kwargs: (
            info
            if (candidate, candidate_root, candidate_desktop, kwargs["launch"])
            == (source, root, desktop, False)
            else pytest.fail("wrong update boundaries")
        ),
    )
    result = maintenance.update(launch=False)
    assert calls == [
        "https://api.github.com/repos/liu-xiaoran/AI-Song-Detection/commits/main",
        "https://codeload.github.com/liu-xiaoran/AI-Song-Detection/zip/" + commit,
    ]
    assert result["commit"] == commit
    assert json.loads((root / "update.json").read_text())["commit"] == commit


def test_windows_deferred_remover_waits_for_cli_and_does_not_recurse_links(installed, monkeypatch):
    root, _, _ = installed
    commands = []
    monkeypatch.setattr(maintenance.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(maintenance.subprocess, "DETACHED_PROCESS", 8, raising=False)
    outputs = []

    def popen(command, **kwargs):
        commands.append(command)
        outputs.append(kwargs["stdout"].name)
        assert kwargs["stderr"] == subprocess.STDOUT

    monkeypatch.setattr(maintenance.subprocess, "Popen", popen)
    record = maintenance._schedule_windows_removal(root, [root / "releases"], "nonce")
    script = (record.parent / "remove.ps1").read_text(encoding="utf-8-sig")
    request = json.loads((record.parent / "request.json").read_text())
    assert request == {"root": str(root), "paths": [str(root / "releases")], "nonce": "nonce"}
    assert f"$parentPid = {os.getpid()}" in script
    assert "WaitForExit(120000)" in script
    assert "ReparsePoint" in script
    assert "if (directory) Directory.Delete(path, false);" in script
    assert (
        "foreach (string child in Directory.EnumerateFileSystemEntries(path)) Remove(child);"
        in script
    )
    assert "File.Delete(path);" in script
    assert "Directory.Delete(path, true)" not in script
    assert "Get-ChildItem" not in script
    assert "Get-Item" not in script
    assert "Remove-Item" not in script
    assert "-Recurse" not in script
    assert "uninstall-request.json" in script
    assert "finally {" in script
    assert "elapsed_seconds =" in script
    assert "attempt_errors =" in script
    assert "$status = 'completed'" in script
    assert "$status = 'failed'" in script
    assert outputs == [str(record.parent / "helper.log")]
    assert commands[0][0] == "powershell.exe"


def wait_for_removal(record, timeout=60):
    deadline = time.monotonic() + timeout
    latest = None
    while time.monotonic() < deadline:
        try:
            latest = json.loads(record.read_text(encoding="utf-8-sig"))
            if latest["status"] in {"completed", "failed"}:
                return latest
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    log = (record.parent / "helper.log").read_text(encoding="utf-8", errors="replace")
    pytest.fail(f"Windows removal helper did not finish: {latest}; log: {log}")


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows .NET and junctions")
def test_native_windows_removal_preserves_junction_target_and_handles_many_files(
    installed, tmp_path
):
    root, _, _ = installed
    target, outside = root / "owned files 中文", tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("unrelated target")
    for index in range(32):
        directory = target / f"directory-{index}"
        directory.mkdir(parents=True)
        for number in range(32):
            (directory / f"file-{number}.txt").write_text("application data")
    readonly = target / "readonly.txt"
    readonly.write_text("readonly application data")
    readonly.chmod(stat.S_IREAD)
    link = target / "external-junction"
    subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
        check=True,
        capture_output=True,
    )
    marker = root / "uninstall-request.json"
    marker.write_text('{"nonce":"native"}')
    record = maintenance._schedule_windows_removal(root, [target], "native", wait_pid=2147483647)
    result = wait_for_removal(record)
    assert result["status"] == "completed", result
    assert result["remaining"] == []
    assert result["error"] is None
    assert result["deleted"]["files"] >= 1025
    assert result["deleted"]["links"] == 1
    assert not target.exists()
    assert not marker.exists()
    assert (outside / "keep.txt").read_text() == "unrelated target"


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows PowerShell")
def test_native_windows_helper_reports_top_level_failure_without_deleting(installed):
    root, _, _ = installed
    marker = root / "uninstall-request.json"
    marker.write_text('{"nonce":"different"}')
    owned = root / "owned.txt"
    owned.write_text("keep after failed identity validation")
    record = maintenance._schedule_windows_removal(root, [owned], "expected", wait_pid=2147483647)
    result = wait_for_removal(record)
    assert result["status"] == "failed"
    assert "Uninstall request changed" in result["error"]
    assert result["remaining"] == [str(owned)]
    assert result["elapsed_seconds"] >= 0
    assert owned.is_file() and marker.is_file()
    assert "Uninstall request changed" in (record.parent / "helper.log").read_text(
        encoding="utf-8", errors="replace"
    )


def test_pending_uninstall_blocks_maintenance(installed):
    root, _, _ = installed
    (root / "uninstall-request.json").write_text('{"nonce":"pending"}')
    with pytest.raises(maintenance.MaintenanceError, match="uninstall is pending"):
        maintenance.cleanup(apply=True)
    assert (root / "current.json").exists()
