FROM python:3.12-slim-bookworm

RUN pip install --no-cache-dir uv==0.13.5
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY third_party ./third_party
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable && chown -R app:app /app
USER app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["ai-song-detection", "serve", "--host", "0.0.0.0", "--port", "8000"]
