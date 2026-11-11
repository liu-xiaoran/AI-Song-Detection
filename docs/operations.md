# Operations

## Run locally

Requirements: Python 3.11–3.13, uv, and FFmpeg including `ffprobe` on `PATH`.

```bash
uv sync --frozen
./start.sh
```

The default address is `http://127.0.0.1:8000`. Stop the foreground process with Ctrl+C. To change the port, use `./start.sh --port 8001`. `start.sh` synchronizes locked runtime dependencies without the development group before starting the server.

For an existing virtual environment without uv, run `pip install -e .` and then `ai-song-detection serve`. The lockfile-based uv workflow is preferred for reproducibility.

```bash
# Local files, one JSON result per file
uv run ai-song-detection detect song.mp3 another-song.wav --json

# Container with FFmpeg included
# Host port is bound to 127.0.0.1 by compose.yaml.
docker compose up --build
```

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

`GET /health` returns `status`, application `version`, `model_loaded`, and `ffmpeg_available`. HTTP 200 means model and both FFmpeg executables are available; HTTP 503 reports `degraded` if a required capability is missing. Availability checks do not prove that every codec works. `GET /docs` provides interactive documentation and `GET /openapi.json` exposes the schema.

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
```

Tests verify implementation behavior and preprocessing compatibility. Establish accuracy, latency, and cost separately using the [Evaluation Plan](evaluation.md).
