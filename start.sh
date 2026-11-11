#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -x .venv/bin/python ]; then
    exec .venv/bin/python -m ai_song_detection launch "$@"
fi
printf '%s\n' 'Run Install.command first, or set up a development environment with: uv sync --frozen'
exit 1
