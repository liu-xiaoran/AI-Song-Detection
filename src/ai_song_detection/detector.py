"""Bounded, CPU-only inference with lofcz/ai-music-detector's fakeprint model.

Feature extraction is adapted from upstream's MIT-licensed Python inference.py.
The resampler uses the sinc-Hann filter described by upstream SincResampler.cs;
it is evaluated as a polyphase FIR instead of requiring PyTorch at runtime.
See the packaged UPSTREAM.json and LICENSE files for provenance.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import onnxruntime as ort
import soundfile as sf
from scipy.fft import rfft
from scipy.ndimage import minimum_filter1d
from scipy.signal import upfirdn

from . import __version__

SAMPLE_RATE = 16000
N_FFT = 8192
MIN_DURATION = 10.0
MAX_DURATION = 300.0
MAX_SAMPLE_RATE = 96000
MAX_CHANNELS = 2
MAX_DECODE_SECONDS = MAX_DURATION + 1.0
MAX_DECODE_BYTES = int(MAX_DECODE_SECONDS * MAX_SAMPLE_RATE * MAX_CHANNELS * 4)
MEDIA_DEMUXERS = "wav,mp3,flac,ogg,mov,aac,aiff,asf"
MODEL_SHA256 = "af7a75c6ed457bc5b6941c8bc76aa06a66d48de40db944b761ed2bebfc0fbbd3"
UPSTREAM_COMMIT = "6ba389e94a179ac90f3eb134b741ef37baa30434"
ASSETS = Path(__file__).parent / "assets"
DECISION_POLICY = {
    "id": "fakeprint-screening-v1",
    "version": 1,
    "human_below": 0.4,
    "ai_above": 0.6,
    "uncertain_inclusive": [0.4, 0.6],
    "validated": False,
}


class AudioError(ValueError):
    """An input that cannot be safely or meaningfully analyzed."""

    def __init__(self, message: str, code: str = "invalid_audio") -> None:
        super().__init__(message)
        self.code = code


def _validate_format(sample_rate: int, channels: int) -> None:
    if sample_rate < SAMPLE_RATE or sample_rate > MAX_SAMPLE_RATE:
        raise AudioError(
            "Audio must have a sample rate between 16,000 and 96,000 Hz.",
            "unsupported_audio",
        )
    if not 1 <= channels <= MAX_CHANNELS:
        raise AudioError("Only mono or stereo audio is supported.", "unsupported_audio")


@lru_cache(maxsize=12)
def _resample_filter(sample_rate: int) -> tuple[np.ndarray, int, int, int]:
    """Build the torchaudio-default sinc-Hann filter, as one polyphase FIR.

    The 0.99 rolloff and six-zero-crossing Hann support match the upstream
    torchaudio.transforms.Resample defaults. The phase offset uses float32
    rounding before float64 filter construction, matching that transform.
    """
    divisor = math.gcd(sample_rate, SAMPLE_RATE)
    down, up = sample_rate // divisor, SAMPLE_RATE // divisor
    base = min(down, up) * 0.99
    radius = math.ceil(6 * down * up / base) + 2
    positions = np.arange(-radius, radius + 1, dtype=np.int64)
    phases = (positions * pow(down, -1, up)) % up
    source_offsets = (phases * down - positions) // up
    phase_offsets = (-phases.astype(np.float32) / up).astype(np.float64)
    t = np.clip((source_offsets / down + phase_offsets) * base, -6, 6)
    coefficients = (np.sinc(t) * np.cos(t * np.pi / 12) ** 2 * (base / down)).astype(np.float32)
    # Center on a downsample position so cropping has no fractional delay.
    prefix = (-radius) % down
    coefficients = np.pad(coefficients, (prefix, down))
    remove = (radius + prefix) // down
    return coefficients, up, down, remove


def resample(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Resample [frames, channels] without changing channel order or gain."""
    audio = np.asarray(audio, dtype=np.float32)
    if sample_rate == SAMPLE_RATE:
        return audio
    coefficients, up, down, remove = _resample_filter(sample_rate)
    target_length = math.ceil(len(audio) * up / down)
    result = upfirdn(coefficients, audio, up=up, down=down, axis=0)
    return result[remove : remove + target_length].astype(np.float32, copy=False)


def compute_fakeprint(audio: np.ndarray) -> np.ndarray:
    """Match upstream's 3,585-bin, mean-log-power fakeprint extraction."""
    mono = np.asarray(audio, dtype=np.float32)
    if mono.ndim == 2:
        mono = mono.mean(axis=1, dtype=np.float32)
    if mono.ndim != 1 or len(mono) <= N_FFT // 2:
        raise AudioError("Not enough audio samples for feature extraction.", "audio_too_short")
    if not np.isfinite(mono).all():
        raise AudioError("Audio contains non-finite samples.", "invalid_audio")
    # Reflected centering and a periodic Hann window match torch.stft defaults.
    centered = np.pad(mono, (N_FFT // 2, N_FFT // 2), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(centered, N_FFT)[:: N_FFT // 2]
    window = np.float32(0.5) - np.float32(0.5) * np.cos(
        np.arange(N_FFT, dtype=np.float32) * np.float32(2 * np.pi / N_FFT)
    )
    spectrum = rfft(frames * window, axis=1, workers=1)
    power = (spectrum.real**2 + spectrum.imag**2).astype(np.float32)
    spectrum_db = 10 * np.log10(np.clip(power, 1e-10, 1e6))
    mean_spectrum = spectrum_db.mean(axis=0, dtype=np.float32)
    band = mean_spectrum[512:4097]  # Inclusive 1,000-8,000 Hz at 16 kHz.
    hull = np.maximum(minimum_filter1d(band, size=10, mode="nearest"), -45)
    residue = np.clip(band - hull, 0, 5)
    return (residue / (np.max(residue) + 1e-6)).astype(np.float32)


class AnalysisCancelled(Exception):
    """Cooperative cancellation; raised only after owned decoder processes exit."""


def check_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AnalysisCancelled("Analysis cancelled.")


def validate_window(start_seconds: float, duration_seconds: float) -> None:
    if not math.isfinite(start_seconds) or start_seconds < 0:
        raise AudioError("Start must be a finite non-negative number of seconds.", "invalid_window")
    if not math.isfinite(duration_seconds) or not MIN_DURATION <= duration_seconds <= MAX_DURATION:
        raise AudioError("Duration must be between 10 and 300 seconds.", "invalid_window")


def _run_decoder(command, *, stdout, timeout, cancel_event):
    check_cancelled(cancel_event)
    process = subprocess.Popen(command, stdout=stdout, stderr=subprocess.DEVNULL)
    started = time.monotonic()
    try:
        while True:
            check_cancelled(cancel_event)
            if time.monotonic() - started > timeout:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                output, _ = process.communicate(timeout=0.1)
                return subprocess.CompletedProcess(command, process.returncode, output)
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()


def _ffmpeg_decode(
    path: Path, start_seconds=0.0, duration_seconds=MAX_DURATION, cancel_event=None
) -> tuple[np.ndarray, int, float]:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise AudioError(
            "This audio format requires FFmpeg and ffprobe. Install FFmpeg and retry.",
            "decoder_unavailable",
        )
    try:
        probe = _run_decoder(
            [
                ffprobe,
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-format_whitelist",
                MEDIA_DEMUXERS,
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_rate,channels,duration:format=duration",
                "-of",
                "json",
                str(path),
            ],
            stdout=subprocess.PIPE,
            timeout=10,
            cancel_event=cancel_event,
        )
        if probe.returncode:
            raise AudioError("The file does not contain a readable audio stream.")
        metadata = json.loads(probe.stdout)
        stream = metadata["streams"][0]
        sample_rate, channels = int(stream["sample_rate"]), int(stream["channels"])
        _validate_format(sample_rate, channels)
        duration = float(stream.get("duration", metadata.get("format", {}).get("duration", 0)))
        if not math.isfinite(duration) or duration < 0:
            duration = 0
    except AudioError:
        raise
    except (subprocess.SubprocessError, KeyError, IndexError, ValueError, TypeError):
        raise AudioError("The file does not contain a readable audio stream.") from None

    # Bounded native-rate output in an anonymous file, with a cancellation-aware child.
    seconds = duration_seconds + 1
    byte_limit = int(seconds * sample_rate * channels * 4)
    with tempfile.TemporaryFile() as decoded:
        try:
            result = _run_decoder(
                [
                    ffmpeg,
                    "-nostdin",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file",
                    "-format_whitelist",
                    MEDIA_DEMUXERS,
                    "-threads",
                    "1",
                    "-i",
                    str(path),
                    "-ss",
                    str(start_seconds),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-sn",
                    "-dn",
                    "-t",
                    str(seconds),
                    "-f",
                    "f32le",
                    "-c:a",
                    "pcm_f32le",
                    "-ar",
                    str(sample_rate),
                    "-ac",
                    str(channels),
                    "-fs",
                    str(byte_limit),
                    "pipe:1",
                ],
                stdout=decoded,
                timeout=60,
                cancel_event=cancel_event,
            )
        except subprocess.TimeoutExpired:
            raise AudioError(
                "Audio decoding exceeded the 60-second limit.", "decode_timeout"
            ) from None
        if result.returncode:
            raise AudioError("The audio file could not be decoded.")
        byte_count = decoded.tell()
        if not byte_count:
            raise AudioError("The selected segment contains no audio.", "audio_too_short")
        if byte_count > byte_limit:
            raise AudioError("The audio stream exceeds decoder limits.")
        decoded.seek(0)
        sample_count = byte_count // (4 * channels) * channels
        audio = np.fromfile(decoded, dtype="<f4", count=sample_count).reshape(-1, channels)
    return audio, sample_rate, max(duration, start_seconds + len(audio) / sample_rate)


def load_audio(
    path: Path, start_seconds=0.0, duration_seconds=MAX_DURATION, cancel_event=None
) -> tuple[np.ndarray, int, float]:
    """Decode only a bounded selected window at native sample rate."""
    validate_window(start_seconds, duration_seconds)
    check_cancelled(cancel_event)
    if not path.is_file():
        raise AudioError("Audio file not found.", "file_not_found")
    try:
        with sf.SoundFile(path) as source:
            _validate_format(source.samplerate, source.channels)
            duration = source.frames / source.samplerate
            if start_seconds >= duration:
                raise AudioError("The selected segment starts beyond the audio.", "audio_too_short")
            start_frame = int(start_seconds * source.samplerate)
            source.seek(start_frame)
            remaining = int((duration_seconds + 1) * source.samplerate)
            chunks = []
            while remaining > 0:
                check_cancelled(cancel_event)
                chunk = source.read(
                    frames=min(remaining, source.samplerate), dtype="float32", always_2d=True
                )
                if not len(chunk):
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            audio = np.concatenate(chunks) if chunks else np.empty((0, source.channels), np.float32)
            return audio, source.samplerate, duration
    except AudioError:
        raise
    except (sf.LibsndfileError, RuntimeError):
        return _ffmpeg_decode(path, start_seconds, duration_seconds, cancel_event)


class Detector:
    """One eagerly loaded model session, reusable for multiple local files."""

    def __init__(self) -> None:
        model_path = ASSETS / "ai_music_detector.onnx"
        try:
            digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        except OSError:
            raise RuntimeError(
                "The bundled detector model is missing. Reinstall the package."
            ) from None
        if digest != MODEL_SHA256:
            raise RuntimeError("The bundled detector model failed its checksum verification.")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        try:
            self.session = ort.InferenceSession(
                str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
            )
        except Exception as exc:
            raise RuntimeError("The bundled ONNX model could not be loaded.") from exc
        inputs = self.session.get_inputs()
        if len(inputs) != 1 or inputs[0].shape[1] != 3585:
            raise RuntimeError("The detector model has an unsupported input shape.")
        self.input_name = inputs[0].name
        self.model = {
            "name": "lofcz/ai-music-detector (fakeprint)",
            "version": "1.0.0",
            "sha256": digest,
            "upstream_commit": UPSTREAM_COMMIT,
        }

    def analyze(
        self,
        path: str | Path,
        filename: str | None = None,
        *,
        start_seconds: float = 0,
        duration_seconds: float = MAX_DURATION,
        cancel_event: threading.Event | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> dict:
        started = time.perf_counter()
        path = Path(path).resolve()
        validate_window(start_seconds, duration_seconds)

        def stage(name):
            check_cancelled(cancel_event)
            if progress:
                progress(name)

        if not path.is_file():
            raise AudioError("Audio file not found or not a regular file.", "file_not_found")
        stage("hashing")
        digest = hashlib.sha256()
        try:
            before = path.stat()
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    check_cancelled(cancel_event)
                    digest.update(chunk)
        except OSError:
            raise AudioError("Audio file could not be read.", "file_not_found") from None
        stage("decoding")
        audio, sample_rate, duration = load_audio(
            path, start_seconds, duration_seconds, cancel_event
        )
        stage("preprocessing")
        if len(audio) / sample_rate < MIN_DURATION:
            raise AudioError("At least 10 seconds of audio is required.", "audio_too_short")
        if not np.isfinite(audio).all():
            raise AudioError("Audio contains non-finite samples.")
        converted = resample(audio, sample_rate)[: int(duration_seconds * SAMPLE_RATE)]
        mono = converted.mean(axis=1, dtype=np.float32)
        if float(np.sqrt(np.mean(mono.astype(np.float64) ** 2))) < 1e-5:
            raise AudioError("The audio is silent or too quiet to analyze.", "insufficient_audio")
        features = compute_fakeprint(mono)
        if not np.isfinite(features).all() or np.max(features) < 0.01:
            raise AudioError("The audio has insufficient spectral evidence.", "insufficient_audio")
        stage("inference")
        score = float(self.session.run(None, {self.input_name: features[None, :]})[0][0, 0])
        check_cancelled(cancel_event)
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise RuntimeError("The model returned an invalid score.")
        warnings = [
            "The AI score is an uncalibrated model output, not a verified probability.",
            "This detector targets known Suno/Udio artifacts; other generators and mixed audio are not validated.",
        ]
        if 0.4 <= score <= 0.6:
            assessment = "uncertain"
            warnings.append(
                "The 0.4-0.6 uncertainty band is a product policy, not a validated accuracy threshold."
            )
        else:
            assessment = "likely_ai_generated" if score > 0.6 else "likely_human_created"
        analyzed_duration = len(mono) / SAMPLE_RATE
        analyzed_end = start_seconds + analyzed_duration
        truncated = start_seconds > 0 or duration > analyzed_end + 1 / SAMPLE_RATE
        if truncated:
            if start_seconds == 0 and duration_seconds == MAX_DURATION:
                warnings.append("Only the first 300 seconds of this file were analyzed.")
            else:
                warnings.append(
                    f"Only the selected segment {start_seconds:g}-{analyzed_end:g} seconds was analyzed; "
                    "this is not a whole-song or time-localized authorship verdict."
                )
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ino,
        ):
            raise AudioError(
                "The input changed during analysis. Retry with a stable file.", "input_changed"
            )
        stage("complete")
        return {
            "filename": Path(filename or path.name).name,
            "assessment": assessment,
            "ai_score": score,
            "threshold": 0.5,
            "upstream_binary_threshold": 0.5,
            "decision_policy": dict(DECISION_POLICY),
            "report_id": str(uuid.uuid4()),
            "input_sha256": digest.hexdigest(),
            "input_size_bytes": before.st_size,
            "application_version": __version__,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "analyzed_start_seconds": round(start_seconds, 4),
            "analyzed_end_seconds": round(analyzed_end, 4),
            "requested_duration_seconds": duration_seconds,
            "audio_duration_seconds": round(duration, 4),
            "analyzed_duration_seconds": round(analyzed_duration, 4),
            "truncated": truncated,
            "processing_time_ms": round((time.perf_counter() - started) * 1000, 2),
            "model": dict(self.model),
            "warnings": warnings,
        }
