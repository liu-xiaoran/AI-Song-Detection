# Desktop installer dependencies

Run the root `Install.command` on macOS or `Install.cmd` on Windows after extracting the project. The first installation uses the network; installed desktop entries and the command wrapper run offline.

Supported desktop systems are macOS 13 or later on Apple Silicon/Intel, and Windows 10/11 x64. The macOS audio bundle itself supports macOS 12; the complete application requires macOS 13 because of the ONNX Runtime dependency.

The installers use user-owned directories and do not require Homebrew, Git, an existing Python installation, or administrator access. They do not modify the system PATH or global PowerShell policy. The Windows entry's execution-policy option applies to that installer process only; enterprise policies can still prevent execution.

`dependencies.json` pins uv 0.13.5, the macOS LGPL bundles from `dfloresc/ffmpeg-macos-builds` v9.0.1-1, and the Windows static tools from `eugeneware/ffmpeg-static` b6.1.1. uv checksums were obtained from the official release's `.sha256` files. Audio-tool archive checksums were obtained from GitHub release-asset SHA-256 digests. Assets are verified before extraction or execution.

The macOS bundles contain FFmpeg 9.0.1, are built for macOS 12 or later, and retain their complete `LICENSES/` directory, replaceable shared libraries, `BUILDINFO.txt`, source URLs, and checksums. They depend only on the included libraries and macOS. The Windows bundle contains FFmpeg 6.1.1 with its complete GPL v3 license, source/build README, download manifest, and actual build configuration. Builds declaring `--enable-nonfree` are rejected. These components retain their own licenses.

The macOS build originally considered from eugeneware was rejected after its executable reported `--enable-nonfree`; a release's generic license text is insufficient evidence of its actual build configuration.

Sources:

- uv: https://github.com/astral-sh/uv/releases/tag/0.13.5 (Apache 2.0 or MIT).
- macOS FFmpeg libraries, notices, source tarballs, and build scripts: https://github.com/dfloresc/ffmpeg-macos-builds/releases/tag/v9.0.1-1.
- Windows FFmpeg binaries and notices: https://github.com/eugeneware/ffmpeg-static/releases/tag/b6.1.1.
- Windows source and build provenance: the installed platform README and https://github.com/eugeneware/ffmpeg-static/tree/b6.1.1.
- FFmpeg licensing: https://ffmpeg.org/legal.html.

No third-party binaries are committed to this repository. The installer downloads them from the pinned upstream release to the user's machine. Anyone redistributing installed binaries must retain their notices and satisfy the applicable source-distribution obligations.

Unsigned downloaded scripts may trigger macOS Gatekeeper or Windows SmartScreen. The installer does not disable either protection. Signed and notarized consumer installers are a separate distribution step.

For isolated verification, set `AI_SONG_DETECTION_INSTALL_DIR` and `AI_SONG_DETECTION_DESKTOP_DIR` before invoking the installer. Applications are copied into versioned directories so the extracted source folder is no longer needed after installation. Failed installs leave the previous current version and desktop entries intact.
