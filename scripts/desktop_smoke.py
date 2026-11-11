#!/usr/bin/env python3
"""Native installer/desktop verification, independent of a developer checkout.

Run on a Mac or Windows host. --browser additionally needs Playwright in the
verifier's environment; the installed application never needs Playwright.
"""

from __future__ import annotations

import argparse
import array
import contextlib
import hashlib
import json
import math
import os
import platform
import random
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave
from pathlib import Path

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
    "Install.command",
    "Install.cmd",
)
WINDOWS = os.name == "nt"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def native_command(path: Path, arguments: list[str], environment: dict) -> tuple[list | str, dict]:
    environment = environment.copy()
    if not WINDOWS:
        return ["/bin/sh", str(path), *arguments], environment
    # Avoid list2cmdline's extra escaping of the quotes consumed by cmd /s /c.
    # Expand path/arguments from environment variables, never interpolate path text.
    environment["AI_SMOKE_COMMAND"] = str(path)
    for index, value in enumerate(arguments):
        environment[f"AI_SMOKE_ARG_{index}"] = value
    parameters = " ".join(f'"%AI_SMOKE_ARG_{index}%"' for index in range(len(arguments)))
    command = f'"{environment["COMSPEC"]}" /d /v:off /s /c ""%AI_SMOKE_COMMAND%" {parameters}"'
    return command, environment


def run_native(
    path: Path,
    arguments: list[str],
    environment: dict,
    *,
    timeout: int = 90,
    log: Path | None = None,
) -> subprocess.CompletedProcess:
    command, environment = native_command(path, arguments, environment)
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}
    if log:
        with log.open("wb") as output:
            result = subprocess.run(
                command,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                **options,
            )
        check(result.returncode == 0, f"Native command failed ({result.returncode}); see {log}")
        return result
    result = subprocess.run(
        command,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **options,
    )
    check(result.returncode == 0, f"Native command failed: {result.stdout}\n{result.stderr}")
    return result


def clean_environment(work: Path, root: Path, desktop: Path) -> dict:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTHON", "UV_", "CONDA", "VIRTUAL_ENV", "AI_SONG_DETECTION_"))
    }
    if WINDOWS:
        system = Path(environment.get("SYSTEMROOT") or environment.get("SystemRoot", r"C:\Windows"))
        environment["COMSPEC"] = str(system / "System32/cmd.exe")
        environment["PATH"] = os.pathsep.join(
            str(system / name) for name in ("System32", "System32/WindowsPowerShell/v1.0")
        )
    else:
        # macOS ships Git/Python stubs in /usr/bin. Fail if setup accidentally uses
        # them instead of its verified private bootstrap and managed Python.
        blocked = work / "No developer tools"
        blocked.mkdir()
        for name in ("python", "python3", "uv", "git", "ffmpeg", "ffprobe"):
            path = blocked / name
            path.write_text(
                "#!/bin/sh\nprintf '%s\\n' 'Host developer tools are disabled during verification.' >&2\nexit 97\n"
            )
            path.chmod(0o700)
        environment["PATH"] = str(blocked) + ":/usr/bin:/bin:/usr/sbin:/sbin"
    environment.update(
        AI_SONG_DETECTION_INSTALL_DIR=str(root),
        AI_SONG_DETECTION_DESKTOP_DIR=str(desktop),
        PYTHONUTF8="1",
    )
    return environment


def cli(wrapper: Path, environment: dict, *arguments: str, timeout: int = 100) -> dict:
    result = run_native(wrapper, [*arguments, "--json"], environment, timeout=timeout)
    return json.loads(result.stdout)


def wait_status(wrapper: Path, environment: dict, expected: str, timeout: float = 60) -> dict:
    deadline, latest = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        try:
            latest = cli(wrapper, environment, "status", timeout=5)
            if latest.get("status") == expected and (expected != "running" or latest.get("ready")):
                return latest
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.2)
    raise AssertionError(f"Expected {expected} within {timeout:g} seconds; latest status: {latest}")


def json_http(url: str, *, audio: Path | None = None) -> tuple[int, dict]:
    if audio:
        boundary = "ai-song-smoke-" + uuid.uuid4().hex
        body = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
            f'filename="{audio.name}"\r\nContent-Type: audio/wav\r\n\r\n'
        ).encode() + audio.read_bytes()
        body += f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
        )
    else:
        request = urllib.request.Request(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def synthetic_song(path: Path) -> None:
    rng, samples = random.Random(1844), array.array("h")
    for index in range(12 * 16000):
        second = index / 16000
        value = (
            0.15 * math.sin(2 * math.pi * 440 * second)
            + 0.08 * math.sin(2 * math.pi * 880 * second)
            + rng.gauss(0, 0.02)
        )
        samples.append(round(max(-1, min(1, value)) * 32767))
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(samples.tobytes())


def windows_loaded_runtime(pid: int, install_root: Path) -> dict:
    """Read the real detector process's DLL paths, without changing the host DLLs."""
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.K32EnumProcessModules.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HMODULE),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel.K32EnumProcessModules.restype = wintypes.BOOL
    kernel.K32GetModuleFileNameExW.argtypes = (
        wintypes.HANDLE,
        wintypes.HMODULE,
        wintypes.LPWSTR,
        wintypes.DWORD,
    )
    kernel.K32GetModuleFileNameExW.restype = wintypes.DWORD
    process = kernel.OpenProcess(0x0400 | 0x0010, False, pid)  # QUERY_INFORMATION | VM_READ.
    if not process:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        capacity = 256
        while True:
            modules = (wintypes.HMODULE * capacity)()
            needed = wintypes.DWORD()
            if not kernel.K32EnumProcessModules(
                process, modules, ctypes.sizeof(modules), ctypes.byref(needed)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if needed.value <= ctypes.sizeof(modules):
                break
            capacity = needed.value // ctypes.sizeof(wintypes.HMODULE) + 64
            check(capacity <= 4096, "The detector module list exceeded its verification limit")
        paths = {}
        for module in modules[: needed.value // ctypes.sizeof(wintypes.HMODULE)]:
            buffer = ctypes.create_unicode_buffer(32768)
            length = kernel.K32GetModuleFileNameExW(process, module, buffer, len(buffer))
            if not length:
                raise ctypes.WinError(ctypes.get_last_error())
            check(length < len(buffer), "A loaded module path was truncated")
            paths[Path(buffer.value).name.casefold()] = buffer.value
        required = ("msvcp140.dll", "msvcp140_1.dll", "vcruntime140.dll", "vcruntime140_1.dll")
        check(
            all(name in paths for name in required),
            "The real ONNX process did not load all required C++ runtime DLLs",
        )
        expected_root = install_root.resolve()
        for name in (*required, "onnxruntime_pybind11_state.pyd"):
            check(name in paths, f"The real detector process has no loaded {name}")
            check(
                Path(paths[name]).resolve().is_relative_to(expected_root),
                f"The detector loaded {name} from a host/global location: {paths[name]}",
            )
        return {
            "process_pid": pid,
            "modules": {name: paths[name] for name in required},
            "onnxruntime_extension": paths["onnxruntime_pybind11_state.pyd"],
            "all_runtime_modules_private": True,
            "method": "Read-only OpenProcess + K32EnumProcessModules/K32GetModuleFileNameExW on the actual inference service after a real upload; no host DLLs were replaced or unloaded.",
        }
    finally:
        kernel.CloseHandle(process)


@contextlib.contextmanager
def temporary_environment(environment: dict):
    previous = os.environ.copy()
    os.environ.clear()
    os.environ.update(environment)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def start_desktop(entry: Path, environment: dict, log: Path) -> None:
    if WINDOWS:
        log.write_text(
            json.dumps(
                {
                    "method": "os.startfile / ShellExecute on the desktop .lnk",
                    "entry": str(entry),
                    "time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "boundary": "ShellExecute does not provide child stdout, stderr or exit status.",
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        with temporary_environment(environment):
            os.startfile(str(entry))
        with log.open("a", encoding="utf-8") as output:
            output.write("ShellExecute returned without an immediate exception.\n")
    else:
        run_native(entry, ["--no-browser"], environment, log=log)


def stop_desktop(entry: Path, environment: dict, log: Path) -> None:
    if WINDOWS:
        with temporary_environment(environment):
            os.startfile(str(entry))
    else:
        run_native(entry, [], environment, log=log, timeout=110)


def windows_shortcut_details(entry: Path) -> dict:
    """Read the saved Unicode shell link without launching or changing its target."""
    import ctypes

    class GUID(ctypes.Structure):
        _fields_ = [("bytes", ctypes.c_ubyte * 16)]

    def guid(value):
        return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)

    hresult = ctypes.c_int32
    ole = ctypes.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole.CoInitializeEx.restype = hresult
    ole.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole.CoCreateInstance.restype = hresult
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None

    def checked(result):
        if result < 0:
            raise OSError(f"Reading shell link failed (0x{result & 0xFFFFFFFF:08X})")

    def invoke(pointer, index, result_type, argument_types, *arguments):
        table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        method = ctypes.WINFUNCTYPE(result_type, ctypes.c_void_p, *argument_types)(table[index])
        return method(pointer, *arguments)

    initialized = ole.CoInitializeEx(None, 2)
    if initialized != -2147417850:  # RPC_E_CHANGED_MODE: existing MTA is usable.
        checked(initialized)
    shell, persist = ctypes.c_void_p(), ctypes.c_void_p()
    try:
        shell_class = guid("00021401-0000-0000-C000-000000000046")
        shell_interface = guid("000214F9-0000-0000-C000-000000000046")
        checked(
            ole.CoCreateInstance(
                ctypes.byref(shell_class),
                None,
                1,
                ctypes.byref(shell_interface),
                ctypes.byref(shell),
            )
        )
        persist_interface = guid("0000010B-0000-0000-C000-000000000046")
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
        checked(invoke(persist, 5, hresult, [ctypes.c_wchar_p, ctypes.c_uint32], str(entry), 0))
        details = {}
        for name, index in (("target", 3), ("arguments", 10), ("working_directory", 8)):
            buffer = ctypes.create_unicode_buffer(32768)
            types = [ctypes.c_wchar_p, ctypes.c_int]
            arguments = [buffer, len(buffer)]
            if index == 3:
                types.extend([ctypes.c_void_p, ctypes.c_uint32])
                arguments.extend([None, 4])  # SLGP_RAWPATH; no resolution side effects.
            checked(invoke(shell, index, hresult, types, *arguments))
            details[name] = buffer.value
        show = ctypes.c_int()
        checked(invoke(shell, 14, hresult, [ctypes.POINTER(ctypes.c_int)], ctypes.byref(show)))
        details["show_command"] = show.value
        details["method"] = "Read-only IPersistFile.Load + IShellLinkW getters"
        return details
    finally:
        for pointer in (persist, shell):
            if pointer:
                invoke(pointer, 2, ctypes.c_uint32, [])
        if initialized >= 0:
            ole.CoUninitialize()


def collect_diagnostics(work: Path, report: Path, evidence: dict) -> None:
    """Keep only explicit non-secret files, including when installation/startup fails."""
    root, desktop = work / "Private App 中文", work / "Desktop 中文"
    output = report / "diagnostics"
    output.mkdir(exist_ok=True)
    details, files, errors = {}, [], []
    sources = [
        *(root / "bin").glob("*.cmd"),
        *(root / "bin").glob("*.command"),
        root / "bin/desktop.py",
        *desktop.glob("*.lnk"),
        root / "current.json",
        root / "state/service.log",
        root / "state/desktop.log",
    ]
    for source in sources:
        if not source.is_file():
            continue
        try:
            # Never traverse/copy the state directory: instance.json contains a token.
            prefix = "desktop-" if source.parent == desktop else ""
            destination = output / (prefix + source.name)
            with source.open("rb") as incoming, destination.open("wb") as outgoing:
                if source.name in {"service.log", "desktop.log"}:
                    incoming.seek(max(0, source.stat().st_size - 2 * 1024 * 1024))
                shutil.copyfileobj(incoming, outgoing)
            files.append(str(destination.relative_to(report)))
            if WINDOWS and source.suffix.lower() == ".lnk":
                try:
                    details[source.name] = windows_shortcut_details(source)
                except Exception as exc:
                    details[source.name] = {"read_error": f"{type(exc).__name__}: {exc}"}
        except Exception as exc:
            errors.append(f"{source.name}: {type(exc).__name__}: {exc}")
    if details:
        (output / "shortcuts.json").write_text(
            json.dumps(details, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        files.append("diagnostics/shortcuts.json")
    evidence["diagnostics"] = {
        "files": files,
        "errors": errors,
        "boundary": "Explicit launcher, shortcut, current-install metadata and service-log whitelist; instance.json and environment variables are never copied. Collection does not launch any entry or change a failed result.",
    }


def browser_verify(url: str, song: Path, report: Path) -> dict:
    from playwright.sync_api import expect, sync_playwright

    errors, requests = [], []
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" else None,
            )
            page.on("request", lambda request: requests.append(request.url))
            page.goto(url, wait_until="networkidle")
            page.get_by_text("Detector ready", exact=True).wait_for(timeout=15000)
            page.locator("#start-seconds").fill("1")
            page.locator("#duration-seconds").fill("10")
            page.locator("#audio-file").set_input_files(str(song))
            page.locator("#analyze-button").click()
            page.locator("#detection-result").wait_for(state="visible", timeout=30000)
            check(
                page.locator("#assessment-label").inner_text()
                in {"Likely AI-generated", "Likely human-created", "Uncertain"},
                "Missing rendered assessment",
            )
            expect(page.locator('#history-list [data-status="completed"]')).to_have_count(1)
            check(
                "1.0 sec to 11.0 sec" in page.locator("#analyzed-coverage").inner_text(),
                "Selected interval was not displayed",
            )
            page.locator("#audio-file").set_input_files(
                [str(song), str(song.parent / "corrupt.wav")]
            )
            page.locator("#analyze-button").click()
            expect(page.locator("#history-list li")).to_have_count(3, timeout=30000)
            check(
                page.locator('#history-list [data-status="completed"]').count() == 2,
                "Multi-file queue lost a valid report",
            )
            check(
                page.locator('#history-list [data-status="failed"]').count() == 1,
                "Multi-file queue did not retain the invalid-audio error",
            )
            with page.expect_download() as download:
                page.locator("#download-all-json").click()
            export = report / "session.json"
            download.value.save_as(export)
            records = json.loads(export.read_text())["reports"]
            check(
                len(records) == 3
                and records[0]["input_sha256"] == hashlib.sha256(song.read_bytes()).hexdigest(),
                "Downloaded session reports are incomplete",
            )
            check(
                records[0]["analyzed_start_seconds"] == 1
                and records[0]["analyzed_end_seconds"] == 11,
                "Downloaded report lost selected interval",
            )
            with page.expect_download() as download:
                page.locator("#download-all-csv").click()
            download.value.save_as(report / "session.csv")
            page.locator('#history-list [data-status="completed"]').first.get_by_role(
                "button", name="View"
            ).click()
            check(
                page.evaluate("document.documentElement.scrollWidth <= innerWidth"),
                "Desktop horizontal overflow",
            )
            page.screenshot(path=str(report / "desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            check(
                page.evaluate("document.documentElement.scrollWidth <= innerWidth"),
                "Mobile horizontal overflow",
            )
            page.screenshot(path=str(report / "mobile.png"), full_page=True)
            page.goto(url + "/docs", wait_until="networkidle")
            check(page.locator("body").inner_text(), "API reference is empty")
            check(not errors, f"Browser errors: {errors}")
            check(
                all(address.startswith(url + "/") or address == url for address in requests),
                "An external browser resource was requested",
            )
            return {
                "desktop_width": 1440,
                "mobile_width": 390,
                "real_upload_rendered": True,
                "serial_queue_valid_and_invalid": True,
                "selected_window": [1, 11],
                "json_and_csv_exports": True,
                "all_resources_local": True,
                "javascript_errors": errors,
                "screenshots": ["desktop.png", "mobile.png"],
            }
        finally:
            browser.close()


def verify(source: Path, work: Path, report: Path, browser: bool, evidence: dict) -> None:
    check(
        platform.system() in {"Darwin", "Windows"}, "Run this native verifier on macOS or Windows."
    )
    check(
        not work.exists() or not any(work.iterdir()),
        "Use a new or empty work directory to verify a fresh install.",
    )
    work.mkdir(parents=True, exist_ok=True)
    root, desktop, copied = (
        work / "Private App 中文",
        work / "Desktop 中文",
        work / "下载 project 中文",
    )
    copied.mkdir()
    for name in PAYLOAD:
        original, destination = source / name, copied / name
        check(original.exists(), f"Required source payload is missing: {original}")
        if original.is_dir():
            shutil.copytree(
                original,
                destination,
                symlinks=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
            )
        else:
            shutil.copy2(original, destination)
    environment = clean_environment(work, root, desktop)
    evidence["clean_path"] = environment["PATH"]
    evidence["desktop_entry_execution"] = (
        "Windows .lnk invoked with os.startfile/ShellExecute; its launcher requests the default browser."
        if WINDOWS
        else "macOS .command executed with /bin/sh --no-browser; Finder activation and default-browser opening are not exercised by this smoke test."
    )
    evidence["checks"] = checks = {}
    install_entry = copied / ("Install.cmd" if WINDOWS else "Install.command")
    run_native(
        install_entry, ["--no-launch"], environment, timeout=1800, log=report / "install.log"
    )
    installed = json.loads((root / "current.json").read_text(encoding="utf-8"))
    for key in ("release", "python", "ffmpeg_directory"):
        check(
            Path(installed[key]).is_relative_to(root), f"{key} is outside the private installation"
        )
    wrapper = root / "bin" / ("ai-song-detection.cmd" if WINDOWS else "ai-song-detection")
    start_entry = desktop / ("AI Song Detection.lnk" if WINDOWS else "AI Song Detection.command")
    stop_entry = desktop / (
        "Stop AI Song Detection.lnk" if WINDOWS else "Stop AI Song Detection.command"
    )
    check(start_entry.exists() and stop_entry.exists(), "The desktop entries were not created")
    if not WINDOWS:
        check(
            os.access(start_entry, os.X_OK) and os.access(stop_entry, os.X_OK),
            "Desktop commands are not executable",
        )
    checks["native_bootstrap_install"] = True
    evidence["installed"] = installed
    runtime_environment = environment | {
        "PATH": installed["ffmpeg_directory"] + os.pathsep + environment["PATH"]
    }
    probe = subprocess.run(
        [
            installed["python"],
            "-c",
            "import json, sys, shutil, ai_song_detection; "
            "print(json.dumps({'python':sys.executable,'base_prefix':sys.base_prefix,"
            "'package':ai_song_detection.__file__,'ffmpeg':shutil.which('ffmpeg'),"
            "'ffprobe':shutil.which('ffprobe')}))",
        ],
        env=runtime_environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    runtime = json.loads(probe.stdout)
    check(
        Path(runtime["base_prefix"]).is_relative_to(root / "runtime/python"), "Host Python was used"
    )
    check(
        Path(runtime["package"]).is_relative_to(Path(installed["release"])),
        "Package imports still depend on the checkout",
    )
    check(
        all(
            Path(runtime[tool]).parent == Path(installed["ffmpeg_directory"])
            for tool in ("ffmpeg", "ffprobe")
        ),
        "Host audio tools were used",
    )
    evidence["runtime"] = runtime
    shutil.rmtree(copied)
    checks["source_download_removed"] = not copied.exists()

    occupied = socket.socket()
    try:
        try:
            occupied.bind(("127.0.0.1", 8000))
            occupied.listen()
            evidence["port_8000"] = "occupied by verifier"
        except OSError:
            occupied.close()
            evidence["port_8000"] = "already occupied; existing process left untouched"
        start_desktop(start_entry, environment, report / "start.log")
        first = wait_status(wrapper, environment, "running")
        check(first["url"] != "http://127.0.0.1:8000", "The occupied port was reused")
        code, health = json_http(first["url"] + "/health")
        check(
            code == 200
            and health["app_id"] == "ai-song-detection"
            and health["instance_id"]
            and health["pid"] == first["pid"]
            and health["version"] == first["version"]
            and health["model_loaded"]
            and health["ffmpeg_available"],
            "The installed service failed identity/readiness checks",
        )
        evidence["health"] = health
        checks["native_desktop_start"] = checks["occupied_port_fallback"] = True
        start_desktop(start_entry, environment, report / "repeat-start.log")
        repeated = wait_status(wrapper, environment, "running")
        check(repeated["pid"] == first["pid"], "Repeated desktop launch created another instance")
        reused = cli(wrapper, environment, "launch", "--no-browser")
        check(
            reused["reused"] and reused["pid"] == first["pid"],
            "Command-line reopen did not reuse the desktop instance",
        )
        checks["repeat_desktop_reuses_pid"] = True
        song, corrupt = work / "synthetic-smoke.wav", work / "corrupt.wav"
        synthetic_song(song)
        corrupt.write_bytes(b"This is not an audio file.")
        code, result = json_http(first["url"] + "/api/v1/detect", audio=song)
        check(
            code == 200 and result["analyzed_duration_seconds"] == 12,
            "Real model HTTP inference failed",
        )
        evidence["inference"] = result
        if WINDOWS:
            evidence["windows_cpp_runtime"] = windows_loaded_runtime(first["pid"], root)
            checks["actual_windows_runtime_modules_private"] = True
        code, error = json_http(first["url"] + "/api/v1/detect", audio=corrupt)
        check(
            code == 422 and error["detail"]["code"] == "invalid_audio",
            "Corrupt audio was not rejected",
        )
        detection = cli(wrapper, environment, "detect", str(song))
        check(detection["ai_score"] == result["ai_score"], "CLI and HTTP inference disagree")
        checks["real_model_upload"] = checks["corrupt_audio_rejected"] = checks["cli_detect"] = True
        doctor = cli(wrapper, environment, "doctor")
        check(doctor["ok"], "Installed doctor found a broken dependency")
        discovered = run_native(wrapper, ["status", "--url"], environment).stdout.strip()
        check(discovered == first["url"], "status --url did not discover the managed service")
        preview = json.loads(run_native(wrapper, ["cleanup", "--keep", "2"], environment).stdout)
        check(
            not preview["applied"] and preview["service_running"],
            "Cleanup did not preserve the live app",
        )
        uninstall_preview = json.loads(run_native(wrapper, ["uninstall"], environment).stdout)
        check(
            not uninstall_preview["applied"] and (root / "current.json").exists(),
            "Uninstall preview changed the installation",
        )
        diagnostic = report / "diagnostics.zip"
        run_native(wrapper, ["diagnostics", "--output", str(diagnostic)], environment)
        checks["maintenance_doctor_discovery_and_previews"] = True
        if browser:
            evidence["browser"] = browser_verify(first["url"], song, report)
            checks["browser_upload_and_layout"] = True
        stop_desktop(stop_entry, environment, report / "stop.log")
        wait_status(wrapper, environment, "stopped")
        checks["native_desktop_stop"] = True
        offline = environment | {
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "ALL_PROXY": "http://127.0.0.1:1",
            "UV_OFFLINE": "1",
        }
        evidence["offline_method"] = (
            "UV_OFFLINE=1 and failing HTTP/HTTPS/ALL proxy addresses; installed launch/inference is exercised without invoking the installer. This does not alter the host firewall."
        )
        relaunched = cli(wrapper, offline, "launch", "--no-browser", "--timeout", "45")
        check(
            relaunched["status"] == "running" and not relaunched["reused"],
            "Offline relaunch failed",
        )
        code, _ = json_http(relaunched["url"] + "/api/v1/detect", audio=song)
        check(code == 200, "Offline local inference failed")
        check(
            cli(wrapper, offline, "stop", "--timeout", "90")["status"] == "stopped",
            "Offline stop failed",
        )
        checks["offline_relaunch_and_inference"] = True
        portable = work / "Offline export"
        bundle = json.loads(
            run_native(
                wrapper, ["bundle", "--output", str(portable)], environment, timeout=300
            ).stdout
        )
        check(bundle["status"] == "created", "Offline bundle export failed")
        relocated = work / "Portable installer 中文"
        portable.replace(relocated)
        restored_root, restored_desktop = work / "Restored App 中文", work / "Restored Desktop 中文"
        restore_entry = relocated / ("Restore.cmd" if WINDOWS else "Restore.command")
        run_native(
            restore_entry,
            [
                "--install-dir",
                str(restored_root),
                "--desktop-dir",
                str(restored_desktop),
                "--no-launch",
            ],
            offline,
            timeout=600,
            log=report / "offline-restore.log",
        )
        restored_wrapper = (
            restored_root / "bin" / ("ai-song-detection.cmd" if WINDOWS else "ai-song-detection")
        )
        isolated_offline = {
            key: value for key, value in offline.items() if not key.startswith("AI_SONG_DETECTION_")
        }
        restored_doctor = cli(restored_wrapper, isolated_offline, "doctor")
        check(restored_doctor["ok"], "Restored wrapper did not bind its own installation")
        restored = cli(restored_wrapper, isolated_offline, "launch", "--no-browser")
        try:
            code, restored_result = json_http(restored["url"] + "/api/v1/detect", audio=song)
            check(
                code == 200 and restored_result["ai_score"] == result["ai_score"],
                "Offline relocated inference changed",
            )
            if WINDOWS:
                evidence["restored_windows_cpp_runtime"] = windows_loaded_runtime(
                    restored["pid"], restored_root
                )
        finally:
            cli(restored_wrapper, isolated_offline, "stop")
        evidence["offline_bundle"] = {
            "platform": bundle["platform"],
            "files": bundle["files"],
            "size_bytes": bundle["size_bytes"],
            "relocated_restore": True,
            "private_runtime_doctor": True,
            "real_inference": True,
        }
        checks["offline_bundle_relocated_restore"] = True
        # Apply destructive maintenance only to this newly-created test installation.
        unrelated = restored_root / "unrelated.txt"
        unrelated.write_text("Preserve this operator file.")
        removed = json.loads(
            run_native(restored_wrapper, ["uninstall", "--apply"], isolated_offline).stdout
        )
        helper_result = None
        evidence["scoped_uninstall"] = removed
        deadline = time.monotonic() + 180
        result_file = Path(removed["result_file"]) if removed.get("scheduled_after_exit") else None
        while time.monotonic() < deadline:
            if result_file and result_file.exists():
                try:
                    helper_result = json.loads(result_file.read_text(encoding="utf-8-sig"))
                    if (
                        helper_result.get("status") in {"completed", "failed"}
                        or "status" not in helper_result
                    ):
                        break
                except (OSError, ValueError):
                    pass
            elif not result_file and not (restored_root / "current.json").exists():
                break
            time.sleep(0.25)
        if result_file:
            helper_log = result_file.with_name("helper.log")
            if helper_log.is_file():
                shutil.copy2(helper_log, report / "uninstall-helper.log")
            evidence["scoped_uninstall"]["helper_directory_files"] = sorted(
                path.name for path in result_file.parent.iterdir()
            )
        evidence["scoped_uninstall"]["helper_result"] = helper_result
        evidence["scoped_uninstall"]["remaining_top_level"] = (
            sorted(path.name for path in restored_root.iterdir()) if restored_root.exists() else []
        )
        if helper_result is not None:
            (report / "uninstall-result.json").write_text(
                json.dumps(helper_result, indent=2), encoding="utf-8"
            )
        check(
            removed["applied"]
            and not (restored_root / "current.json").exists()
            and unrelated.exists()
            and (
                not result_file
                or (
                    helper_result is not None
                    and helper_result.get("status", "completed") == "completed"
                    and not helper_result.get("remaining")
                    and not helper_result.get("error")
                )
            ),
            "Scoped uninstall did not remove only owned installation files; see scoped_uninstall evidence",
        )
        checks["scoped_uninstall_preserves_unrelated"] = True

    finally:
        occupied.close()
        # Stop only this verifier's private, identity-verified instance.
        if wrapper.exists():
            original_error = sys.exc_info()[0] is not None
            try:
                cli(wrapper, environment, "stop", "--timeout", "90")
            except Exception as exc:
                evidence["cleanup_error"] = str(exc)
                if not original_error:
                    raise
    checks["private_python_and_ffmpeg"] = True
    checks["unicode_and_space_paths"] = True
    checks["final_service_stopped"] = cli(wrapper, environment, "status")["status"] == "stopped"
    check(checks["final_service_stopped"], "The verifier left its managed service running")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--browser", action="store_true")
    arguments = parser.parse_args()
    report = arguments.report_dir.resolve()
    report.mkdir(parents=True, exist_ok=True)
    evidence = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "status": "running",
        "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "boundary": "Synthetic audio verifies software behavior, not detection accuracy. See desktop_entry_execution for the exact platform entry exercised. Playwright separately verifies the rendered interface in its own Chromium browser; it does not verify the system default browser.",
    }
    try:
        verify(
            arguments.source.resolve(),
            arguments.work_dir.resolve(),
            report,
            arguments.browser,
            evidence,
        )
        evidence["status"] = "passed"
    except BaseException as exc:
        evidence["status"] = "failed"
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            collect_diagnostics(arguments.work_dir.resolve(), report, evidence)
        except Exception as exc:
            evidence["diagnostics_error"] = f"{type(exc).__name__}: {exc}"
        evidence["finished_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (report / "evidence.json").write_text(
            json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(
            f"Desktop verification {evidence['status']}. Evidence: {report / 'evidence.json'}",
            flush=True,
        )


if __name__ == "__main__":
    main()
