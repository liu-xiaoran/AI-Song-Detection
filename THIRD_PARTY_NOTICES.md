# Third-Party Notices

## AI Music Detector

This project includes the original fakeprint ONNX model and adapts its inference method from [lofcz/ai-music-detector](https://github.com/lofcz/ai-music-detector), revision `6ba389e94a179ac90f3eb134b741ef37baa30434`.

- Copyright (c) 2026 Matěj Štágl.
- License: MIT. The complete notice is retained in [third_party/ai-music-detector/LICENSE](third_party/ai-music-detector/LICENSE) and distributed with the package assets.
- The [model card](https://huggingface.co/lofcz/ai-music-detector) separately declares the model license as MIT.
- The bundled model is unchanged. The web interface, HTTP service, CLI, input handling, NumPy/SciPy inference implementation, and uncertainty policy are adaptations for this project.
- Model SHA-256: `af7a75c6ed457bc5b6941c8bc76aa06a66d48de40db944b761ed2bebfc0fbbd3`.

Upstream reports 99.88% accuracy on its own held-out set of 17,866 samples, targeting Suno <= 5 and Udio <= 1.5. This result has not been independently reproduced by this project. Upstream training includes proprietary recordings; those recordings and the FMA/SONICS datasets are not included here.

## Dependencies

Runtime dependencies retain their respective licenses. FFmpeg is installed separately or by the container's operating-system package manager; its applicable license depends on its build configuration. Consult the installed distribution's notices when redistributing binaries. The project's Apache 2.0 license does not replace third-party licenses.
