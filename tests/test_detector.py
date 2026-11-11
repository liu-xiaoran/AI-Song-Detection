import hashlib
import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from ai_song_detection.detector import ASSETS, MODEL_SHA256, AudioError, Detector


@pytest.fixture(scope="module")
def detector():
    return Detector()


def write_audio(tmp_path, seconds=11, sample_rate=16000, channels=1):
    audio = (
        np.random.default_rng(120)
        .normal(0, 0.08, (int(seconds * sample_rate), channels))
        .astype(np.float32)
    )
    path = tmp_path / "test.wav"
    sf.write(path, audio, sample_rate, subtype="FLOAT")
    return path


def test_bundled_model_matches_upstream_checksum():
    assert (
        hashlib.sha256((ASSETS / "ai_music_detector.onnx").read_bytes()).hexdigest() == MODEL_SHA256
    )


def test_real_model_inference_returns_versioned_finite_score(tmp_path, detector):
    result = detector.analyze(write_audio(tmp_path), filename="test.wav")
    assert result["filename"] == "test.wav"
    assert 0 <= result["ai_score"] <= 1
    assert result["assessment"] in {"likely_ai_generated", "likely_human_created", "uncertain"}
    assert result["audio_duration_seconds"] == 11
    assert result["analyzed_duration_seconds"] == 11
    assert result["truncated"] is False
    assert result["model"]["sha256"] == MODEL_SHA256
    assert result["processing_time_ms"] > 0
    assert "uncalibrated" in result["warnings"][0]


def test_long_file_is_capped_and_disclosed(tmp_path, detector):
    result = detector.analyze(write_audio(tmp_path, seconds=301))
    assert result["audio_duration_seconds"] == 301
    assert result["analyzed_duration_seconds"] == 300
    assert result["truncated"] is True
    assert any("first 300 seconds" in item for item in result["warnings"])


def test_short_audio_is_rejected(tmp_path, detector):
    with pytest.raises(AudioError) as error:
        detector.analyze(write_audio(tmp_path, seconds=9.9))
    assert error.value.code == "audio_too_short"


def test_silence_is_rejected(tmp_path, detector):
    path = tmp_path / "silence.wav"
    sf.write(path, np.zeros(16000 * 10, dtype=np.float32), 16000)
    with pytest.raises(AudioError) as error:
        detector.analyze(path)
    assert error.value.code == "insufficient_audio"


@pytest.mark.parametrize("rate,channels", [(8000, 1), (192000, 1), (16000, 3)])
def test_unsupported_audio_properties_are_rejected(tmp_path, detector, rate, channels):
    with pytest.raises(AudioError) as error:
        detector.analyze(write_audio(tmp_path, seconds=0.1, sample_rate=rate, channels=channels))
    assert error.value.code == "unsupported_audio"


def test_nonfinite_pcm_is_rejected(tmp_path, detector):
    path = tmp_path / "nan.wav"
    sf.write(path, np.full(16000 * 10, np.nan, dtype=np.float32), 16000, subtype="FLOAT")
    with pytest.raises(AudioError, match="non-finite"):
        detector.analyze(path)


def test_missing_and_malformed_files_fail_explicitly(tmp_path, detector):
    with pytest.raises(AudioError) as error:
        detector.analyze(tmp_path / "missing.wav")
    assert error.value.code == "file_not_found"
    path = tmp_path / "broken.mp3"
    path.write_text("This is not audio.")
    with pytest.raises(AudioError):
        detector.analyze(path)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_compressed_audio_fallback_runs_real_inference(tmp_path, detector):
    source = write_audio(tmp_path, sample_rate=44100, channels=2)
    compressed = tmp_path / "test.m4a"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-c:a", "aac", str(compressed)],
        check=True,
        timeout=20,
    )
    result = detector.analyze(compressed)
    assert 0 <= result["ai_score"] <= 1
    assert 10 <= result["analyzed_duration_seconds"] <= 12


def test_uncertainty_band_is_explicit(tmp_path):
    class FixedSession:
        def run(self, *_):
            return [np.array([[0.5]], dtype=np.float32)]

    detector = Detector()
    detector.session = FixedSession()
    result = detector.analyze(write_audio(tmp_path))
    assert result["assessment"] == "uncertain"
    assert any("product policy" in item for item in result["warnings"])


def test_selected_window_reports_content_and_coverage(tmp_path, detector):
    path = write_audio(tmp_path, seconds=25)
    stages = []
    result = detector.analyze(path, start_seconds=5, duration_seconds=10, progress=stages.append)
    assert result["analyzed_start_seconds"] == 5
    assert result["analyzed_end_seconds"] == 15
    assert result["analyzed_duration_seconds"] == 10
    assert result["audio_duration_seconds"] == 25
    assert result["truncated"]
    assert result["input_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result["input_size_bytes"] == path.stat().st_size
    assert result["report_id"] and result["analyzed_at"] and result["application_version"]
    assert result["decision_policy"]["uncertain_inclusive"] == [0.4, 0.6]
    assert result["decision_policy"]["validated"] is False
    assert stages == ["hashing", "decoding", "preprocessing", "inference", "complete"]


@pytest.mark.parametrize("start,duration", [(-1, 10), (float("nan"), 10), (0, 9), (0, 301)])
def test_invalid_windows_rejected(tmp_path, detector, start, duration):
    with pytest.raises(AudioError) as error:
        detector.analyze(tmp_path / "unused.wav", start_seconds=start, duration_seconds=duration)
    assert error.value.code == "invalid_window"


def test_segment_near_end_requires_ten_seconds(tmp_path, detector):
    with pytest.raises(AudioError) as error:
        detector.analyze(write_audio(tmp_path, seconds=20), start_seconds=15, duration_seconds=10)
    assert error.value.code == "audio_too_short"


def test_cancellation_before_and_during_analysis(tmp_path, detector):
    import threading

    from ai_song_detection.detector import AnalysisCancelled

    path = write_audio(tmp_path)
    event = threading.Event()
    event.set()
    with pytest.raises(AnalysisCancelled):
        detector.analyze(path, cancel_event=event)
    event.clear()
    with pytest.raises(AnalysisCancelled):
        detector.analyze(
            path,
            cancel_event=event,
            progress=lambda stage: event.set() if stage == "preprocessing" else None,
        )


def test_cancelled_decoder_process_is_reaped():
    import sys
    import threading
    import time

    from ai_song_detection.detector import AnalysisCancelled, _run_decoder

    event = threading.Event()
    timer = threading.Timer(0.15, event.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(AnalysisCancelled):
            _run_decoder(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                stdout=subprocess.PIPE,
                timeout=60,
                cancel_event=event,
            )
        assert time.monotonic() - started < 4
    finally:
        timer.cancel()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg is not installed")
def test_compressed_selected_window(tmp_path, detector):
    source = write_audio(tmp_path, seconds=25, sample_rate=44100, channels=2)
    compressed = tmp_path / "selected.m4a"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-c:a", "aac", str(compressed)],
        check=True,
        timeout=20,
    )
    result = detector.analyze(compressed, start_seconds=5, duration_seconds=10)
    assert result["analyzed_duration_seconds"] == 10
    assert result["analyzed_start_seconds"] == 5
    assert result["analyzed_end_seconds"] == 15
    assert 25 <= result["audio_duration_seconds"] < 26
