# AI Song Detection

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Español](README.es.md)

English is the primary project language, and this README is the source document for translations.

Run AI music screening locally through a web interface, HTTP API, or command line. The application uses the MIT-licensed [lofcz/ai-music-detector](https://github.com/lofcz/ai-music-detector) fakeprint model and runs on a CPU, without a GPU, paid inference API, or training dependencies.

The small ONNX model is included. Audio is processed on the machine running the application and is not sent to an external detection service.

## Desktop installation

Download and extract this project, then run the installer for your computer:

| Platform | First installation |
| --- | --- |
| macOS 13 or newer, Apple Silicon or Intel | Double-click `Install.command`. |
| Windows 10/11, x64 | Double-click `Install.cmd`. |

The installer prepares private Python, FFmpeg/ffprobe, and application dependencies, creates desktop start and stop entries, and opens the application. On Windows it also prepares a private Microsoft Visual C++ runtime for ONNX Runtime. Use `--no-launch` to install without opening a browser. It does not require an existing Python installation, Git, Homebrew, or administrator access, and does not change your global PATH. The first installation requires an internet connection. uv, FFmpeg, and Windows C++ runtime downloads are pinned and checksum-verified; see [installer dependencies](install/README.md).

After installation, double-click the desktop **AI Song Detection** entry. The launcher starts the local service, waits for the model and decoder to be ready, and opens your default browser. Select or drop multiple audio files and choose **Start queue**. Files run serially; each item shows upload progress, processing stage, and cancellation status. Choose a start offset and 10–300-second window before adding files. Session results can be revisited, copied, or downloaded as JSON/CSV. Later launches and detection work offline. The installed copy is independent of the extracted source folder.

Repeated clicks reopen the existing instance. If the preferred port is occupied by another application, the launcher chooses an available port. Closing the browser does not stop the detector; use the desktop **Stop AI Song Detection** entry or the `stop` command when finished.

macOS or Windows may show an origin or security warning for unsigned downloaded scripts. The installer does not disable Gatekeeper, SmartScreen, or enterprise security policy. These script installers are not signed consumer application packages.

See [Operations](docs/operations.md) for installation paths, command-line launch, logs, and troubleshooting. Platform verification evidence is recorded separately in [Verification](docs/verification.md).

### Command line

The installer prints its command-wrapper path. For example, launch the installed copy with:

```bash
# macOS
"$HOME/Library/Application Support/AI Song Detection/bin/ai-song-detection" launch
```

```powershell
# Windows PowerShell
& "$env:LOCALAPPDATA\AI Song Detection\bin\ai-song-detection.cmd" launch
```

The same wrapper accepts detection, diagnostics, maintenance, and offline-bundle commands. From a development checkout, use:

```bash
uv run ai-song-detection launch
uv run ai-song-detection status
uv run ai-song-detection stop
uv run ai-song-detection detect song.mp3
uv run ai-song-detection detect song.mp3 another-song.flac --json
uv run ai-song-detection detect ./songs --recursive --start 30 --duration 60 --output reports.csv
uv run ai-song-detection doctor --json
uv run ai-song-detection logs --lines 100
uv run ai-song-detection status --url
uv run ai-song-detection launch --port 8001 --strict-port
uv run ai-song-detection evaluate labeled-songs.csv --output evaluation.json
```

`launch` manages a background instance and opens the default browser. `serve` remains available for foreground operation, stopped with Ctrl+C. The launcher's `--no-browser` option is useful for automated checks. Detection JSON mode writes one JSON object per input file and exits with status 1 if any file fails.

For an installed desktop copy, `update` prepares and checks a new release before switching. `cleanup --keep 2` and `uninstall` preview their changes; add `--apply` to execute. Stop the service before cleaning old releases. Use `shell-setup --directory "$HOME/.local/bin"` to create a short command in a directory you choose; add that directory to your own shell PATH if needed. See [maintenance and offline installation](docs/operations.md#maintenance-and-offline-installation).

### HTTP API

```bash
curl -F 'file=@song.mp3' http://127.0.0.1:8000/api/v1/detect
curl http://127.0.0.1:8000/health
```

Use the address printed by `launch` or `status`; replace port `8000` in these examples if another was selected. Interactive API documentation is at `/docs` on that address. See [Operations](docs/operations.md) for response fields, limits, and errors.

### Docker

```bash
docker compose up --build
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The image includes Python, FFmpeg, dependencies, and the model. Compose binds the host port to localhost and runs a non-root container with a read-only root filesystem and temporary storage. Building the image requires network access; inference does not.

## Results and limits

- `likely_ai_generated`: AI score above 0.6.
- `likely_human_created`: AI score below 0.4.
- `uncertain`: AI score from 0.4 through 0.6, inclusive.

The AI score is the model output used by the decision policy above. Reports include the score, assessment, analyzed interval, and model details.

The web interface accepts a multi-file queue; each API upload accepts one file up to **100 MiB**, with at least **10 seconds** of audio. Supported extensions are MP3, WAV, FLAC, M4A, AAC, OGG, Opus, AIFF/AIF, and WMA, subject to decoder support. Audio must be mono or stereo at 16–96 kHz. Analysis defaults to the **first 300 seconds**, with an optional start offset and 10–300-second duration. Reports disclose the actual analyzed interval and whether audio was omitted. Only one analysis runs at a time. The jobs API admits up to nine pending jobs (one running plus eight waiting/uploading); the synchronous endpoint returns 429 while busy.

The model targets artifacts from **Suno ≤ 5 and Udio ≤ 1.5**. Detection assesses audio features; authorship, copyright ownership, and production history require their own supporting records.

## Model reference and runtime cost

Upstream [reports 99.88% accuracy](https://github.com/lofcz/ai-music-detector/tree/6ba389e94a179ac90f3eb134b741ef37baa30434#performance) on its held-out set of 17,866 samples.

Local CPU inference avoids per-request detection service fees. Latency and actual cost depend on hardware, song length, concurrency, and hosting. See the [Evaluation Plan](docs/evaluation.md) for dataset evaluation and performance measurement.

## Development

Development requires Python 3.11–3.13, [uv](https://docs.astral.sh/uv/getting-started/installation/), and FFmpeg/ffprobe on PATH. The desktop installer prepares its own environment instead.

```bash
uv sync --frozen
uv run ai-song-detection launch
uv run pytest
uv run ruff check .
node --test tests/browser/connection.test.cjs
```

On macOS/Linux, `./start.sh` launches an already-created development environment without syncing or downloading dependencies. Use `uv run ai-song-detection serve --port 8001` for a foreground service at a chosen port.

English is the primary project language; translated READMEs are provided for reference. Keep credentials and private audio out of Git. The bundled, attributed model is the intentional exception to the general rule against committing model artifacts.

## Documentation and license

- [Product scope](docs/product-scope.md)
- [Operations and API contract](docs/operations.md)
- [Evaluation plan](docs/evaluation.md)
- [Verification record](docs/verification.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

Original project code is licensed under [Apache 2.0](LICENSE). The upstream model and adapted inference method retain their [MIT notice](third_party/ai-music-detector/LICENSE). Model provenance, pinned upstream revision, and checksum are included in the package assets. Other dependencies retain their respective licenses.
