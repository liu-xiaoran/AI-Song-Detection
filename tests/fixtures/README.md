# Upstream numerical reference

`upstream_reference.npz` contains full 3,585-element fakeprints and the first
200 mono resampled samples computed with PyTorch 2.8.0 and torchaudio 2.8.0,
using the Python preprocessing from upstream commit
`6ba389e94a179ac90f3eb134b741ef37baa30434`.

The input for each sample rate is reproduced by `reference_audio` in
`tests/test_features.py`: 11.13 seconds of seeded stereo Gaussian noise mixed
with 440 Hz and 880 Hz sine waves. The fixture contains no music or private data.

Reference operations: `torchaudio.transforms.Resample(rate, 16000)`, stereo
mean, `torchaudio.transforms.Spectrogram(n_fft=8192, power=2, normalized=False)`,
power clamping to `[1e-10, 1e6]`, `10 * log10`, mean over frames, bins
`512:4097`, nearest-mode minimum filter of size 10, hull floor -45 dB,
residue clipping to `[0, 5]`, and division by `max(residue) + 1e-6`.

Stored scores are model outputs for these synthetic inputs. Production tests
do not depend on PyTorch.

Sample comparisons allow absolute error `8e-8`; fakeprint comparisons allow
`2e-4` on the normalized `[0, 1]` feature range. Different FFT and floating-point
reduction implementations can amplify tiny sample differences in log-power
bins with very low energy. These checks compare numerical preprocessing
results with the upstream reference.
