# Third-Party Notices

## AI Music Detector

This project includes the original fakeprint ONNX model and adapts its inference method from [lofcz/ai-music-detector](https://github.com/lofcz/ai-music-detector), revision `6ba389e94a179ac90f3eb134b741ef37baa30434`.

- Copyright (c) 2026 Matěj Štágl.
- License: MIT. The complete notice is retained in [third_party/ai-music-detector/LICENSE](third_party/ai-music-detector/LICENSE) and distributed with the package assets.
- The [model card](https://huggingface.co/lofcz/ai-music-detector) separately declares the model license as MIT.
- The bundled model is unchanged. The web interface, HTTP service, CLI, input handling, NumPy/SciPy inference implementation, and uncertainty policy are adaptations for this project.
- Model SHA-256: `af7a75c6ed457bc5b6941c8bc76aa06a66d48de40db944b761ed2bebfc0fbbd3`.

[Upstream reports 99.88% accuracy](https://github.com/lofcz/ai-music-detector/tree/6ba389e94a179ac90f3eb134b741ef37baa30434#performance) on its held-out set of 17,866 samples, targeting Suno <= 5 and Udio <= 1.5. Upstream training includes proprietary recordings; those recordings and the FMA/SONICS datasets are not included here.

## Desktop runtime and installer tools

Third-party desktop binaries are downloaded during installation rather than committed to this repository. The pinned download URLs and SHA-256 values are recorded in [install/dependencies.json](install/dependencies.json); [installer dependency provenance](install/README.md) describes their origin and installation behavior.

- **uv 0.13.5:** from [astral-sh/uv](https://github.com/astral-sh/uv/releases/tag/0.13.5), licensed under Apache 2.0 or MIT. Original [Apache 2.0](install/licenses/uv-LICENSE-APACHE) and [MIT](install/licenses/uv-LICENSE-MIT) notices are included in the source payload and copied beside the private uv executable by both bootstrap scripts.
- **Managed CPython 3.12:** installed by uv into the application's private runtime directory. uv obtains managed Python builds from [astral-sh/python-build-standalone](https://github.com/astral-sh/python-build-standalone); see [uv's Python distribution documentation](https://docs.astral.sh/uv/concepts/python-versions/#managed-and-system-python-installations). CPython uses the [Python Software Foundation License and included notices](https://docs.python.org/3.12/license.html). The installed Python distribution retains its own license files and additional component notices. The installer selects the 3.12 series; it does not pin a specific CPython patch release.
- **Windows Microsoft Visual C++ CRT 14.44.35211:** downloaded from Microsoft's fixed Visual Studio 2022 package URL recorded in the dependency manifest. These proprietary Microsoft components are governed by the [Microsoft Visual C++ Runtime license terms](https://visualstudio.microsoft.com/license-terms/vs2022-cruntime/), with the redistributable file list documented [by Microsoft](https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution#visual-c-runtime-files). They are not covered by the upstream detector's MIT license or this application's Apache 2.0 license. Installation extracts only the ten unmodified x64 release CRT DLLs selected by the manifest; the package and each DLL are checksum-verified. The original [Microsoft runtime license document](install/licenses/Microsoft-Visual-C-Runtime-LICENSE.docx) and download metadata are retained with the DLLs under each private environment's `Lib/site-packages/ai_song_detection_vc_runtime/` directory.
- **macOS FFmpeg and ffprobe 9.0.1:** LGPL variant from [dfloresc/ffmpeg-macos-builds v9.0.1-1](https://github.com/dfloresc/ffmpeg-macos-builds/releases/tag/v9.0.1-1), built from revision `e95a80ee4eeaf8bdb4f208ccbc1952eb79e0b08a`. FFmpeg is LGPL 2.1 or later; included codec libraries retain their respective LGPL or BSD notices. Installation retains the complete `LICENSES/` directory, separate replaceable shared libraries, `BUILDINFO.txt`, source URLs/checksums, and an installation manifest. The corresponding component source tarballs and build scripts are available at that release. This software is based in part on the work of the Independent JPEG Group.
- **Windows FFmpeg and ffprobe 6.1.1:** static builds from [eugeneware/ffmpeg-static b6.1.1](https://github.com/eugeneware/ffmpeg-static/releases/tag/b6.1.1), distributed under their included GPL v3 license. Installation retains the platform `LICENSE`, source/build `README`, actual executable configuration in `BUILD-CONFIGURATION.txt`, and source/download information in `DOWNLOADS.json`. Consult those exact installed notices and their corresponding source references when redistributing the binaries.

The installer rejects FFmpeg builds declaring `--enable-nonfree`; the macOS LGPL bundle must also be built without `--enable-gpl`. A generic license attached to a release does not override an executable's actual build configuration. See [FFmpeg licensing](https://ffmpeg.org/legal.html) for the applicable requirements. Keep third-party notices and corresponding-source obligations when distributing installed runtimes; the project's Apache 2.0 license does not replace them.

## Other dependencies

Python application dependencies retain their respective licenses and packaged notices. Development tools are not required by the installed application. Development-checkout FFmpeg and container FFmpeg are installed separately or by the operating-system package manager; their applicable licenses depend on those distributions' build configurations.
