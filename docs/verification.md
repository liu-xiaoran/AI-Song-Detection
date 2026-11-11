# Version 0.3.0 verification

Date: 2026-11-11. Local platform: macOS ARM64, Python 3.12, CPU inference.

## Source and browser checks

- `uv run pytest -q`: **169 passed, 2 skipped**. The skipped tests require native Windows PowerShell/.NET; they are exercised on Windows CI. One upstream Starlette deprecation warning remains.
- `node --test tests/browser/connection.test.cjs`: **11 passed**.
- Ruff lint and formatting checks pass. Version 0.3.0 source distribution and wheel build successfully.

The functional suite covers bounded FIFO jobs and actual cancellation lifetime, upload validation and cleanup, window selection, content/report provenance, batch CLI exports, labeled-manifest evaluation math, strict-port behavior, maintenance ownership boundaries, cross-platform raw update-archive validation, Windows worker startup/error reporting, and offline-bundle integrity/relocation contracts. Browser logic tests cover serial queues, upload progress, cancellation, accepted-job polling recovery, failure retry, history, and JSON/CSV exports.

A real local browser run verified two valid synthetic-audio jobs and one corrupt-audio failure, retained history, a selected 1–11-second interval, JSON/CSV downloads, 1440px/390px layouts without horizontal overflow, no JavaScript errors, and no external browser resource requests.

## Installed Mac and offline package

The user's Mac installation has been updated to version 0.3.0 using the source payload from code commit `18d166263db77148da38238b597cf811410a550e`. Its installed payload SHA-256 is `e7ad6a5deb93b5fe3146644a3073647d2e1b958e3187e14765e33e1cbf160e70`, matching `installer.payload_digest` for that checkout. The desktop start/stop entries bind to this per-user installation. Final health and doctor checks confirmed the model and private FFmpeg/ffprobe were ready, with the managed service at `http://127.0.0.1:8002` at verification time.

Local native installation, source-folder removal, desktop lifecycle, occupied-port fallback, offline relaunch, relocated offline restore, restored inference, and scoped uninstall checks passed during 0.3.0 verification. A read-only check of the user's default-browser tab visibly confirmed the new queue and window controls with `Detector ready`. The previous interactive Finder double-click/default-browser check is recorded under the historical 0.2.0 evidence below; it was not repeated for every maintenance-only revision.

The final macOS ARM64 offline folder was regenerated from the installed payload and verified against its complete manifest. The ZIP archive was checked for CRC errors, the embedded source digest, and executable restore-entry permissions:

- File: `AI-Song-Detection-0.3.0-macos-arm64-offline.zip`
- Size: 282,380,089 bytes
- SHA-256: `bc3331f89132d487c2af7314807d441d45c44c1c7067f71c3eadd1fb9145554e`

It contains private Python/uv, decoder assets, dependencies, and the model/source for macOS ARM64; it is platform-specific. Checksums detect corruption and do not establish a publisher signature. The archive and ignored machine evidence are local deliverables, not committed Git files. Evidence is retained under `.runtime/verification/dev-v030/`, `.runtime/verification/native-v030/`, and `.runtime/verification/user-v030/`.

## Native CI and Windows removal

All six jobs in the [0.3.0 CI run 43046650583](https://github.com/liu-xiaoran/AI-Song-Detection/actions/runs/43046650583) passed for code commit `18d166263db77148da38238b597cf811410a550e`. Linux Python 3.11/3.12/3.13 jobs run lint, format, Python/Node tests, and package builds. Native jobs cover macOS ARM64, macOS Intel, and Windows x64 with private installation, source removal, desktop start/reuse/stop, occupied-port fallback, real model HTTP/CLI inference, browser upload/layout, diagnostics/previews, offline relaunch, relocated offline-bundle restore, and scoped uninstall.

Windows Server 2025 completed **165 Python tests, with 6 platform-specific skips**, the 11 browser logic tests, and all 18 native smoke checks. The installed ONNX/C++ runtime modules were confirmed to load from private installation paths. Both named Windows remover tests passed, covering 1,025 files with read-only content and an external directory junction, and a mismatched ownership nonce that must preserve files and report failure.

The restored disposable Windows installation's deferred uninstall completed in 2.446 seconds. The helper reported 15,026 files and 1,565 directories removed, no remaining owned paths, no error, and no retry errors. Only `unrelated.txt` remained at the installation root. The evidence and final result are retained under `.runtime/verification/windows-v030/` and in the run's `desktop-windows-2025` artifact. This confirms actual cleanup after CLI exit, not only a successful scheduling response.

Windows validation used a hosted Server 2025 runner; physical Windows 10/11 desktops were not separately tested. Visible default-browser opening was directly observed on the user's Mac, while CI independently checks the requested browser opening and renders the interface with Chromium.

The previous release verification is retained as historical evidence and does not by itself verify version 0.3.0.

---

# Verification Record

Application version: 0.2.0. Date: 2026-11-11. Local platform: macOS ARM64, Python 3.12, CPU inference.

## Local source and package checks

- The latest completed full `uv run pytest -q` execution passed 81 tests. Coverage includes the real bundled model, audio validation, duration capping, FFmpeg fallback, numerical preprocessing references, upload limits, temporary-file cleanup, API contracts, concurrent-request rejection, managed-service identity and lifecycle, real redirector/worker PID handoff and cleanup, installer integrity, private Windows runtime preparation/repair, and failed-upgrade behavior. This includes the Windows CRLF regression check within the 16-test installer suite. One upstream Starlette deprecation warning is reported.
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

The pinned Intel macOS FFmpeg/ffprobe bundle was separately executed using the host's already-installed Rosetta. Its checksum, embedded LGPL configuration, macOS 12 deployment target, bundled-library linkage, signatures, and real MP3/AAC/WAV encoding/probing passed the upstream bundle checks. Full native Intel macOS desktop installation, browser upload/layout, offline relaunch/inference, lifecycle, and unit checks also passed in GitHub Actions. The application itself requires macOS 13 or newer because of ONNX Runtime.

## Platform and CI status

The complete [GitHub Actions run 43013384907](https://github.com/liu-xiaoran/AI-Song-Detection/actions/runs/43013384907) passed for code commit `47255c57a73ca5f38332c96d8cff01d877aaffe6`. All six jobs completed successfully:

| Target | Verified behavior |
| --- | --- |
| macOS ARM64, macOS 26 runner | Fresh private installation, source removal, desktop commands, port fallback, repeated launch, real HTTP/CLI inference, browser upload/layout, offline relaunch, stop, and Python/Node tests. Local Finder/default-browser interaction also passed as described above. |
| macOS Intel, macOS 15 runner | The same complete native installation, lifecycle, inference, browser, offline, and test checks. |
| Windows x64, Windows Server 2025 runner | Native `Install.cmd`, Unicode `.lnk` shortcuts invoked through ShellExecute, private Python/audio tools, worker/redirector lifecycle, repeated launch, actual HTTP/CLI inference, browser upload/layout, offline relaunch, stop, and Python/Node tests. |
| Linux, Python 3.11 / 3.12 / 3.13 | Lint, format, Python/Node tests, and distribution builds on all three versions. |

Windows module enumeration after actual inference confirmed that `MSVCP140.dll` and `MSVCP140_1.dll` loaded from the release's private runtime directory, `VCRUNTIME140.dll` and `VCRUNTIME140_1.dll` loaded from the private CPython directory, and ONNX Runtime loaded from the private environment. No host DLLs were replaced or unloaded. This distinguishes private runtime use from merely succeeding on a hosted runner with preinstalled system libraries.

The [CI workflow](../.github/workflows/ci.yml) retains native reports, logs, shortcut metadata, and screenshots as `desktop-macos-26`, `desktop-macos-15-intel`, and `desktop-windows-2025` artifacts. The native smoke checks in all three reports passed and left their verifier-managed services stopped. Reports downloaded during this verification are retained under the ignored `.runtime/verification/` directory.

The Windows native runner uses Server 2025; physical Windows 10/11 desktop machines were not separately exercised. The Windows shortcut requests the system default browser, while Playwright independently verifies the rendered interface in Chromium. Visible default-browser opening was directly observed on the user's Mac. Signed-installer warnings and organization-specific execution policies remain outside the automated checks.

Later documentation-only edits record these results without changing the verified runtime code.

## Container checks

Compose configuration validation passes. Docker image build attempts encountered registry timeouts while fetching base-image metadata. Desktop installation and runtime checks use the native application paths described above.
