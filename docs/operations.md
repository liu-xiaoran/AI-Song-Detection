# Operations

## Install and open from the desktop

Extract the complete project archive, then double-click `Install.command` on macOS or `Install.cmd` on Windows x64. macOS Apple Silicon and Intel have separate pinned native components, selected automatically. The initial installation downloads a private uv/Python runtime, FFmpeg/ffprobe, and locked application dependencies. No existing Python, Git, Homebrew, or administrator access is required.

| Location | macOS | Windows |
| --- | --- | --- |
| Application root | `~/Library/Application Support/AI Song Detection` | `%LOCALAPPDATA%\AI Song Detection` |
| Managed service state and logs | `state/` below the application root | `state\` below the application root |
| Command wrapper | `bin/ai-song-detection` below the application root | `bin\ai-song-detection.cmd` below the application root |
| Desktop start entry | `AI Song Detection.command` | `AI Song Detection.lnk` |
| Desktop stop entry | `Stop AI Song Detection.command` | `Stop AI Song Detection.lnk` |

The installer creates an independent application copy in `releases/<source-hash>/`, with its own virtual environment. `current.json` records the selected release, Python, and decoder paths; the command wrapper uses those installed paths. The extracted source folder is not needed afterward. Runtime downloads and cached packages remain under the application root. No global PATH or system Python is changed. See [installer dependency provenance](../install/README.md) for pinned versions, checksums, and component notices.

Installation opens the app by default. Pass `--no-launch` to the installation entry to skip that step. For an isolated installation, set `AI_SONG_DETECTION_INSTALL_DIR` and `AI_SONG_DETECTION_DESKTOP_DIR` before running the entry; these overrides apply to the bootstrap and the application installer together. Failed setup can be retried. Candidate checks run before switching releases; older release directories are retained. There is no separate automatic-update or uninstall command.

Double-click the start entry to launch or reopen the app in the default browser. The service runs in the background. A healthy existing instance is reused; an occupied preferred port leads to another available local port. The launcher waits for model and decoder readiness before opening the browser. Failure messages identify the service log rather than opening an unusable page.

Closing a browser tab or its window leaves the detector running. Use the desktop stop entry or the `stop` command to exit gracefully. Reopen the start entry to resume. Daily launch and detection do not download dependencies or update the application.

Unsigned-download checks may produce macOS Gatekeeper or Windows SmartScreen warnings. The Windows bootstrap uses a process-scoped PowerShell policy option and does not change global execution policy; enterprise policy can still block it. The installer does not disable operating-system protections. These entry scripts are not signed/notarized consumer installers.

## Command-line lifecycle and development

The installed wrapper exposes the same interface as the package:

```bash
# macOS
"$HOME/Library/Application Support/AI Song Detection/bin/ai-song-detection" launch
"$HOME/Library/Application Support/AI Song Detection/bin/ai-song-detection" status --json
"$HOME/Library/Application Support/AI Song Detection/bin/ai-song-detection" stop
```

```powershell
# Windows PowerShell
& "$env:LOCALAPPDATA\AI Song Detection\bin\ai-song-detection.cmd" launch
& "$env:LOCALAPPDATA\AI Song Detection\bin\ai-song-detection.cmd" status --json
& "$env:LOCALAPPDATA\AI Song Detection\bin\ai-song-detection.cmd" stop
```

From an already-prepared development checkout:

```bash
uv run ai-song-detection launch
uv run ai-song-detection launch --port 8001 --no-browser --json
uv run ai-song-detection status --json
uv run ai-song-detection stop --json
uv run ai-song-detection detect song.mp3 another-song.wav --json
```

`launch` prefers port 8000 but prints the actual selected address. `status` reports a running, identity-verified managed instance, its address, version, PID, and log path. The default startup timeout is 45 seconds. `stop` requests graceful shutdown and waits up to 90 seconds by default; it does not terminate another application based on an old PID file. JSON output never contains the private control token.

Private instance state is protected by a per-user file lock. The service identity includes application, instance, and version fields. Start and stop operations use localhost directly, independently of HTTP proxy environment settings. Browser-originated stop requests are denied; the command uses a private instance token.

The service log is `state/service.log` under the application root. A log over 5 MiB is moved to `service.log.1` at the next start. If launch fails, inspect the printed log path. A missing decoder should be repaired through the installer. A startup error does not justify terminating the program occupying the preferred port.

Development requires Python 3.11–3.13, uv, and FFmpeg/ffprobe on PATH. Run `uv sync --frozen` once to prepare the checkout. `./start.sh` on macOS/Linux launches its existing virtual environment without dependency synchronization. For a foreground service, use `uv run ai-song-detection serve --port 8001` and stop it with Ctrl+C. Foreground `serve` is independent of the managed instance and is not stopped by the managed `stop` command.

For an existing virtual environment without uv, run `pip install -e .` and then use its `ai-song-detection` executable. The lockfile-based uv workflow is preferred for reproducibility.

For Docker, run `docker compose up --build`; Compose binds the host port to `127.0.0.1:8000`. Container lifecycle is managed with Docker, separately from the desktop launcher's state.

The model is bundled and checksum-verified at startup. An invalid or missing model prevents startup. CPU inference uses one ONNX Runtime thread and needs no external detection service. Package installation and image builds need network access; inference does not.

## HTTP contract

`POST /api/v1/detect` accepts `multipart/form-data` with exactly one binary field named `file`. No additional fields are accepted.

```bash
curl -F 'file=@song.mp3' http://127.0.0.1:8000/api/v1/detect
```

Successful requests return HTTP 200 with these fields:

| Field | Meaning |
| --- | --- |
| `filename` | Sanitized display filename; never a server path. |
| `assessment` | `likely_ai_generated`, `likely_human_created`, or `uncertain`. |
| `ai_score` | Float in [0, 1]; uncalibrated model output. |
| `threshold` | Upstream binary reference threshold, 0.5; the application uses the uncertainty band described below. |
| `audio_duration_seconds` | Reported or decoded duration; a decoder estimate may be used when exact duration is unavailable. |
| `analyzed_duration_seconds` | Duration actually analyzed, capped at 300 seconds. |
| `truncated` | Whether only the beginning of a longer file was analyzed. |
| `processing_time_ms` | Decode, preprocess, and inference elapsed time; excludes HTTP upload and response transfer. |
| `model` | `name`, `version`, `sha256`, and `upstream_commit`. |
| `warnings` | Score interpretation, coverage, and validation limitations. |

Scores below 0.4 produce `likely_human_created`; scores above 0.6 produce `likely_ai_generated`; both endpoints and the values between them produce `uncertain`. This policy has not been independently validated.

`GET /health` returns `app_id`, `instance_id`, `pid`, `status`, application `version`, `model_loaded`, and `ffmpeg_available`, with a no-store cache header. `app_id` is `ai-song-detection`; an unmanaged foreground service has an empty instance ID. HTTP 200 means model and both FFmpeg executables are available; HTTP 503 reports `degraded` if a required capability is missing. Availability checks do not prove that every codec works. `GET /docs` provides interactive documentation and `GET /openapi.json` exposes the schema.

The main page polls readiness every five seconds while visible, and checks again before submitting audio. Connection loss disables analysis and presents `Retry connection`; the selected track remains available after reconnecting. A request failure does not leave a previous result displayed as the new result.

## Input and resource limits

- HTTP file size: 100 MiB (104,857,600 bytes). Total request-body allowance includes another 1 MiB for multipart overhead.
- One upload or analysis per server process, including multipart parsing. An additional request receives HTTP 429 rather than joining a queue.
- Minimum audio: 10 seconds. Analysis covers the first 300 seconds.
- Native sample rate: 16,000–96,000 Hz; mono or stereo only. Resampling to 16 kHz occurs before feature extraction.
- HTTP extensions: `.mp3`, `.wav`, `.flac`, `.m4a`, `.aac`, `.ogg`, `.opus`, `.aiff`, `.aif`, `.wma`. Decoding must also succeed.
- FFprobe timeout: 10 seconds. FFmpeg decode timeout: 60 seconds, with bounded output and at most 301 seconds decoded.
- Upload parsing and upload copying each have a 120-second limit. Inference is outside those upload timeouts.

The CLI does not impose the HTTP file-size or filename-extension check. Audio validation and bounded decoding still apply. Do not increase worker count as a substitute for a shared admission-control design; the concurrency guard is per process.

## Errors

Application errors use `{"detail":{"code":"...","message":"..."}}`.

| HTTP status | Code | Meaning |
| --- | --- | --- |
| 400 | `invalid_length` | Malformed `Content-Length`. |
| 400 | `invalid_upload` | Malformed multipart form or too many fields/files. |
| 403 | `origin_not_allowed` | Browser submission comes from a different origin. |
| 408 | `upload_timeout` | Upload parsing or copying exceeded its time limit. |
| 413 | `file_too_large` | File or request-body limit exceeded. |
| 415 | `unsupported_format` | Filename extension is not accepted. |
| 422 | `missing_file`, `empty_file` | Required file is absent or empty. |
| 422 | `invalid_audio`, `unsupported_audio` | Decode failed or channel/sample-rate limits were exceeded. |
| 422 | `audio_too_short`, `insufficient_audio` | Too little audio, silence, or insufficient spectral evidence. |
| 422 | `decoder_unavailable`, `decode_timeout` | FFmpeg is missing or decoding timed out. |
| 422 | `file_not_found` | Input disappeared before analysis; also used by the CLI. |
| 429 | `busy` | Another request is uploading or analyzing. |
| 500 | `analysis_failed` | Unexpected analysis failure; server logs contain diagnostic details. |

CLI JSON errors contain `filename`, `error`, and `code`. Any failed input produces a final exit status of 1; successful files still produce results.

## Storage, access, and deployment boundaries

The application does not send audio to an external API, retain a results database, or train on uploads. Multipart processing may spool to temporary storage. Request-scoped uploads and decoder temporary files are closed and removed after processing, including handled errors. A process crash or forced termination may leave temporary files for the operating system or operator to clean up. This is cleanup behavior, not a secure-erasure guarantee.

There is no authentication. Localhost is the default intended scope. Cross-origin browser POSTs are rejected, but this is not an authentication mechanism. Binding with `--host 0.0.0.0` exposes the unauthenticated service to reachable machines; it does not configure TLS, firewall rules, access controls, or prove LAN reachability.

Before a shared or public deployment, provide authenticated access, TLS, request-size and timeout limits, abuse controls, and an explicit retention policy. Configure a reverse proxy to preserve the effective host and scheme consistently with the browser origin check. Proxy buffering, access logs, infrastructure logs, backups, and temporary storage can have their own retention behavior. The application logs unexpected analysis failures; review operator logging and filesystem access before handling private recordings.

Compose uses a non-root user, a read-only root filesystem, 512 MiB of temporary filesystem space, a 2 GiB memory limit, and two CPUs. These defaults are a local operating baseline, not a validated production capacity claim. This repository does not deploy or expose a public service automatically.

## Development checks

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
node --test tests/browser/connection.test.cjs
```

Tests verify implementation behavior and preprocessing compatibility. Establish accuracy, latency, and cost separately using the [Evaluation Plan](evaluation.md).
