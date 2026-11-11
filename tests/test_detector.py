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
