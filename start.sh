#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    printf '%s\n' 'FFmpeg is required. Install with: brew install ffmpeg (macOS), or apt-get install ffmpeg (Debian/Ubuntu).'
    exit 1
fi
if command -v uv >/dev/null 2>&1; then
    uv sync --frozen --no-dev
    exec uv run --frozen --no-dev ai-song-detection serve "$@"
fi
if [ -x .venv/bin/ai-song-detection ]; then
    exec .venv/bin/ai-song-detection serve "$@"
fi
printf '%s\n' 'Install uv, or create a Python 3.11-3.13 virtual environment and run: pip install -e .'
exit 1
