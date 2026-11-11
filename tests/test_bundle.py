"""Offline bundle integrity, relocation, privacy and no-download boundaries."""

import json
import os
from types import SimpleNamespace

import pytest

from ai_song_detection import bundle, installer


@pytest.fixture
def installed(tmp_path, monkeypatch):
    root = tmp_path / "Original App 中文"
    source = root / "releases/current-release"
    for name in installer.PAYLOAD:
        path = source / name
        if name in {"src", "third_party", "install"}:
            path.mkdir(parents=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("application " + name)
    (source / "install/dependencies.json").write_text(
        json.dumps(
            {"uv_version": "test", "platforms": {"darwin-arm64": {"uv_target": "test-target"}}}
        )
    )
    (source / "src/ai_song_detection").mkdir(parents=True)
    (source / "src/ai_song_detection/installer.py").write_text("# verified installer fixture\n")
    (source / "src/ai_song_detection/model.onnx").write_bytes(b"model")
    (source / ".venv").mkdir()
    (source / ".venv/private-old-environment").write_text("absolute old path")
    (source / "private-song.wav").write_bytes(b"never copy this audio")
    (source / "installed.json").write_text("old absolute paths")
    for component in bundle.COMPONENTS:
        (root / component).mkdir(parents=True)
    python = root / "runtime/python/cpython-3.12.15-macos-aarch64-none/bin/python3.12"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"private relocatable python")
    python.chmod(0o700)
    uv = root / "bootstrap/uv-test-test-target/uv"
    uv.parent.mkdir(parents=True)
    uv.write_bytes(b"private uv")
    uv.chmod(0o700)
    (root / "tools/ffmpeg").write_bytes(b"private ffmpeg")
    (root / "downloads/audio-tool.tar.xz").write_bytes(b"cached tool archive")
    wheel = root / "cache/uv/wheels/dependency.whl"
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"cached dependency")
    (root / "state").mkdir()
    (root / "state/instance.json").write_text('{"control_token":"never copy"}')
    (root / "reports").mkdir()
    (root / "reports/private-report.json").write_text("private report")
    (root / "releases/old-release").mkdir()
    (root / "releases/old-release/old.py").write_text("old release")
    current = {
        "release": str(source),
        "platform": "darwin-arm64",
        "source_sha256": installer.payload_digest(source),
    }
    (root / "current.json").write_text(json.dumps(current))
    monkeypatch.setattr(installer, "install_directory", lambda: root)
    monkeypatch.setattr(bundle, "_platform_key", lambda: "darwin-arm64")
    return root, source, tmp_path / "Portable Bundle 中文"


def test_bundle_is_relocatable_and_omits_audio_state_reports_and_virtualenv(installed, tmp_path):
    root, _, destination = installed
    result = bundle.create(destination)
    assert result["status"] == "created"
    manifest = bundle.verify(destination)
    names = set(manifest["files"])
    assert "data/downloads/audio-tool.tar.xz" in names
    assert "source/src/ai_song_detection/model.onnx" in names
    assert not any(
        ".venv" in name or "private-song" in name or "old-release" in name for name in names
    )
    assert not any(name.startswith(("data/state", "data/reports")) for name in names)
    assert "current.json" not in names
    launcher = (destination / "Restore.command").read_text()
    assert str(root) not in launcher
    assert "shasum -a 256" in launcher
    assert ' -I -B -X utf8 "$bundle_dir/restore.py"' in launcher
    moved = tmp_path / "Moved Folder 中文"
    destination.rename(moved)
    assert bundle.verify(moved)["source_sha256"] == manifest["source_sha256"]
    assert not any(path.is_symlink() for path in moved.rglob("*"))


def test_safe_internal_links_are_dereferenced_and_external_links_are_rejected(installed, tmp_path):
    root, _, destination = installed
    (root / "tools/ffmpeg-alias").symlink_to(root / "tools/ffmpeg")
    bundle.create(destination)
    assert (destination / "data/tools/ffmpeg-alias").read_bytes() == b"private ffmpeg"
    assert not (destination / "data/tools/ffmpeg-alias").is_symlink()
    outside = tmp_path / "private.txt"
    outside.write_text("private external bytes")
    (root / "tools/escape").symlink_to(outside)
    with pytest.raises(bundle.BundleError, match="outside"):
        bundle.create(tmp_path / "Rejected")
    assert not (tmp_path / "Rejected").exists()


def test_cyclic_directory_links_are_rejected(installed, tmp_path):
    root, _, _ = installed
    (root / "tools/loop").symlink_to(root / "tools", target_is_directory=True)
    with pytest.raises(bundle.BundleError, match="cyclic"):
        bundle.create(tmp_path / "Rejected")


def test_editable_app_and_machine_specific_cache_entries_are_not_exported(installed):
    root, _, destination = installed
    for name in (
        "builds-v0/stale",
        "interpreter-v4/stale",
        "sdists-v10/editable/path/app.whl",
        "archive-v0/old-app/_editable_impl_ai_song_detection.pth",
    ):
        path = root / "cache/uv" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(root / "releases/old-release"))
    bundle.create(destination)
    assert not (destination / "data/cache/uv/builds-v0").exists()
    assert not (destination / "data/cache/uv/interpreter-v4").exists()
    assert not (destination / "data/cache/uv/sdists-v10/editable").exists()
    assert not (destination / "data/cache/uv/archive-v0/old-app").exists()
    assert (destination / "data/cache/uv/wheels/dependency.whl").is_file()


def test_corruption_is_detected_before_application_code_or_destination_writes(
    installed, tmp_path, monkeypatch
):
    _, _, destination = installed
    bundle.create(destination)
    (destination / "data/tools/ffmpeg").write_bytes(b"damaged")
    target = tmp_path / "New Installation"
    monkeypatch.setattr(
        bundle, "_load_installer", lambda source: pytest.fail("executed unverified code")
    )
    with pytest.raises(bundle.BundleError, match="checksum"):
        bundle.restore(destination, target, tmp_path / "Desktop", launch=False)
    assert not target.exists()


def test_extra_files_platform_mismatch_and_escaping_manifest_paths_are_rejected(
    installed, monkeypatch
):
    _, _, destination = installed
    bundle.create(destination)
    extra = destination / "extra.exe"
    extra.write_bytes(b"unverified")
    with pytest.raises(bundle.BundleError, match="not listed"):
        bundle.verify(destination)
    extra.unlink()
    monkeypatch.setattr(bundle, "_platform_key", lambda: "win32-x64")
    with pytest.raises(bundle.BundleError, match="different operating system"):
        bundle.verify(destination)
    monkeypatch.setattr(bundle, "_platform_key", lambda: "darwin-arm64")
    metadata = json.loads((destination / bundle.MANIFEST).read_text())
    metadata["files"]["../escape"] = {"sha256": "0" * 64, "size": 1, "mode": 0o600}
    (destination / bundle.MANIFEST).write_text(json.dumps(metadata))
    with pytest.raises(bundle.BundleError, match="invalid file path"):
        bundle.verify(destination)


def test_restore_rebuilds_at_final_location_offline_and_refuses_network_fallback(
    installed, tmp_path, monkeypatch
):
    _, _, destination = installed
    bundle.create(destination)
    target, desktop = tmp_path / "Restored App 中文", tmp_path / "New Desktop 中文"
    calls = []
    fake = SimpleNamespace()

    def install(source, uv, root, entries, *, launch):
        calls.append((source, uv, root, entries, launch))
        assert root == target
        assert uv.is_relative_to(target / "bootstrap")
        assert not (root / "current.json").exists()
        assert not (root / "releases").exists(), "a relocated virtualenv must not be copied"
        assert os.environ["UV_OFFLINE"] == "1"
        assert os.environ["UV_PYTHON_DOWNLOADS"] == "never"
        assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:1"
        cached = root / "downloads/audio-tool.tar.xz"
        assert fake.download("https://unused.test", bundle._digest(cached), cached) == cached
        with pytest.raises(bundle.BundleError, match="missing a verified cached"):
            fake.download("https://must-not-download.test", "0" * 64, root / "downloads/missing")
        return {"status": "installed", "release": str(root / "releases/fresh")}

    fake.install = install
    monkeypatch.setattr(bundle, "_load_installer", lambda source: fake)
    monkeypatch.setenv("UV_OFFLINE", "previous-value")
    result = bundle.restore(destination, target, desktop, launch=False)
    assert result["status"] == "installed"
    assert len(calls) == 1
    assert os.environ["UV_OFFLINE"] == "previous-value"
    assert (target / "tools/ffmpeg").read_bytes() == b"private ffmpeg"
    with pytest.raises(bundle.BundleError, match="new or empty"):
        bundle.restore(destination, target, desktop, launch=False)
    assert len(calls) == 1


def test_create_refuses_nonempty_or_nested_destinations_without_removing_files(installed):
    root, _, destination = installed
    destination.mkdir()
    retained = destination / "keep.txt"
    retained.write_text("keep")
    with pytest.raises(bundle.BundleError, match="new or empty"):
        bundle.create(destination)
    assert retained.read_text() == "keep"
    with pytest.raises(bundle.BundleError, match="outside"):
        bundle.create(root / "cache/output")


def test_windows_launcher_is_relative_utf8_and_verifies_before_python_execution(tmp_path):
    root = tmp_path / "Windows Bundle 中文"
    python = root / "data/runtime/python/cpython-3.12.15-windows-x86_64-none/python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"python")
    (root / "restore.py").write_text("# restore")
    relative = python.relative_to(root).as_posix()
    bundle._launchers(root, "win32-x64", relative)
    script = (root / "restore.ps1").read_text(encoding="utf-8-sig")
    assert script.index("Get-FileHash") < script.index("& $python -I -B -X utf8 $restore")
    assert str(root) not in script
    assert "$PSScriptRoot" in script
    batch = (root / "Restore.cmd").read_bytes()
    assert b'"%~dp0restore.ps1"' in batch
    assert b"chcp 65001" in batch
    assert b"\n" not in batch.replace(b"\r\n", b"")


def test_loading_verified_installer_does_not_modify_reusable_bundle(installed):
    _, _, destination = installed
    bundle.create(destination)
    original = bundle.verify(destination)
    bundle._load_installer(destination / "source")
    assert not (destination / "source/src/ai_song_detection/__pycache__").exists()
    assert bundle.verify(destination) == original


def test_finder_and_explorer_metadata_do_not_break_reusable_installer(installed):
    _, _, destination = installed
    bundle.create(destination)
    manifest = bundle.verify(destination)
    for name in (".DS_Store", "._Restore.command", "Thumbs.db", "desktop.ini"):
        (destination / name).write_bytes(b"desktop metadata")
    assert bundle.verify(destination) == manifest
