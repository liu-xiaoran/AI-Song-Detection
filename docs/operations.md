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

Installation opens the app by default. Pass `--no-launch` to the installation entry to skip that step. For an isolated installation, set `AI_SONG_DETECTION_INSTALL_DIR` and `AI_SONG_DETECTION_DESKTOP_DIR` before running the entry; these overrides apply to the bootstrap and the application installer together. Failed setup can be retried. Candidate checks run before switching releases; older release directories are retained. The explicit `update` command checks a candidate before switching; updates are never automatic. Cleanup and uninstall commands preview their scope before `--apply`.

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

`launch` prefers port 8000 but prints the actual selected address. Add `--strict-port` to require exactly the requested port; this also rejects reusing an instance on a different port. `status --url` prints only a ready managed URL and otherwise exits 1. `status` reports a running, identity-verified managed instance, its address, version, PID, and log path. The default startup timeout is 45 seconds. `stop` requests graceful shutdown and waits up to 90 seconds by default; it does not terminate another application based on an old PID file. JSON output never contains the private control token.

Private instance state is protected by a per-user file lock. The service identity includes application, instance, and version fields. Start and stop operations use localhost directly, independently of HTTP proxy environment settings. Browser-originated stop requests are denied; the command uses a private instance token.

The service log is `state/service.log` under the application root. Windows desktop startup requests and failures are also recorded in `state/desktop.log`. A log over 5 MiB is moved to `service.log.1` at the next start. If launch fails, inspect the printed log path. A missing decoder should be repaired through the installer. A startup error does not justify terminating the program occupying the preferred port.

Development requires Python 3.11–3.13, uv, and FFmpeg/ffprobe on PATH. Run `uv sync --frozen` once to prepare the checkout. `./start.sh` on macOS/Linux launches its existing virtual environment without dependency synchronization. For a foreground service, use `uv run ai-song-detection serve --port 8001` and stop it with Ctrl+C. Foreground `serve` is independent of the managed instance and is not stopped by the managed `stop` command.

For an existing virtual environment without uv, run `pip install -e .` and then use its `ai-song-detection` executable. The lockfile-based uv workflow is preferred for reproducibility.

For Docker, run `docker compose up --build`; Compose binds the host port to `127.0.0.1:8000`. Container lifecycle is managed with Docker, separately from the desktop launcher's state.

The model is bundled and checksum-verified at startup. An invalid or missing model prevents startup. CPU inference uses one ONNX Runtime thread and needs no external detection service. Package installation and image builds need network access; inference does not.

## Batch detection and reports

```bash
ai-song-detection detect ./songs another.flac --recursive --start 30 --duration 60 --output reports.csv
ai-song-detection detect ./songs --output reports.json --retries 1 --json
```

Directory scans include supported extensions; subdirectories require `--recursive`. Explicit file inputs still go through decoder validation. Resolved paths are deduplicated. `--retries` accepts 0–3 retries of transient runtime/file errors; invalid content, missing files, and permission failures are not retried. Processing stays serial. A summary goes to stderr; `--json` keeps one JSON object per input on stdout. Output supports JSON, JSONL, and CSV and is written atomically; an output path cannot overwrite an input. CSV cells that could be spreadsheet formulas are neutralized.

The browser keeps a serial multi-file queue and session results in memory, without localStorage or an audio database. Add files during a job, cancel individual items, retry failures, revisit results, and copy/download JSON or CSV. Window settings are captured when each item is added. XHR shows transferred upload bytes; later stages are reported by the server rather than estimated percentages. Cancellation during upload is requested after upload returns a job ID. Running work stays `cancelling` until its worker exits; hashing/decoding check cancellation, owned decoder processes are terminated and reaped, and preprocessing/inference check between bounded operations. There is no immediate mid-ONNX interruption guarantee.

Closing a tab loses its browser history and queued browser files; already accepted server jobs continue. Keep exported reports for durable history. A known job ID can be polled again for up to one hour, subject to the 100-terminal-report limit and service lifetime. Upload timeout after server acceptance can be ambiguous: the browser pauses further uploads until the service is restarted rather than silently submitting a duplicate. Reports never imply whole-song coverage when only a window was analyzed.

## Maintenance and offline installation

Run these through the installed wrapper (or a shell entry created with `shell-setup`):

```bash
ai-song-detection doctor --json
ai-song-detection logs --lines 100 --follow
ai-song-detection diagnostics --output diagnostics.zip
ai-song-detection update
ai-song-detection update --source /path/to/extracted/source --no-launch
ai-song-detection cleanup --keep 2
ai-song-detection stop
ai-song-detection cleanup --keep 2 --cache --apply
ai-song-detection uninstall
ai-song-detection uninstall --apply
ai-song-detection shell-setup --directory "$HOME/.local/bin"
```

`doctor` checks the interpreter, model checksum/load, FFmpeg/ffprobe executables, installation boundaries, and managed status. A stopped service is an available status, not itself a missing dependency. `logs` reads the service log; Ctrl+C ends follow mode. Diagnostics include health facts with private directory prefixes removed, and omit raw logs, environment variables, audio, reports, and private control state. Review the ZIP before sharing.

`update` reads the main-branch commit of this project's own GitHub repository, then downloads that exact SHA over HTTPS. It uses the same locked installer, candidate checks, rollback behavior, and component checksum checks. This is a commit-pinned source update, not a signed release channel. A local `--source` supports a reviewed source tree. Changed bootstrap versions may require downloading the source and running Install again.

`cleanup` lists paths and reclaimable bytes. Current, executing, and identified active releases are protected. An unidentified or legacy active service conservatively protects all releases. `--cache` also removes downloaded archives and package caches. Create and test an offline bundle before clearing these caches. After clearing them, offline reinstall capability requires repopulating the complete caches online and testing a restore; creating another bundle alone does not restore missing dependencies. `uninstall --apply` first requests authenticated shutdown, removes owned application directories and unchanged registered shortcuts, and preserves unknown top-level files. Windows runtime deletion is deferred until the CLI exits and reports a result-file path. These operations never kill a process merely because its PID was saved in old state.

To prepare an offline installer on an already installed machine:

```bash
ai-song-detection bundle --output /path/to/Offline-Installer
```

Copy the entire output folder to another computer with the same OS and CPU architecture. Open `Restore.command` on Mac or `Restore.cmd` on Windows. The destination must be a new or empty per-user installation directory; existing installations are left untouched. `--install-dir`, `--desktop-dir`, and `--no-launch` support controlled restores. The folder includes private Python/uv, verified decoder assets, locked dependency caches and the model/source, and excludes service state, audio, reports, old releases and virtual environments. Restore verifies the file manifest and rebuilds the environment at its final path, with uv offline and dependency downloads disabled. Do not remove caches before creating it. Component checksums detect corruption; they are not publisher signatures. Bundles are generated per platform from an installation, not universal signed binaries.

## HTTP contract

`POST /api/v1/detect` accepts `multipart/form-data` with exactly one binary field named `file`. No additional form fields are accepted. Optional query parameters are `start_seconds` (finite, non-negative; default 0) and `duration_seconds` (10–300; default 300). Invalid query parameters return the framework validation response with HTTP 422.

```bash
curl -F 'file=@song.mp3' http://127.0.0.1:8000/api/v1/detect
```

Successful requests return HTTP 200 with these fields:

| Field | Meaning |
| --- | --- |
| `filename` | Sanitized display filename; never a server path. |
| `assessment` | `likely_ai_generated`, `likely_human_created`, or `uncertain`. |
| `ai_score` | Model output as a float in [0, 1], used by the assessment policy. |
| `threshold` | Deprecated legacy binary reference, 0.5. Do not use it to reproduce the application assessment. |
| `upstream_binary_threshold` | Explicit upstream binary reference, 0.5. |
| `decision_policy` | Assessment policy metadata, including ID, version, `human_below: 0.4`, `ai_above: 0.6`, and the inclusive uncertainty interval. |
| `report_id`, `analyzed_at`, `application_version` | Unique report ID, UTC analysis timestamp, and software version. |
| `input_sha256`, `input_size_bytes` | Full input content fingerprint and bytes, including audio outside the analyzed window. |
| `analyzed_start_seconds`, `analyzed_end_seconds`, `requested_duration_seconds` | Selected start, actual end, and requested window duration. |
| `audio_duration_seconds` | Reported or decoded duration; a decoder estimate may be used when exact duration is unavailable. |
| `analyzed_duration_seconds` | Duration actually analyzed, capped at 300 seconds. |
| `truncated` | Whether any original audio was omitted, before or after the selected interval. |
| `processing_time_ms` | Hash, decode, preprocess, and inference elapsed time; excludes HTTP upload and response transfer. |
| `model` | `name`, `version`, `sha256`, and `upstream_commit`. |
| `warnings` | Analysis notices, score interpretation, and selected-window coverage. |

Scores below 0.4 produce `likely_human_created`; scores above 0.6 produce `likely_ai_generated`; both endpoints and the values between them produce `uncertain`.

For queueing and cancellation use:

```bash
curl -F 'file=@song.mp3' 'http://127.0.0.1:8000/api/v1/jobs?start_seconds=30&duration_seconds=60'
curl http://127.0.0.1:8000/api/v1/jobs/JOB_ID
curl -X POST http://127.0.0.1:8000/api/v1/jobs/JOB_ID/cancel
```

Upload returns 202 with `id`, `status`, `stage`, `created_at`, `updated_at`, `result`, and `error`. Polling and cancel return the same structure with no-store headers. Status is `queued`, `running`, `cancelling`, `completed`, `failed`, or `cancelled`. Stages are `queued`, `hashing`, `decoding`, `preprocessing`, `inference`, and `complete`; stage is not a percentage. Completed jobs contain the result contract above; failures contain `error: {code,message}`. Cancellation is idempotent; only terminal `cancelled` confirms the worker has ended. Unknown/expired IDs return 404 `job_not_found`. Reports are memory-only, retained for one hour and at most 100 terminal jobs; restart loses them. Audio is removed when a job ends. A temporary-file cleanup failure is reported as `cleanup_failed`; admission pauses while cleanup is retried, rather than losing the worker or accumulating more uploads.

`GET /health` returns `app_id`, `instance_id`, `pid`, `status`, application `version`, `model_loaded`, and `ffmpeg_available`, with a no-store cache header. `app_id` is `ai-song-detection`; every service startup has a fresh instance ID, including foreground operation; this lets clients distinguish a restart after an ambiguous network failure. HTTP 200 means model and both FFmpeg executables are available; HTTP 503 reports `degraded` if a required capability is missing. Availability checks do not prove that every codec works. `GET /docs` provides interactive documentation and `GET /openapi.json` exposes the schema.

The main page polls readiness every five seconds while visible, and checks again before submitting audio. Connection loss disables analysis and presents `Retry connection`; selected files remain available after reconnecting. A request failure does not leave a previous result displayed as the new result.

## Input and resource limits

- HTTP file size: 100 MiB (104,857,600 bytes). Total request-body allowance includes another 1 MiB for multipart overhead.
- One analysis per process. The jobs API admits up to nine uploading/waiting/running jobs and returns 429 `queue_full` at capacity; the legacy synchronous API returns 429 `busy` while other work is admitted.
- Minimum selected audio: 10 seconds. Default coverage is the first 300 seconds; choose a start and 10–300-second duration.
- Native sample rate: 16,000–96,000 Hz; mono or stereo only. Resampling to 16 kHz occurs before feature extraction.
- HTTP extensions: `.mp3`, `.wav`, `.flac`, `.m4a`, `.aac`, `.ogg`, `.opus`, `.aiff`, `.aif`, `.wma`. Decoding must also succeed.
- FFprobe timeout: 10 seconds. FFmpeg decode timeout: 60 seconds, with bounded output and at most 301 seconds decoded.
- Upload parsing and copying share a 120-second limit. Inference is outside those upload timeouts.

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

The application does not send audio to an external API, retain a results database, or train on uploads. Multipart processing may spool to temporary storage. Request/job-scoped uploads and decoder temporary files are closed and removed after processing, including handled errors. A process crash or forced termination may leave temporary files for the operating system or operator to clean up. This is cleanup behavior, not a secure-erasure guarantee.

There is no authentication. Localhost is the default intended scope. Cross-origin browser POSTs are rejected, but this is not an authentication mechanism. Binding with `--host 0.0.0.0` exposes the unauthenticated service to reachable machines; it does not configure TLS, firewall rules, access controls, or prove LAN reachability.

Before a shared or public deployment, provide authenticated access, TLS, request-size and timeout limits, abuse controls, and an explicit retention policy. Configure a reverse proxy to preserve the effective host and scheme consistently with the browser origin check. Proxy buffering, access logs, infrastructure logs, backups, and temporary storage can have their own retention behavior. The application logs unexpected analysis failures; review operator logging and filesystem access before handling private recordings.

Compose uses a non-root user, a read-only root filesystem, 1536 MiB of temporary filesystem space, a 2 GiB memory limit, and two CPUs. These defaults are a local operating baseline, not a validated production capacity claim. This repository does not deploy or expose a public service automatically.

## Development checks

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
node --test tests/browser/connection.test.cjs
```

Tests cover application behavior and preprocessing compatibility. See the [Evaluation Plan](evaluation.md) for dataset evaluation and performance measurement.
