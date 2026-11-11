"""User-level desktop installation; bootstrap entry points need only the standard library."""

from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

APP_NAME = "AI Song Detection"
PAYLOAD = (
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "src",
    "third_party",
    "install",
)
IGNORED = {"__pycache__", ".DS_Store", ".pytest_cache", ".ruff_cache"}
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
MAX_BINARY_BYTES = 400 * 1024 * 1024


class InstallError(RuntimeError):
    """An installation failure that can be shown without a traceback."""


def platform_key(system: str | None = None, machine: str | None = None) -> str:
    system, machine = system or platform.system(), (machine or platform.machine()).lower()
    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        return "darwin-arm64"
    if system == "Darwin" and machine in {"x86_64", "amd64"}:
        return "darwin-x64"
    if system == "Windows" and machine in {"x86_64", "amd64"}:
        return "win32-x64"
    raise InstallError("The desktop installer supports Apple Silicon/Intel Macs and x64 Windows.")


def install_directory() -> Path:
    override = os.environ.get("AI_SONG_DETECTION_INSTALL_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / APP_NAME
    return Path.home() / "Library/Application Support" / APP_NAME


def desktop_directory() -> Path:
    override = os.environ.get("AI_SONG_DETECTION_DESKTOP_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        # Respect redirected/OneDrive desktops instead of assuming %USERPROFILE%\Desktop.
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "Desktop")
        return Path(os.path.expandvars(value))
    return Path.home() / "Desktop"


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def download(url: str, expected: str, destination: Path) -> Path:
    """Cache a fixed HTTPS asset, validating bytes before they are used."""
    if not url.startswith("https://") or len(expected) != 64:
        raise InstallError("An installer dependency has invalid provenance metadata.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and digest(destination) == expected:
        return destination
    partial = destination.with_name(destination.name + ".part")
    for attempt in range(3):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "AI-Song-Detection-Installer"}
            )
            size = 0
            with (
                urllib.request.urlopen(request, timeout=60) as response,
                partial.open("wb") as target,
            ):
                if not response.url.startswith("https://"):
                    raise InstallError("A dependency download redirected to an insecure address.")
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise InstallError("An installer download exceeded its size limit.")
                    target.write(block)
            if digest(partial) != expected:
                raise InstallError(f"Checksum verification failed for {destination.name}.")
            partial.replace(destination)
            return destination
        except (OSError, urllib.error.URLError, InstallError) as exc:
            partial.unlink(missing_ok=True)
            if isinstance(exc, InstallError) or attempt == 2:
                raise InstallError(f"Could not download {destination.name}: {exc}") from exc
            time.sleep(attempt + 1)
    raise AssertionError("Unreachable download retry state")


def decompress(source: Path, destination: Path) -> None:
    partial = destination.with_name(destination.name + ".part")
    size = 0
    try:
        with gzip.open(source, "rb") as compressed, partial.open("wb") as target:
            while block := compressed.read(1024 * 1024):
                size += len(block)
                if size > MAX_BINARY_BYTES:
                    raise InstallError("An extracted dependency exceeded its size limit.")
                target.write(block)
        partial.chmod(0o700)
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int = 600,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            env=env,
            timeout=timeout,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.STDOUT if capture else None,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        detail = getattr(exc, "stdout", None) or str(exc)
        raise InstallError(f"A setup command failed: {detail}") from exc


def prepare_ffmpeg(root: Path, manifest: dict, target: str) -> Path:
    specification = manifest["platforms"][target]
    if "ffmpeg_bundle" in specification:
        return prepare_ffmpeg_bundle(root, specification["ffmpeg_bundle"])
    release = manifest["ffmpeg_release"]
    base = f"https://github.com/eugeneware/ffmpeg-static/releases/download/{release}"
    tools_root = root / "tools"
    tools = tools_root / f"ffmpeg-{release}-{target}"
    suffix = ".exe" if target.startswith("win32") else ""
    assets = {
        "ffmpeg": f"ffmpeg-{target}",
        "ffprobe": f"ffprobe-{target}",
        "license": f"{target}.LICENSE",
        "readme": f"{target}.README",
    }
    output_names = {
        kind: ((kind + suffix) if kind in {"ffmpeg", "ffprobe"} else kind.upper())
        for kind in assets
    }
    expected_files = {output_names[kind]: specification[f"{kind}_binary_sha256"] for kind in assets}
    candidates = [tools]
    try:
        preferred = Path(json.loads((root / "current.json").read_text())["ffmpeg_directory"])
        if preferred.parent == tools_root:
            candidates.insert(0, preferred)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    matched = next((path for path in candidates if files_match(path, expected_files)), None)
    if matched:
        tools = matched
    elif tools.exists():
        tools = tools_root / (tools.name + "-repair-" + str(time.time_ns()))
    tools.mkdir(parents=True, exist_ok=True)
    downloads = {}
    for kind, name in assets.items():
        print(f"Preparing {name}...", flush=True)
        archive = download(
            f"{base}/{name}.gz",
            specification[f"{kind}_sha256"],
            root / "downloads" / f"{release}-{name}.gz",
        )
        output = tools / output_names[kind]
        # Keep installed binaries immutable: Windows locks an executable while it runs.
        if not output.exists():
            decompress(archive, output)
        if digest(output) != specification[f"{kind}_binary_sha256"]:
            raise InstallError(
                "A private audio dependency failed its integrity check: " + str(output)
            )
        downloads[kind] = {"url": f"{base}/{name}.gz", "sha256": specification[f"{kind}_sha256"]}
    configurations = []
    for executable in ("ffmpeg", "ffprobe"):
        result = run([str(tools / (executable + suffix)), "-version"], timeout=20, capture=True)
        if "--enable-nonfree" in result.stdout:
            raise InstallError(
                "The selected FFmpeg build is marked nonfree and cannot be installed."
            )
        configurations.append(result.stdout)
    (tools / "BUILD-CONFIGURATION.txt").write_text("\n\n".join(configurations), encoding="utf-8")
    (tools / "DOWNLOADS.json").write_text(
        json.dumps(
            {
                "release": release,
                "assets": downloads,
                "source_and_build_information": "https://github.com/eugeneware/ffmpeg-static/tree/"
                + release,
                "source_information": "See README and BUILD-CONFIGURATION.txt in this directory.",
                "license_information": "See LICENSE; binaries retain their upstream licenses.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return tools


def files_match(directory: Path, expected: dict[str, str]) -> bool:
    try:
        return all(
            (directory / name).is_file() and digest(directory / name) == checksum
            for name, checksum in expected.items()
        )
    except OSError:
        return False


def prepare_windows_runtime(root: Path, release: Path, specification: dict) -> Path:
    """Register the unmodified Microsoft CRT before any native Python extensions load."""
    site = release / ".venv/Lib/site-packages"
    directory = site / "ai_song_detection_vc_runtime"
    registration = site / "ai_song_detection_vc_runtime.pth"
    # .pth files must be ASCII even for Unicode Windows account/install paths.
    loader = (
        "import os; os._ai_song_detection_dll_directory = os.add_dll_directory("
        + ascii(str(directory))
        + ")\n"
    )
    expected = {name: details["sha256"] for name, details in specification["files"].items()}
    expected["LICENSE.docx"] = specification["license_sha256"]
    if directory.exists():
        if (
            files_match(directory, expected)
            and registration.is_file()
            and registration.read_bytes() == loader.encode("ascii")
        ):
            return directory
        # The caller repairs into a new release rather than replacing loaded DLLs.
        raise InstallError("The private Windows C++ runtime needs a clean environment repair.")
    print("Preparing the private Microsoft Visual C++ runtime...", flush=True)
    archive = download(
        specification["url"],
        specification["sha256"],
        root / "downloads" / ("Microsoft-CRT-" + specification["version"] + "-x64.vsix"),
    )
    directory.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as package:
            for name, details in specification["files"].items():
                if Path(name).name != name or not name.endswith(".dll"):
                    raise InstallError("A Windows runtime dependency has invalid file metadata.")
                member = package.getinfo(details["archive_path"])
                if member.file_size > MAX_BINARY_BYTES:
                    raise InstallError("A Windows runtime dependency exceeds its size limit.")
                # Never extract archive paths; whitelist only redistributable release DLLs.
                (directory / name).write_bytes(package.read(member))
    except (zipfile.BadZipFile, KeyError) as exc:
        raise InstallError(
            "The verified Windows runtime package has an unexpected layout."
        ) from exc
    shutil.copy2(
        release / "install/licenses/Microsoft-Visual-C-Runtime-LICENSE.docx",
        directory / "LICENSE.docx",
    )
    if not files_match(directory, expected):
        raise InstallError("A private Windows runtime dependency failed its integrity check.")
    write_atomic(directory / "DOWNLOADS.json", json.dumps(specification, indent=2) + "\n")
    write_atomic(registration, loader)
    return directory


def prepare_ffmpeg_bundle(root: Path, specification: dict) -> Path:
    """Keep the complete relocatable LGPL bundle, including libraries and notices."""
    name = specification["directory"]
    if Path(name).name != name or name in {".", ".."}:
        raise InstallError("An audio dependency has an invalid extraction directory.")
    tools_root = root / "tools"
    tools_root.mkdir(parents=True, exist_ok=True)
    tools = tools_root / name
    print("Preparing " + name + "...", flush=True)
    archive = download(
        specification["url"], specification["sha256"], root / "downloads" / (name + ".tar.xz")
    )
    candidates = [tools]
    current_path = root / "current.json"
    if current_path.exists():
        try:
            preferred = Path(json.loads(current_path.read_text())["ffmpeg_directory"]).parent
            if preferred.parent == tools_root:
                candidates.insert(0, preferred)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    matched = next(
        (candidate for candidate in candidates if bundle_matches(candidate, specification)), None
    )
    if matched:
        tools = matched
    else:
        if tools.exists():
            tools = tools_root / (name + "-repair-" + str(time.time_ns()))
        with tempfile.TemporaryDirectory(prefix="ffmpeg-stage-", dir=tools_root) as stage:
            try:
                with tarfile.open(archive, "r:xz") as bundle:
                    members = bundle.getmembers()
                    if sum(item.size for item in members) > MAX_BINARY_BYTES:
                        raise InstallError("The extracted audio bundle exceeds its size limit.")
                    if any(
                        not Path(item.name).parts or Path(item.name).parts[0] != name
                        for item in members
                    ):
                        raise InstallError("The audio bundle has an unexpected directory layout.")
                    bundle.extractall(stage, members=members, filter="data")
            except tarfile.TarError as exc:
                raise InstallError(
                    "The verified audio bundle could not be safely extracted."
                ) from exc
            candidate = Path(stage) / name
            candidate.replace(tools)
            files = {}
            for path in tools.rglob("*"):
                if path.is_symlink():
                    files[path.relative_to(tools).as_posix()] = {"link": os.readlink(path)}
                elif path.is_file():
                    files[path.relative_to(tools).as_posix()] = {"sha256": digest(path)}
            write_atomic(
                tools / "INSTALL-MANIFEST.json",
                json.dumps({"asset": specification, "files": files}, indent=2) + "\n",
            )
    for executable in ("ffmpeg", "ffprobe"):
        output = run([str(tools / "bin" / executable), "-version"], timeout=20, capture=True).stdout
        if "--enable-nonfree" in output or "--enable-gpl" in output:
            raise InstallError(
                "The selected LGPL audio bundle has an incompatible build configuration."
            )
    if not (tools / "LICENSES").is_dir() or not (tools / "BUILDINFO.txt").is_file():
        raise InstallError("The audio bundle is missing its license or source-build notices.")
    return tools / "bin"


def bundle_matches(directory: Path, specification: dict) -> bool:
    try:
        metadata = json.loads((directory / "INSTALL-MANIFEST.json").read_text())
        if metadata["asset"] != specification or not metadata["files"]:
            return False
        for name, expected in metadata["files"].items():
            path = directory / name
            if "link" in expected:
                if not path.is_symlink() or os.readlink(path) != expected["link"]:
                    return False
            elif not path.is_file() or digest(path) != expected["sha256"]:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def payload_files(source: Path):
    for name in PAYLOAD:
        path = source / name
        if not path.exists():
            raise InstallError(f"The extracted project is incomplete: {name} is missing.")
        if path.is_symlink():
            raise InstallError("The application payload must not contain symbolic links.")
        for item in sorted(path.rglob("*")) if path.is_dir() else (path,):
            relative = item.relative_to(source)
            if (
                item.is_file()
                and not any(part in IGNORED for part in relative.parts)
                and item.suffix != ".pyc"
            ):
                if item.is_symlink():
                    raise InstallError("The application payload must not contain symbolic links.")
                yield item, relative


def payload_digest(source: Path) -> str:
    checksum = hashlib.sha256()
    for path, relative in payload_files(source):
        checksum.update(relative.as_posix().encode("utf-8") + b"\0")
        checksum.update(bytes.fromhex(digest(path)))
    return checksum.hexdigest()


def payload_matches(source: Path, expected: str) -> bool:
    try:
        return payload_digest(source) == expected
    except (InstallError, OSError):
        return False


def prepare_release(
    source: Path,
    release: Path,
    uv: Path,
    python_version: str,
    environment: dict[str, str],
    windows: bool,
) -> Path:
    if not (release / "installed.json").exists():
        if release.exists():
            shutil.rmtree(release)
        release.mkdir(parents=True)
        for name in PAYLOAD:
            if (source / name).is_dir():
                (release / name).mkdir(parents=True, exist_ok=True)
        for path, relative in payload_files(source):
            destination = release / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        print("Installing the locked application dependencies...", flush=True)
        run(
            [
                str(uv),
                "sync",
                "--project",
                str(release),
                "--no-config",
                "--frozen",
                "--no-dev",
                "--python",
                python_version,
                "--python-preference",
                "only-managed",
                "--link-mode",
                "copy",
            ],
            env=environment,
            timeout=1200,
        )
    return release / ".venv" / ("Scripts/python.exe" if windows else "bin/python")


def write_atomic(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    # cmd.exe can misparse the line after UTF-8 paths in LF-only batch files.
    temporary.write_text(
        text, encoding="utf-8", newline="\r\n" if path.suffix.lower() == ".cmd" else "\n"
    )
    temporary.chmod(0o700 if executable else 0o600)
    temporary.replace(path)


def command_text(python: Path, tools: Path, state: Path, windows: bool) -> str:
    if windows:

        def escape(value):
            return str(value).replace("%", "%%")

        return (
            "@echo off\nsetlocal DisableDelayedExpansion\n"
            'for /f "tokens=2 delims=:" %%C in (\'chcp\') do set "AI_PREVIOUS_CODEPAGE=%%C"\n'
            "chcp 65001 >nul\n"
            f'set "PATH={escape(tools)};%PATH%"\n'
            f'set "AI_SONG_DETECTION_STATE_DIR={escape(state)}"\n'
            f'"{escape(python)}" -m ai_song_detection %*\n'
            'set "AI_COMMAND_RESULT=%errorlevel%"\n'
            "if defined AI_PREVIOUS_CODEPAGE chcp %AI_PREVIOUS_CODEPAGE% >nul\n"
            "exit /b %AI_COMMAND_RESULT%\n"
        )
    return (
        "#!/bin/sh\n"
        + f'export PATH={shlex.quote(str(tools))}:"$PATH"\n'
        + f"export AI_SONG_DETECTION_STATE_DIR={shlex.quote(str(state))}\n"
        + f'exec {shlex.quote(str(python))} -m ai_song_detection "$@"\n'
    )


def shortcut_text(wrapper: Path, action: str, windows: bool) -> str:
    if windows:
        path = str(wrapper).replace("%", "%%")
        return (
            "@echo off\nchcp 65001 >nul\nsetlocal DisableDelayedExpansion\n"
            + f'call "{path}" {action} %*\nset "result=%errorlevel%"\n'
            + 'if not "%result%"=="0" pause\nexit /b %result%\n'
        )
    return (
        "#!/bin/sh\n"
        + f'{shlex.quote(str(wrapper))} {action} "$@"\n'
        + 'result=$?\nif [ "$result" -ne 0 ] && [ -t 0 ]; then\n'
        + "  printf '\nThe operation failed. Read the error above. Press Enter to close. '\n"
        + '  read -r answer\nfi\nexit "$result"\n'
    )


def create_windows_link(shortcut: Path, target: Path, arguments: list[str]) -> None:
    """Use Unicode COM interfaces; WScript.Shell loses non-ANSI desktop paths."""
    import ctypes
    import uuid

    class GUID(ctypes.Structure):
        _fields_ = [("bytes", ctypes.c_ubyte * 16)]

    def guid(value):
        return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)

    hresult = ctypes.c_int32
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole32.CoInitializeEx.restype = hresult
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = hresult
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None

    def checked(result):
        if result < 0:
            raise InstallError(
                f"Could not create the desktop shortcut (0x{result & 0xFFFFFFFF:08X})."
            )

    def invoke(pointer, index, result_type, argument_types, *arguments):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        function = ctypes.WINFUNCTYPE(result_type, ctypes.c_void_p, *argument_types)(table[index])
        return function(pointer, *arguments)

    initialized = ole32.CoInitializeEx(None, 2)
    # An already initialized MTA can still use this in-process COM server.
    if initialized != -2147417850:  # RPC_E_CHANGED_MODE
        checked(initialized)
    shell, persist = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        shell_class = guid("00021401-0000-0000-C000-000000000046")
        shell_interface = guid("000214F9-0000-0000-C000-000000000046")  # IShellLinkW
        checked(
            ole32.CoCreateInstance(
                ctypes.byref(shell_class),
                None,
                1,
                ctypes.byref(shell_interface),
                ctypes.byref(shell),
            )
        )
        for index, value in (
            (20, str(target)),  # SetPath
            (11, subprocess.list2cmdline(arguments)),  # SetArguments
            (9, str(target.parent)),  # SetWorkingDirectory
            (7, "AI Song Detection local service"),  # SetDescription
        ):
            checked(invoke(shell, index, hresult, [ctypes.c_wchar_p], value))
        checked(invoke(shell, 15, hresult, [ctypes.c_int], 1))  # SetShowCmd
        persist_interface = guid("0000010B-0000-0000-C000-000000000046")  # IPersistFile
        checked(
            invoke(
                shell,
                0,
                hresult,
                [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
                ctypes.byref(persist_interface),
                ctypes.byref(persist),
            )
        )
        checked(invoke(persist, 6, hresult, [ctypes.c_wchar_p, ctypes.c_int], str(shortcut), 1))
    finally:
        for pointer in (persist, shell):
            if pointer:
                invoke(pointer, 2, ctypes.c_uint32, [])  # Release
        if initialized >= 0:
            ole32.CoUninitialize()


def install_entries(root: Path, desktop: Path, python: Path, tools: Path, windows: bool) -> Path:
    desktop.mkdir(parents=True, exist_ok=True)
    wrapper = root / "bin" / ("ai-song-detection.cmd" if windows else "ai-song-detection")
    write_atomic(wrapper, command_text(python, tools, root / "state", windows), executable=True)
    if windows:
        # The native shortcut starts Python directly. CMD's extra parsing of
        # nested batch paths is unnecessary for a desktop entry.
        desktop_script = root / "bin" / "desktop.py"
        write_atomic(
            desktop_script,
            "import os, sys, traceback\nfrom pathlib import Path\n"
            + f"os.environ['PATH'] = {str(tools)!r} + os.pathsep + os.environ.get('PATH', '')\n"
            + f"os.environ['AI_SONG_DETECTION_STATE_DIR'] = {str(root / 'state')!r}\n"
            + "state = Path(os.environ['AI_SONG_DETECTION_STATE_DIR'])\n"
            + "state.mkdir(parents=True, exist_ok=True)\n"
            + "with (state / 'desktop.log').open('a', encoding='utf-8') as log:\n"
            + "    log.write('Desktop request: ' + repr(sys.argv[1:]) + '\\n')\n"
            + "    log.flush()\n"
            + "    try:\n"
            + "        from ai_song_detection.cli import main\n"
            + "        main()\n"
            + "    except BaseException as exc:\n"
            + "        if not isinstance(exc, SystemExit) or exc.code not in (None, 0):\n"
            + "            traceback.print_exc(file=log)\n"
            + "        raise\n",
        )
    for action, label in (("launch", APP_NAME), ("stop", "Stop " + APP_NAME)):
        entry = (
            root
            / "bin"
            / (("Start" if action == "launch" else "Stop") + (".cmd" if windows else ".command"))
        )
        write_atomic(entry, shortcut_text(wrapper, action, windows), executable=True)
        if windows:
            create_windows_link(desktop / (label + ".lnk"), python, [str(desktop_script), action])
        else:
            write_atomic(
                desktop / (label + ".command"),
                shortcut_text(wrapper, action, windows),
                executable=True,
            )
    return wrapper


@contextlib.contextmanager
def install_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / "install.lock").open("a+b") as lock:
        lock.seek(0)
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise InstallError(
                "Another installation is running. Wait for it to finish and retry."
            ) from exc
        try:
            yield
        finally:
            lock.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def install(source: Path, uv: Path, root: Path, desktop: Path, *, launch: bool = True) -> dict:
    source, uv, root, desktop = (
        path.expanduser().resolve() for path in (source, uv, root, desktop)
    )
    target = platform_key()
    if target.startswith("darwin") and int(platform.mac_ver()[0].split(".")[0]) < 13:
        raise InstallError("AI Song Detection requires macOS 13 or later.")
    if target.startswith("win32") and sys.getwindowsversion().major < 10:
        raise InstallError("AI Song Detection requires Windows 10 or Windows 11.")
    if not uv.is_file():
        raise InstallError("The verified private installer could not be found. Run Install again.")
    manifest = json.loads((source / "install/dependencies.json").read_text(encoding="utf-8"))
    if manifest["uv_version"] not in run([str(uv), "--version"], capture=True, timeout=10).stdout:
        raise InstallError("The installer version does not match the pinned dependency manifest.")
    with install_lock(root):
        print("Installing AI Song Detection into " + str(root), flush=True)
        tools = prepare_ffmpeg(root, manifest, target)
        source_hash = payload_digest(source)
        current_path = root / "current.json"
        previous = json.loads(current_path.read_text()) if current_path.exists() else None
        release = root / "releases" / source_hash[:16]
        if previous and previous.get("source_sha256") == source_hash:
            installed = Path(previous["release"])
            if installed.parent == root / "releases":
                release = installed
        ready = release / "installed.json"
        is_current = previous and previous.get("release") == str(release)
        if release.exists() and (
            (ready.exists() and not payload_matches(release, source_hash))
            or (is_current and not ready.exists())
        ):
            print("Preparing a clean repair without modifying the existing version...", flush=True)
            release = root / "releases" / (source_hash[:16] + "-repair-" + str(time.time_ns()))
            ready = release / "installed.json"
        environment = os.environ | {
            "UV_PYTHON_INSTALL_DIR": str(root / "runtime/python"),
            "UV_CACHE_DIR": str(root / "cache/uv"),
            "UV_PYTHON_PREFERENCE": "only-managed",
            "UV_NO_MODIFY_PATH": "1",
            "UV_PYTHON_INSTALL_BIN": "0",
            "PATH": str(tools) + os.pathsep + os.environ.get("PATH", ""),
            "AI_SONG_DETECTION_STATE_DIR": str(root / "state"),
        }
        check = (
            "from ai_song_detection.detector import Detector; import shutil; "
            "assert shutil.which('ffmpeg') and shutil.which('ffprobe'); Detector(); "
            "print('Model and audio tools are ready.')"
        )
        for attempt in range(2):
            reused = ready.exists()
            python = prepare_release(
                source,
                release,
                uv,
                manifest["python_version"],
                environment,
                target.startswith("win32"),
            )
            print("Checking the bundled model and private audio tools...", flush=True)
            try:
                if target.startswith("win32"):
                    prepare_windows_runtime(root, release, manifest["windows_runtime"])
                run([str(python), "-c", check], env=environment, timeout=90)
                break
            except InstallError:
                if not reused or attempt:
                    raise
                print(
                    "The installed environment needs repair. Preparing a clean copy...", flush=True
                )
                release = root / "releases" / (source_hash[:16] + "-repair-" + str(time.time_ns()))
                ready = release / "installed.json"
        information = {
            "release": str(release),
            "python": str(python),
            "ffmpeg_directory": str(tools),
            "source_sha256": source_hash,
            "platform": target,
            "desktop": str(desktop),
        }
        write_atomic(ready, json.dumps(information, indent=2) + "\n")
        # Prepare all candidate files before stopping an old managed instance.
        if previous and (
            previous.get("release") != str(release)
            or previous.get("ffmpeg_directory") != str(tools)
        ):
            old_python = Path(previous["python"])
            if old_python.is_file():
                print("Stopping the previous application version before switching...", flush=True)
                run(
                    [str(old_python), "-c", "from ai_song_detection.launcher import stop; stop()"],
                    env=environment,
                    timeout=100,
                )
        # Desktop failures must not publish a broken 'current' version.
        backup = {}
        entries = [
            root / "bin",
            desktop / (APP_NAME + (".lnk" if target.startswith("win32") else ".command")),
            desktop / ("Stop " + APP_NAME + (".lnk" if target.startswith("win32") else ".command")),
        ]
        for entry in entries:
            if entry.is_file():
                backup[entry] = entry.read_bytes()
        try:
            wrapper = install_entries(root, desktop, python, tools, target.startswith("win32"))
            write_atomic(current_path, json.dumps(information, indent=2) + "\n")
        except Exception:
            # Restore the previous wrapper; immutable old environments remain untouched.
            if previous:
                install_entries(
                    root,
                    Path(previous["desktop"]),
                    Path(previous["python"]),
                    Path(previous["ffmpeg_directory"]),
                    target.startswith("win32"),
                )
            for entry, data in backup.items():
                entry.write_bytes(data)
            raise
        print("Installation complete. Desktop entries: " + str(desktop), flush=True)
        print("Command-line entry: " + str(wrapper), flush=True)
    if launch:
        print("Starting the detector and opening the default browser...", flush=True)
        run([str(python), "-m", "ai_song_detection", "launch"], env=environment, timeout=120)
    return information


def main() -> None:
    parser = argparse.ArgumentParser(description="Install AI Song Detection for the current user")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--uv", type=Path, required=True, help="Verified private uv executable")
    parser.add_argument("--install-dir", type=Path, default=install_directory())
    parser.add_argument("--desktop-dir", type=Path, default=desktop_directory())
    parser.add_argument(
        "--no-launch", action="store_true", help="Install without opening a browser"
    )
    arguments = parser.parse_args()
    try:
        install(
            arguments.source,
            arguments.uv,
            arguments.install_dir,
            arguments.desktop_dir,
            launch=not arguments.no_launch,
        )
    except (InstallError, OSError, ValueError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
