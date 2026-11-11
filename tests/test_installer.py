"""Installation boundaries and rollback behavior without downloading dependencies."""

import gzip
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from ai_song_detection import installer


@pytest.mark.parametrize(
    "system,machine,expected",
    [
        ("Darwin", "arm64", "darwin-arm64"),
        ("Darwin", "x86_64", "darwin-x64"),
        ("Windows", "AMD64", "win32-x64"),
    ],
)
def test_supported_installer_platforms(system, machine, expected):
    assert installer.platform_key(system, machine) == expected


def test_unsupported_platform_is_explicit():
    with pytest.raises(installer.InstallError, match="supports"):
        installer.platform_key("Linux", "x86_64")


def test_download_verifies_cache_and_rejects_bad_checksum(tmp_path, monkeypatch):
    destination = tmp_path / "asset.gz"
    payload = b"downloaded content"
    expected = hashlib.sha256(payload).hexdigest()

    class Response(io.BytesIO):
        url = "https://example.test/asset"

    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: Response(payload))
    assert (
        installer.download("https://example.test/asset", expected, destination).read_bytes()
        == payload
    )
    monkeypatch.setattr(
        installer.urllib.request, "urlopen", lambda *a, **k: pytest.fail("cache miss")
    )
    installer.download("https://example.test/asset", expected, destination)
    monkeypatch.setattr(installer.urllib.request, "urlopen", lambda *a, **k: Response(b"different"))
    with pytest.raises(installer.InstallError, match="Checksum verification"):
        installer.download("https://example.test/asset", "0" * 64, destination)
    assert destination.read_bytes() == payload
    assert not destination.with_suffix(".gz.part").exists()


def test_failed_extraction_keeps_previous_binary(tmp_path, monkeypatch):
    archive, destination = tmp_path / "file.gz", tmp_path / "ffmpeg"
    archive.write_bytes(gzip.compress(b"x" * 100))
    destination.write_bytes(b"previous")
    monkeypatch.setattr(installer, "MAX_BINARY_BYTES", 20)
    with pytest.raises(installer.InstallError, match="size limit"):
        installer.decompress(archive, destination)
    assert destination.read_bytes() == b"previous"
    assert not (tmp_path / "ffmpeg.part").exists()


def source_fixture(tmp_path):
    source = tmp_path / "Source Folder"
    for name in installer.PAYLOAD:
        path = source / name
        if name in {"src", "third_party", "install"}:
            path.mkdir(parents=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
    (source / "src/app.py").write_text("original")
    model = source / "src/ai_song_detection/assets/ai_music_detector.onnx"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"original model")
    (source / "install/dependencies.json").write_text(
        json.dumps({"uv_version": "0.13.5", "python_version": "3.12"})
    )
    (source / "private.wav").write_bytes(b"private audio")
    (source / ".env").write_text("PRIVATE=value")
    (source / "src/__pycache__").mkdir()
    (source / "src/__pycache__/app.pyc").write_bytes(b"generated")
    return source


def test_payload_only_copies_application_files(tmp_path):
    source = source_fixture(tmp_path)
    paths = [relative.as_posix() for _, relative in installer.payload_files(source)]
    assert "src/app.py" in paths
    assert "private.wav" not in paths
    assert ".env" not in paths
    assert not any("__pycache__" in path for path in paths)
    before = installer.payload_digest(source)
    (source / "private.wav").write_bytes(b"changed private audio")
    assert installer.payload_digest(source) == before


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    source = source_fixture(tmp_path)
    root, desktop = tmp_path / "Installed App", tmp_path / "Desktop"
    uv = tmp_path / "uv"
    uv.write_text("fake bootstrap")
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if "sync" in command:
            release = Path(command[command.index("--project") + 1])
            python = release / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("private python")
        return subprocess.CompletedProcess(command, 0, stdout="uv 0.13.5\n")

    monkeypatch.setattr(installer, "platform_key", lambda: "darwin-arm64")
    monkeypatch.setattr(installer.platform, "mac_ver", lambda: ("26.0", ("", "", ""), "arm64"))
    monkeypatch.setattr(installer, "prepare_ffmpeg", lambda root, *a: root / "private-audio/bin")
    monkeypatch.setattr(installer, "run", run)
    return source, uv, root, desktop, commands


def test_install_is_self_contained_and_same_version_does_not_resync(fake_install):
    source, uv, root, desktop, commands = fake_install
    result = installer.install(source, uv, root, desktop, launch=False)
    wrapper = root / "bin/ai-song-detection"
    assert str(source) not in wrapper.read_text()
    assert str(result["python"]) in wrapper.read_text()
    assert (desktop / "AI Song Detection.command").is_file()
    assert (desktop / "Stop AI Song Detection.command").is_file()
    assert (Path(result["release"]) / "src/app.py").read_text() == "original"
    installer.install(source, uv, root, desktop, launch=False)
    assert sum("sync" in command for command in commands) == 1


def test_failed_upgrade_retains_previous_current_version(fake_install, monkeypatch):
    source, uv, root, desktop, _ = fake_install
    previous = installer.install(source, uv, root, desktop, launch=False)
    wrapper = (root / "bin/ai-song-detection").read_text()
    original_entries = installer.install_entries
    (source / "src/app.py").write_text("new version")

    def fail_candidate(root, desktop, python, tools, windows):
        if str(python) != previous["python"]:
            # Simulate failure after the main wrapper was already changed.
            installer.write_atomic(root / "bin/ai-song-detection", "broken")
            raise OSError("Desktop is not writable")
        return original_entries(root, desktop, python, tools, windows)

    monkeypatch.setattr(installer, "install_entries", fail_candidate)
    with pytest.raises(OSError, match="not writable"):
        installer.install(source, uv, root, desktop, launch=False)
    assert json.loads((root / "current.json").read_text()) == previous
    assert (root / "bin/ai-song-detection").read_text() == wrapper
    assert Path(previous["python"]).is_file()


def test_corrupt_model_reinstall_uses_clean_release_and_preserves_old_files(fake_install):
    source, uv, root, desktop, commands = fake_install
    previous = installer.install(source, uv, root, desktop, launch=False)
    damaged = Path(previous["release"]) / "src/ai_song_detection/assets/ai_music_detector.onnx"
    damaged.write_bytes(b"damaged model")
    repaired = installer.install(source, uv, root, desktop, launch=False)
    assert repaired["release"] != previous["release"]
    assert repaired["source_sha256"] == previous["source_sha256"]
    assert damaged.read_bytes() == b"damaged model"
    assert (
        Path(repaired["release"]) / "src/ai_song_detection/assets/ai_music_detector.onnx"
    ).read_bytes() == b"original model"
    assert any("launcher import stop" in " ".join(command) for command in commands)
    assert json.loads((root / "current.json").read_text()) == repaired
    # A later ordinary reinstall reuses the repaired release instead of rebuilding again.
    installer.install(source, uv, root, desktop, launch=False)
    assert sum("sync" in command for command in commands) == 2


def test_interrupted_candidate_retries_without_losing_current_version(fake_install, monkeypatch):
    source, uv, root, desktop, commands = fake_install
    previous = installer.install(source, uv, root, desktop, launch=False)
    (source / "src/app.py").write_text("upgrade")
    real_fake_run = installer.run

    def interrupted(command, **kwargs):
        if "sync" in command:
            raise installer.InstallError("Simulated interrupted installation")
        return real_fake_run(command, **kwargs)

    monkeypatch.setattr(installer, "run", interrupted)
    with pytest.raises(installer.InstallError, match="interrupted"):
        installer.install(source, uv, root, desktop, launch=False)
    assert json.loads((root / "current.json").read_text()) == previous
    assert Path(previous["python"]).is_file()
    monkeypatch.setattr(installer, "run", real_fake_run)
    installed = installer.install(source, uv, root, desktop, launch=False)
    assert installed["release"] != previous["release"]
    assert json.loads((root / "current.json").read_text()) == installed
    assert sum("sync" in command for command in commands) == 2


def test_windows_wrappers_enable_utf8_before_unicode_paths():
    python = Path("C:/Users/中文 User/private/python.exe")
    wrapper = Path("C:/Users/中文 User/cli.cmd")
    text = installer.command_text(
        python,
        Path("C:/Users/中文 User/audio"),
        Path("C:/Users/中文 User/state"),
        True,
    )
    assert text.index("chcp 65001 >nul") < text.index("中文")
    assert "if defined AI_PREVIOUS_CODEPAGE chcp %AI_PREVIOUS_CODEPAGE% >nul" in text
    assert f'"{python}" -m ai_song_detection %*' in text
    shortcut = installer.shortcut_text(wrapper, "launch", True)
    assert shortcut.splitlines()[1] == "chcp 65001 >nul"
    assert f'call "{wrapper}" launch' in shortcut


def test_audio_bundle_repair_preserves_old_directory(tmp_path, monkeypatch):
    source = tmp_path / "archive-source"
    name = "ffmpeg-test-lgpl"
    bundle = source / name
    (bundle / "bin").mkdir(parents=True)
    (bundle / "LICENSES").mkdir()
    (bundle / "BUILDINFO.txt").write_text("source build information")
    (bundle / "LICENSES/license.txt").write_text("license")
    for binary in ("ffmpeg", "ffprobe"):
        (bundle / "bin" / binary).write_text("original " + binary)
    archive = tmp_path / "bundle.tar.xz"
    with tarfile.open(archive, "w:xz") as tar:
        tar.add(bundle, arcname=name)
    specification = {
        "directory": name,
        "url": "https://example.test/bundle.tar.xz",
        "sha256": installer.digest(archive),
    }
    root = tmp_path / "installed"
    root.mkdir()
    monkeypatch.setattr(installer, "download", lambda *args: archive)
    monkeypatch.setattr(
        installer,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout="ffmpeg LGPL build"
        ),
    )
    first = installer.prepare_ffmpeg_bundle(root, specification)
    (root / "current.json").write_text(json.dumps({"ffmpeg_directory": str(first)}))
    (first / "ffmpeg").write_text("corrupt")
    repaired = installer.prepare_ffmpeg_bundle(root, specification)
    assert repaired != first
    assert (first / "ffmpeg").read_text() == "corrupt"
    assert (repaired / "ffmpeg").read_text() == "original ffmpeg"
    (root / "current.json").write_text(json.dumps({"ffmpeg_directory": str(repaired)}))
    assert installer.prepare_ffmpeg_bundle(root, specification) == repaired
