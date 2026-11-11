# AI Song Detection

Run AI music screening locally through a web interface, HTTP API, or command line. The application uses the MIT-licensed [lofcz/ai-music-detector](https://github.com/lofcz/ai-music-detector) fakeprint model and runs on a CPU, without a GPU, paid inference API, or training dependencies.

The small ONNX model is included. Audio is processed on the machine running the application and is not sent to an external detection service.

## Quick start

Requirements: Python 3.11–3.13, [uv](https://docs.astral.sh/uv/getting-started/installation/), and FFmpeg with `ffprobe` on your `PATH`.

```bash
# macOS
brew install uv ffmpeg

# From the repository root
uv sync --frozen
./start.sh
```

On Debian/Ubuntu, install FFmpeg with `sudo apt-get install ffmpeg` and install uv using its installation guide. Open [http://127.0.0.1:8000](http://127.0.0.1:8000), choose an audio file, and select **Analyze track**. The default listener accepts connections from this machine only.

To use another local port:

```bash
./start.sh --port 8001
```

### Command line

```bash
uv run ai-song-detection detect song.mp3
uv run ai-song-detection detect song.mp3 another-song.flac --json
```

JSON mode writes one JSON object per input file. The command exits with status 1 if any file fails.

### HTTP API

```bash
curl -F 'file=@song.mp3' http://127.0.0.1:8000/api/v1/detect
curl http://127.0.0.1:8000/health
```

Interactive API documentation is available at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). See [Operations](docs/operations.md) for response fields, limits, and errors.

### Docker

```bash
docker compose up --build
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The image includes Python, FFmpeg, dependencies, and the model. Compose binds the host port to localhost and runs a non-root container with a read-only root filesystem and temporary storage. Building the image requires network access; inference does not.

## Results and limits

- `likely_ai_generated`: AI score above 0.6.
- `likely_human_created`: AI score below 0.4.
- `uncertain`: AI score from 0.4 through 0.6, inclusive.

The score is an uncalibrated model output, not a verified probability that a song is AI-generated. The uncertainty band is an initial product policy and has not been validated against an independent evaluation set.

The web interface and API accept one file up to **100 MiB**, with at least **10 seconds** of audio. Supported extensions are MP3, WAV, FLAC, M4A, AAC, OGG, Opus, AIFF/AIF, and WMA, subject to decoder support. Audio must be mono or stereo at 16–96 kHz. Analysis uses the **first 300 seconds**; responses disclose analyzed duration and truncation. One upload or analysis runs at a time per server process.

The model targets artifacts from **Suno ≤ 5 and Udio ≤ 1.5**. Other generators, future generator versions, mixed production, and heavily modified audio are not validated. Detection cannot establish authorship, copyright ownership, or exact production history.

## Accuracy and cost

Upstream [reports 99.88% accuracy](https://github.com/lofcz/ai-music-detector/tree/6ba389e94a179ac90f3eb134b741ef37baa30434#performance) on its held-out set of 17,866 samples. This project has not independently reproduced that result or established 99% accuracy on user uploads. Functional tests verify software behavior and preprocessing compatibility; they do not measure detection accuracy.

Local CPU inference avoids per-request detection service fees. Latency and actual cost depend on hardware, song length, concurrency, and hosting. Use the [Evaluation Plan](docs/evaluation.md) before publishing quality, speed, or cost claims.

## Development

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
```

Project content is in English. Keep credentials and private audio out of Git. The bundled, attributed model is the intentional exception to the general rule against committing model artifacts.

## Documentation and license

- [Product scope](docs/product-scope.md)
- [Operations and API contract](docs/operations.md)
- [Evaluation plan](docs/evaluation.md)
- [Verification record](docs/verification.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

Original project code is licensed under [Apache 2.0](LICENSE). The upstream model and adapted inference method retain their [MIT notice](third_party/ai-music-detector/LICENSE). Model provenance, pinned upstream revision, and checksum are included in the package assets. Other dependencies retain their respective licenses.
