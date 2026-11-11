"""Create and restore a platform-specific, offline installation folder.

This module also becomes the standalone restore.py in a bundle. Its restore path
uses only the standard library until every copied component has been verified.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shlex
import shutil
import stat
import sys
import tempfile
from pathlib import Path, PurePosixPath

COMPONENTS = ("bootstrap", "runtime", "tools", "downloads", "cache")
MANIFEST = "bundle-manifest.json"
SCHEMA_VERSION = 1


def _desktop_metadata(path: Path) -> bool:
    return path.name in {".DS_Store", "Thumbs.db", "desktop.ini"} or path.name.startswith("._")


class BundleError(RuntimeError):
    """A bundle cannot be safely created or restored."""


def _digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as incoming:
        for block in iter(lambda: incoming.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def _platform_key() -> str:
    system, machine = platform.system(), platform.machine().lower()
    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        return "darwin-arm64"
    if system == "Darwin" and machine in {"x86_64", "amd64"}:
        return "darwin-x64"
    if system == "Windows" and machine in {"x86_64", "amd64"}:
        return "win32-x64"
    raise BundleError("Offline bundles support Apple Silicon/Intel Macs and x64 Windows.")


def _copy_tree(
    source: Path,
    destination: Path,
    boundary: Path,
    ancestors: tuple = (),
    excluded: frozenset[Path] = frozenset(),
) -> None:
    """Dereference only links contained in the component being copied."""
    try:
        resolved = source.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BundleError("A bundle component contains a broken or cyclic symbolic link.") from exc
    if not resolved.is_relative_to(boundary):
        raise BundleError("A bundle component contains a symbolic link outside its directory.")
    if resolved in excluded:
        return
    if resolved in ancestors:
        raise BundleError("A bundle component contains a cyclic symbolic link.")
    if resolved.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for child in sorted(resolved.iterdir()):
            _copy_tree(child, destination / child.name, boundary, (*ancestors, resolved), excluded)
        shutil.copystat(resolved, destination)
    elif resolved.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resolved, destination)
    else:
        raise BundleError("A bundle component contains a file that cannot be copied.")


def _inventory(root: Path) -> dict:
    inventory = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise BundleError("Offline bundles must not contain symbolic links.")
        if path.is_file() and _desktop_metadata(path):
            continue
        if path.is_file() and path != root / MANIFEST:
            inventory[path.relative_to(root).as_posix()] = {
                "sha256": _digest(path),
                "size": path.stat().st_size,
                "mode": stat.S_IMODE(path.stat().st_mode),
            }
        elif not path.is_dir() and not path.is_file():
            raise BundleError("The bundle contains an unsupported file type.")
    return inventory


def _cache_exclusions(cache: Path) -> frozenset[Path]:
    """Omit machine-specific interpreter/build records and old editable app wheels."""
    uv_cache = cache / "uv"
    excluded = {
        path.resolve()
        for pattern in ("builds-*", "interpreter-*", "sdists-*/editable")
        for path in uv_cache.glob(pattern)
    }
    excluded.update(
        path.parent.resolve()
        for path in uv_cache.glob("archive-*/*/_editable_impl_ai_song_detection.pth")
    )
    return frozenset(excluded)


def _relative_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or "\\" in name or ":" in name:
        raise BundleError("The bundle manifest contains an invalid file path.")
    relative = PurePosixPath(name)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.parts
        or relative.as_posix() != name
    ):
        raise BundleError("The bundle manifest contains an invalid file path.")
    path = root.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(root):
        raise BundleError("The bundle manifest contains an escaping file path.")
    return path


def verify(directory: Path) -> dict:
    """Verify every component before copying files or loading application code."""
    root = directory.resolve()
    manifest_path = root / MANIFEST
    if manifest_path.is_symlink():
        raise BundleError("The bundle manifest must be a regular file.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BundleError("The offline bundle manifest is missing or unreadable.") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise BundleError("This offline bundle format is not supported.")
    if manifest.get("platform") != _platform_key():
        raise BundleError(
            "This offline bundle was created for a different operating system or CPU."
        )
    expected = manifest.get("files")
    if not isinstance(expected, dict) or not expected:
        raise BundleError("The offline bundle has no component hashes.")
    for name, information in expected.items():
        path = _relative_file(root, name)
        if not isinstance(information, dict) or not path.is_file() or path.is_symlink():
            raise BundleError(f"A bundle component is missing or invalid: {name}")
        if not isinstance(information.get("mode"), int):
            raise BundleError(f"A bundle component has invalid permissions metadata: {name}")
        if path.stat().st_size != information.get("size") or _digest(path) != information.get(
            "sha256"
        ):
            raise BundleError(f"Bundle checksum verification failed: {name}")
    actual = _inventory(root)
    if actual.keys() != expected.keys():
        raise BundleError("The bundle contains files not listed in its component manifest.")
    for key in ("python", "uv"):
        if manifest.get(key) not in expected:
            raise BundleError(f"The offline bundle is missing its private {key} executable.")
    if not all((root / "data" / name).is_dir() for name in COMPONENTS):
        raise BundleError("The offline bundle is missing a required installation component.")
    if "source/src/ai_song_detection/installer.py" not in expected:
        raise BundleError("The offline bundle is missing its verified application installer.")
    return manifest


def _bootstrap_paths(root: Path, source: Path, target: str) -> tuple[Path, Path]:
    specification = json.loads((source / "install/dependencies.json").read_text(encoding="utf-8"))
    suffix = ".exe" if target.startswith("win32") else ""
    uv = (
        root
        / "bootstrap"
        / f"uv-{specification['uv_version']}-{specification['platforms'][target]['uv_target']}"
        / ("uv" + suffix)
    )
    python_root = root / "runtime/python"
    candidates = sorted(
        child / ("python.exe" if suffix else "bin/python3.12")
        for child in python_root.iterdir()
        if child.name.startswith("cpython-3.12.") and child.is_dir() and not child.is_symlink()
    )
    candidates = [path for path in candidates if path.is_file()]
    if not uv.is_file() or not candidates:
        raise BundleError(
            "The private installer or Python 3.12 is missing. Repair the installation first."
        )
    return candidates[-1], uv


def _launchers(root: Path, target: str, python_relative: str) -> None:
    python_hash = _digest(root / python_relative)
    restore_hash = _digest(root / "restore.py")
    if target.startswith("darwin"):
        script = (
            "#!/bin/sh\nset -eu\n"
            'bundle_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
            'cd "$bundle_dir"\n'
            + f"python_relative={shlex.quote(python_relative)}\n"
            + f"python_expected={python_hash}\nrestore_expected={restore_hash}\n"
            + 'python_actual=$(shasum -a 256 "$python_relative" | cut -d " " -f 1)\n'
            + 'restore_actual=$(shasum -a 256 restore.py | cut -d " " -f 1)\n'
            + 'if [ "$python_actual" != "$python_expected" ] || [ "$restore_actual" != "$restore_expected" ]; then\n'
            + "  printf '%s\\n' 'Bundle bootstrap checksum verification failed. Nothing was executed.' >&2\n  exit 1\nfi\n"
            + 'exec "$bundle_dir/$python_relative" -I -B -X utf8 "$bundle_dir/restore.py" "$@"\n'
        )
        entry = root / "Restore.command"
        entry.write_text(script, encoding="utf-8")
        entry.chmod(0o700)
    else:
        # PowerShell reads Unicode paths directly; CMD only forwards the relative script.
        powershell = (
            "$ErrorActionPreference = 'Stop'\ntry {\n"
            + f"    $python = Join-Path $PSScriptRoot '{python_relative.replace('/', chr(92))}'\n"
            + "    $restore = Join-Path $PSScriptRoot 'restore.py'\n"
            + f"    if ((Get-FileHash -LiteralPath $python -Algorithm SHA256).Hash.ToLowerInvariant() -ne '{python_hash}') {{ throw 'Private Python checksum verification failed.' }}\n"
            + f"    if ((Get-FileHash -LiteralPath $restore -Algorithm SHA256).Hash.ToLowerInvariant() -ne '{restore_hash}') {{ throw 'Restore script checksum verification failed.' }}\n"
            + "    & $python -I -B -X utf8 $restore @args\n    exit $LASTEXITCODE\n"
            + "} catch { Write-Error $_; exit 1 }\n"
        )
        (root / "restore.ps1").write_text(powershell, encoding="utf-8-sig")
        (root / "Restore.cmd").write_text(
            "@echo off\nsetlocal DisableDelayedExpansion\nchcp 65001 >nul\n"
            'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0restore.ps1" %*\n'
            'set "AI_RESTORE_RESULT=%errorlevel%"\n'
            'if not "%AI_RESTORE_RESULT%"=="0" pause\nexit /b %AI_RESTORE_RESULT%\n',
            encoding="utf-8",
            newline="\r\n",
        )


def create(output: Path) -> dict:
    """Export the current private installation without user audio or service state."""
    from . import installer

    root = installer.install_directory().resolve()
    destination = output.expanduser().absolute()
    if destination.is_symlink():
        raise BundleError("The offline bundle output must not be a symbolic link.")
    destination = destination.resolve()
    if destination.is_relative_to(root) or root.is_relative_to(destination):
        raise BundleError("Choose an offline bundle output outside the private installation.")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise BundleError("The offline bundle output must be a new or empty directory.")
    try:
        current = json.loads((root / "current.json").read_text(encoding="utf-8"))
        source = Path(current["release"]).resolve()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BundleError("No complete private installation was found. Run Install first.") from exc
    target = _platform_key()
    if source.parent != root / "releases" or current.get("platform") != target:
        raise BundleError("The current installation metadata does not match this computer.")
    if not installer.payload_matches(source, current.get("source_sha256", "")):
        raise BundleError(
            "The installed application payload is damaged. Repair it before exporting."
        )
    private_python, uv = _bootstrap_paths(root, source, target)
    if not all((root / name).is_dir() and not (root / name).is_symlink() for name in COMPONENTS):
        raise BundleError(
            "A private installation component is missing or invalid. Run Install again."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Publish only a complete bundle; an interrupted export never looks ready to restore.
    with (
        installer.install_lock(root),
        tempfile.TemporaryDirectory(prefix=".ai-song-bundle-", dir=destination.parent) as temporary,
    ):
        stage = Path(temporary) / "bundle"
        stage.mkdir()
        for path, relative in installer.payload_files(source):
            copied = stage / "source" / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, copied)
        for component in COMPONENTS:
            boundary = (root / component).resolve()
            excluded = _cache_exclusions(boundary) if component == "cache" else frozenset()
            _copy_tree(boundary, stage / "data" / component, boundary, excluded=excluded)
        shutil.copy2(Path(__file__).resolve(), stage / "restore.py")
        python_relative = "data/" + private_python.relative_to(root).as_posix()
        uv_relative = "data/" + uv.relative_to(root).as_posix()
        _launchers(stage, target, python_relative)
        (stage / "OFFLINE-README.txt").write_text(
            "AI Song Detection offline installer\n\n"
            f"Platform: {target}. Use the same operating system and CPU architecture.\n"
            "Copy this entire folder, then open Restore.command (Mac) or Restore.cmd (Windows).\n"
            "No system Python, Git, Homebrew, or network download is required.\n"
            "The destination must be a new or empty installation directory.\n"
            "AI_SONG_DETECTION_INSTALL_DIR and AI_SONG_DETECTION_DESKTOP_DIR override the defaults.\n"
            "Use --no-launch to install without opening the browser.\n"
            "This folder contains dependencies and the model, not audio, reports, service tokens, or a copied virtual environment.\n"
            "Component hashes detect corruption; they are not a publisher signature.\n",
            encoding="utf-8",
        )
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "platform": target,
            "source_sha256": current["source_sha256"],
            "python": python_relative,
            "uv": uv_relative,
            "files": _inventory(stage),
        }
        (stage / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        verify(stage)
        if destination.exists():
            destination.rmdir()
        stage.replace(destination)
    return {
        "status": "created",
        "output": str(destination),
        "platform": target,
        "manifest": str(destination / MANIFEST),
        "files": len(manifest["files"]),
        "size_bytes": sum(item["size"] for item in manifest["files"].values()),
        "restore_entry": str(
            destination / ("Restore.cmd" if target.startswith("win32") else "Restore.command")
        ),
    }


def _load_installer(source: Path):
    specification = importlib.util.spec_from_file_location(
        "ai_song_detection_offline_installer", source / "src/ai_song_detection/installer.py"
    )
    if specification is None or specification.loader is None:
        raise BundleError("The verified application installer could not be loaded.")
    module = importlib.util.module_from_spec(specification)
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        specification.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def restore(
    directory: Path,
    install_dir: Path | None = None,
    desktop_dir: Path | None = None,
    *,
    launch: bool = True,
) -> dict:
    """Rebuild a relocated installation from verified caches, with no download fallback."""
    directory = directory.resolve()
    manifest = verify(directory)
    installer = _load_installer(directory / "source")
    root = (install_dir or installer.install_directory()).expanduser().absolute()
    if root.is_symlink():
        raise BundleError("The installation destination must not be a symbolic link.")
    root = root.resolve()
    desktop = (desktop_dir or installer.desktop_directory()).expanduser().resolve()
    if root.is_relative_to(directory) or directory.is_relative_to(root):
        raise BundleError("Restore into a directory outside the offline bundle.")
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise BundleError(
            "Restore requires a new or empty installation directory; existing files were left untouched."
        )
    root.mkdir(parents=True, exist_ok=True)
    for component in COMPONENTS:
        shutil.copytree(directory / "data" / component, root / component)
    for name, metadata in manifest["files"].items():
        if name.startswith("data/"):
            installed_path = root.joinpath(*PurePosixPath(name).parts[1:])
            installed_path.chmod(metadata.get("mode", 0o600) & 0o777)
    uv = root.joinpath(*PurePosixPath(manifest["uv"]).parts[1:])

    def cached_download(url, expected, destination):
        if destination.is_file() and _digest(destination) == expected:
            return destination
        raise BundleError(
            "The offline bundle is missing a verified cached dependency: " + destination.name
        )

    installer.download = cached_download
    offline = {
        "UV_OFFLINE": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "HTTP_PROXY": "http://127.0.0.1:1",
        "HTTPS_PROXY": "http://127.0.0.1:1",
        "ALL_PROXY": "http://127.0.0.1:1",
    }
    previous = {name: os.environ.get(name) for name in offline}
    try:
        os.environ.update(offline)
        return installer.install(directory / "source", uv, root, desktop, launch=launch)
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore AI Song Detection without network downloads"
    )
    parser.add_argument("--install-dir", type=Path)
    parser.add_argument("--desktop-dir", type=Path)
    parser.add_argument("--no-launch", action="store_true")
    arguments = parser.parse_args()
    try:
        restore(
            Path(__file__).resolve().parent,
            arguments.install_dir,
            arguments.desktop_dir,
            launch=not arguments.no_launch,
        )
    except (BundleError, OSError, ValueError, RuntimeError) as exc:
        print("Offline restore failed: " + str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
