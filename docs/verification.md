# Verification Record

Application version: 0.2.0. Date: 2026-11-11. Local platform: macOS ARM64, Python 3.12, CPU inference.

## Local source and package checks

- The latest completed full `uv run pytest -q` execution passed 76 tests. Coverage includes the real bundled model, audio validation, duration capping, FFmpeg fallback, numerical preprocessing references, upload limits, temporary-file cleanup, API contracts, concurrent-request rejection, managed-service identity and lifecycle, installer integrity, private Windows runtime preparation/repair, and failed-upgrade behavior. This includes the Windows CRLF regression check within the 16-test installer suite. One upstream Starlette deprecation warning is reported.
- `node --test tests/browser/connection.test.cjs`: four tests pass, covering readiness requirements, single in-flight health checks, disconnect/retry behavior, file preservation, and upload gating.
- Ruff lint and formatting checks pass. JavaScript and macOS shell syntax checks pass.
- Version 0.2.0 source distribution and wheel build successfully. The wheel contains the bundled model, provenance, licenses, and static interface assets. The model bytes match the pinned upstream SHA-256.
- Synthetic preprocessing references compare against PyTorch/torchaudio 2.8; see [fixture provenance](../tests/fixtures/README.md). Earlier isolated wheel installation checks also exercised local CLI inference.

## Native installation and browser evidence

The local macOS ARM64 smoke run completed at 11:05:53 UTC. Its machine-readable report and browser screenshots are retained under `.runtime/verification/macos-local/` in the verification checkout; this ignored directory is not part of the distributed source.

The [native smoke script](../scripts/desktop_smoke.py) copies a release payload to paths containing spaces and Chinese characters, removes developer-tool access from PATH, invokes the root installer, and checks the installed copy after deleting the extracted source folder. This run passed all recorded checks:

- The bootstrap prepared private uv/Python and the pinned ARM64 LGPL FFmpeg bundle without using host Python, Git, or audio tools.
- Generated desktop start/stop commands and the installed command wrapper controlled the same identity-verified service. Repeated starts reused its PID; an occupied port 8000 caused selection of another local port.
- HTTP and CLI used the real bundled model on a 12-second synthetic WAV. Corrupt audio returned an explicit error.
- Playwright uploaded the synthetic file and rendered its result. Desktop width 1440 and mobile width 390 had no horizontal overflow, no browser JavaScript errors, and no external resource requests. The local API reference loaded successfully.
- A stopped service relaunched and performed inference with `UV_OFFLINE=1` and deliberately failing HTTP/HTTPS/ALL proxy settings. This checks the installed path without changing the host firewall or claiming a physical network-disconnection test.
- The desktop stop entry and command stopped the verifier's service; the final report confirms no verifier-managed service remained running.

The automated macOS smoke invokes the generated `.command` files through `/bin/sh` with `--no-browser`. A separate interactive check on the user's Mac double-clicked the installed desktop start entry in Finder: the system's default browser, Microsoft Edge, opened `http://127.0.0.1:8001` and displayed `Detector ready`. Double-clicking the desktop stop entry changed the existing page to `Connection unavailable`. Double-clicking start again opened port 8002 and restored `Detector ready`. These port values are observations from that machine, not fixed installation addresses. Downloaded-file quarantine and security prompts remain dependent on download method and system policy. Unit tests also establish that the browser-open request occurs only after readiness and when an existing instance is reused.

Additional local browser checks cover width 320, connection loss/retry, a preserved file after reconnecting, blocked submission while busy or unavailable, simulated network failure, invalid and short audio, result changes, and uncertainty rendering. These include simulated failures as well as real synthetic-audio inference; they are not all native installer tests.

The pinned Intel macOS FFmpeg/ffprobe bundle was separately executed using the host's already-installed Rosetta. Its checksum, embedded LGPL configuration, macOS 12 deployment target, bundled-library linkage, signatures, and real MP3/AAC/WAV encoding/probing passed the upstream bundle checks. In addition, the full native Intel macOS desktop job passed in [GitHub Actions run 43009706785](https://github.com/liu-xiaoran/AI-Song-Detection/actions/runs/43009706785) at commit `5d3073c`, including installation, browser upload/layout, offline relaunch/inference, lifecycle, and unit checks. The application itself requires macOS 13 or newer because of ONNX Runtime.

## Platform and CI status

| Target | Evidence at this record |
| --- | --- |
| macOS ARM64 | Local isolated installation, launch/status/stop, real inference, automated browser checks, and interactive Finder/default-browser start/stop/restart passed as described above. |
| macOS Intel | Complete native desktop CI job passed at `5d3073c`; the current revision's consolidated CI rerun is pending. |
| Windows 10/11 x64 | Installer implementation and platform-independent tests present; native installation, shortcuts, private runtime, and browser run pending. |
| Remote CI | Native Intel job passed in the linked run; final results covering the subsequent Windows fixes are pending. |

The [CI workflow](../.github/workflows/ci.yml) defines Linux tests for Python 3.11, 3.12, and 3.13, plus native installer/browser jobs on `macos-26`, `macos-15-intel`, and `windows-2025`. Desktop jobs retain reports and screenshots as artifacts. The linked Intel success applies to its recorded commit; workflow definitions and local tests do not establish success for another platform or later commit.

## Accuracy, performance, and container boundaries

The audio used for functional and numerical checks is synthetic. These checks do not measure accuracy on real music, reproduce upstream's 99.88% result, establish a 99% guarantee, or benchmark production latency and cost. The uncertainty band is an unvalidated product policy. Use the [evaluation plan](evaluation.md) for an independent quality assessment.

Compose configuration validation passes. Docker image builds were previously attempted but could not fetch base-image metadata because the registry requests timed out. Container startup and container inference remain unverified; local desktop verification is independent of Docker.
