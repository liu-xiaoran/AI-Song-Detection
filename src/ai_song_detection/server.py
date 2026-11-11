"""Single-worker local HTTP service with bounded uploads and temporary storage."""

import asyncio
import logging
import os
import secrets
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import APP_ID, __version__
from .detector import AudioError, Detector
from .schemas import DetectionResult

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_UPLOAD_BYTES + 1024 * 1024
UPLOAD_TIMEOUT_SECONDS = 120
STATIC_DIR = Path(__file__).parent / "static"
EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".aiff", ".aif", ".wma"}
logger = logging.getLogger(__name__)


class BodyLimitMiddleware:
    """Count actual streamed body bytes, including requests without Content-Length."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            response = JSONResponse(
                {"detail": {"code": "invalid_length", "message": "Invalid Content-Length header."}},
                status_code=400,
            )
            return await response(scope, receive, send)
        if declared > MAX_REQUEST_BYTES:
            response = JSONResponse(
                {
                    "detail": {
                        "code": "file_too_large",
                        "message": "The upload exceeds the 100 MB file limit.",
                    }
                },
                status_code=413,
            )
            return await response(scope, receive, send)
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_REQUEST_BYTES:
                    raise HTTPException(
                        413,
                        detail={
                            "code": "file_too_large",
                            "message": "The upload exceeds the 100 MB file limit.",
                        },
                    )
            return message

        await self.app(scope, bounded_receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.detector = Detector()
    app.state.active_request = False
    app.state.instance_id = os.environ.get("AI_SONG_DETECTION_INSTANCE_ID", "")
    app.state.control_token = os.environ.get("AI_SONG_DETECTION_CONTROL_TOKEN", "")
    yield


app = FastAPI(
    title="AI Song Detection",
    version=__version__,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(BodyLimitMiddleware)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def restrict_browser_origin(request: Request, call_next):
    # The local service has no authentication. Block cross-origin browser submissions.
    origin = request.headers.get("origin")
    if (
        request.method == "POST"
        and origin
        and origin.rstrip("/") != str(request.base_url).rstrip("/")
    ):
        return JSONResponse(
            {
                "detail": {
                    "code": "origin_not_allowed",
                    "message": "Submit audio from this application's own page.",
                }
            },
            status_code=403,
        )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'"
    )
    return response


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/docs", include_in_schema=False)
async def api_docs():
    return FileResponse(STATIC_DIR / "api-docs.html")


@app.get("/health")
async def health(request: Request):
    loaded = getattr(request.app.state, "detector", None) is not None
    ffmpeg = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
    return JSONResponse(
        {
            "app_id": APP_ID,
            "instance_id": getattr(request.app.state, "instance_id", ""),
            "pid": os.getpid(),
            "status": "ok" if loaded and ffmpeg else "degraded",
            "version": __version__,
            "model_loaded": loaded,
            "ffmpeg_available": ffmpeg,
        },
        status_code=200 if loaded and ffmpeg else 503,
        headers={"Cache-Control": "no-store"},
    )


@app.post("/_control/stop", include_in_schema=False)
async def stop_managed_service(request: Request):
    """Private launcher control; never accept browser-originated shutdown requests."""
    token = getattr(request.app.state, "control_token", "")
    shutdown = getattr(request.app.state, "request_shutdown", None)
    if not token or not callable(shutdown):
        raise HTTPException(404, detail="Not found")
    provided = request.headers.get("X-AI-Song-Control", "")
    if (
        not request.client
        or request.client.host not in {"127.0.0.1", "::1"}
        or "origin" in request.headers
        or not secrets.compare_digest(provided.encode("utf-8"), token.encode("utf-8"))
    ):
        raise HTTPException(403, detail="Control request denied")
    return JSONResponse(
        {"status": "stopping"},
        status_code=202,
        headers={"Cache-Control": "no-store"},
        background=BackgroundTask(shutdown),
    )


def fail(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


@app.post(
    "/api/v1/detect",
    response_model=DetectionResult,
    responses={
        400: {"description": "Malformed multipart upload"},
        408: {"description": "Upload timeout"},
        413: {"description": "Upload exceeds 100 MB"},
        415: {"description": "Unsupported file extension"},
        422: {"description": "Missing, invalid, short, or unsupported audio"},
        429: {"description": "Another analysis is in progress"},
        500: {"description": "Analysis failed"},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {"file": {"type": "string", "format": "binary"}},
                    }
                }
            },
        }
    },
)
async def detect(request: Request):
    """Analyze one uploaded audio file; remove temporary files after processing."""
    if request.app.state.active_request:
        raise fail(429, "busy", "Another song is being analyzed. Please try again shortly.")
    # No await between checking and acquiring: one request per process, including upload.
    request.app.state.active_request = True
    try:
        try:
            async with asyncio.timeout(UPLOAD_TIMEOUT_SECONDS):
                form = await request.form(max_files=1, max_fields=0, max_part_size=MAX_UPLOAD_BYTES)
        except StarletteHTTPException as exc:
            if isinstance(exc.detail, dict):
                raise
            raise fail(400, "invalid_upload", "Submit one audio file in the 'file' field.") from exc
        try:
            upload = form.get("file")
            if len(form.multi_items()) != 1 or not isinstance(upload, UploadFile):
                raise fail(422, "missing_file", "Submit one audio file in the 'file' field.")
            filename = (upload.filename or "audio").replace("\\", "/").rsplit("/", 1)[-1][:255]
            suffix = Path(filename).suffix.lower()
            if suffix not in EXTENSIONS:
                raise fail(415, "unsupported_format", "Choose a supported audio file format.")
            if upload.size is not None and upload.size > MAX_UPLOAD_BYTES:
                raise fail(413, "file_too_large", "Choose an audio file of 100 MB or less.")
            with tempfile.TemporaryDirectory(prefix="ai-song-") as directory:
                path = Path(directory) / ("upload" + suffix)
                size = 0
                async with asyncio.timeout(UPLOAD_TIMEOUT_SECONDS):
                    with path.open("wb") as target:
                        while chunk := await upload.read(1024 * 1024):
                            size += len(chunk)
                            if size > MAX_UPLOAD_BYTES:
                                raise fail(
                                    413, "file_too_large", "Choose an audio file of 100 MB or less."
                                )
                            target.write(chunk)
                if size == 0:
                    raise fail(422, "empty_file", "The uploaded file is empty.")
                await upload.close()
                # Inference is outside the upload timeout; do not delete an active thread's input.
                try:
                    return await run_in_threadpool(
                        request.app.state.detector.analyze, path, filename=filename
                    )
                except AudioError as exc:
                    raise fail(422, exc.code, str(exc)) from exc
                except Exception:
                    logger.exception("Audio analysis failed")
                    raise fail(
                        500, "analysis_failed", "Audio analysis failed. Please try another file."
                    )
        finally:
            await form.close()
    except TimeoutError as exc:
        raise fail(408, "upload_timeout", "The request took too long. Please try again.") from exc
    finally:
        request.app.state.active_request = False
