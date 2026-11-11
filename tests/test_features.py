"""Numerical parity against stored PyTorch/torchaudio upstream references."""

from pathlib import Path

import numpy as np
import pytest

from ai_song_detection.detector import compute_fakeprint, resample


def reference_audio(sample_rate: int) -> np.ndarray:
    rng = np.random.default_rng(8871 + sample_rate)
    audio = rng.normal(0, 0.08, (int(sample_rate * 11.13), 2)).astype(np.float32)
    time = np.arange(len(audio)) / sample_rate
    audio[:, 0] += (0.15 * np.sin(2 * np.pi * 440 * time)).astype(np.float32)
    audio[:, 1] += (0.08 * np.sin(2 * np.pi * 880 * time)).astype(np.float32)
    return audio


@pytest.mark.parametrize("sample_rate", [16000, 44100, 48000])
def test_features_match_upstream_torchaudio_reference(sample_rate):
    fixture = Path(__file__).parent / "fixtures" / "upstream_reference.npz"
    with np.load(fixture, allow_pickle=False) as reference:
        audio = resample(reference_audio(sample_rate), sample_rate)
        mono = audio.mean(axis=1)
        np.testing.assert_allclose(
            mono[:200], reference[f"audio_head_{sample_rate}"], atol=8e-8, rtol=3e-6
        )
        np.testing.assert_allclose(
            compute_fakeprint(mono), reference[f"features_{sample_rate}"], atol=2e-4, rtol=3e-5
        )


@pytest.mark.parametrize("sample_rate", [16000, 22050, 32000, 44100, 48000, 88200, 96000])
def test_resampling_preserves_channel_order_length_and_dc_gain(sample_rate):
    audio = np.empty((sample_rate, 2), dtype=np.float32)
    audio[:, 0], audio[:, 1] = 0.25, -0.5
    output = resample(audio, sample_rate)
    assert output.shape == (16000, 2)
    np.testing.assert_allclose(output[100:-100, 0], 0.25, atol=3e-4)
    np.testing.assert_allclose(output[100:-100, 1], -0.5, atol=6e-4)


def test_resampling_unusual_rate_is_bounded_and_has_correct_length():
    # A coprime rate must not allocate a dense 16,000 x 44,117 kernel bank.
    audio = np.ones((44117, 1), dtype=np.float32)
    output = resample(audio, 44117)
    assert output.shape == (16000, 1)
    assert np.isfinite(output).all()


def test_invalid_nonfinite_features_are_rejected():
    from ai_song_detection.detector import AudioError

    audio = np.full(16000, np.nan, dtype=np.float32)
    with pytest.raises(AudioError, match="non-finite"):
        compute_fakeprint(audio)
