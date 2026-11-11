# Verification Record

Date: 2026-11-11. Local platform: macOS ARM64, Python 3.12, CPU inference.

## Verified

- The 34 automated tests pass, covering the real bundled model, audio validation, duration capping, FFmpeg fallback, numerical preprocessing references, upload limits, temporary-file cleanup, API contracts, and concurrent-request rejection.
- Ruff lint and formatting checks pass. JavaScript and shell syntax checks pass.
- Source distribution and wheel build successfully. A wheel installed into a separate environment performs local CLI inference with the packaged model and license files.
- The running HTTP service returns a healthy status and performs inference through both the main upload page and the offline API console.
- Browser checks cover desktop, 390-pixel, and 320-pixel layouts, real synthetic-audio uploads, invalid and short audio, result changes, and uncertainty rendering. No horizontal overflow or JavaScript/CSP errors were observed.
- The main interface and API reference load their assets locally.
- Model bytes match the pinned upstream SHA-256. Synthetic preprocessing references compare against PyTorch/torchaudio 2.8; see [fixture provenance](../tests/fixtures/README.md).

## Boundaries

The audio used for functional and numerical checks is synthetic. These checks do not measure accuracy on real music, reproduce upstream's 99.88% result, establish a 99% guarantee, or benchmark production latency and cost. The uncertainty band is an unvalidated product policy.

Compose configuration validation passes. Docker image builds were attempted but could not fetch base-image metadata because the registry requests timed out. Container startup and container inference have not been verified. The local Python installation and service were verified independently of Docker.

CI is configured for Python 3.11, 3.12, and 3.13 on Linux. A workflow definition alone does not establish that those remote jobs have passed.
