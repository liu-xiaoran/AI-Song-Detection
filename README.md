# AI Song Detection

Fast, low-cost detection of AI-generated music.

AI Song Detection aims to help users assess whether a song contains AI-generated audio. The project targets **99% song-level accuracy**, with an emphasis on short analysis times and low cost per song.

**Status:** Project initialization. This repository currently contains project documentation and repository configuration. A detector, trained model, API, and benchmark results are not yet available. The 99% figure is a target, not a measured result or a guarantee for individual songs.

## Product goals

- **Accurate:** Target 99% accuracy on a documented, representative, held-out evaluation set, while reporting false positives and false negatives separately.
- **Fast:** Minimize the time from submitting an audio file to receiving a result, and measure end-to-end latency.
- **Low cost:** Minimize compute and service cost per analyzed song, and publish the assumptions behind cost measurements.
- **Clear results:** Return an assessment of AI-generated audio with an explicit uncertain outcome when the evidence is insufficient.

## Intended workflow

1. Submit a song as an audio file.
2. Validate the file and prepare audio segments for analysis.
3. Analyze the audio using a detection model.
4. Aggregate segment-level evidence into a song-level assessment.
5. Return the assessment with the model version and relevant limitations.

This is the planned workflow. No upload interface or detection command is implemented yet.

## Detection scope

The initial focus is fully AI-generated songs versus human-created recordings. Songs with generated vocals, generated accompaniment, or other mixed production require separate labels and evaluation. Ordinary editing, mastering, pitch correction, or use of digital instruments alone does not establish that a song is AI-generated.

Detection assesses audio evidence. It cannot establish authorship, ownership, or the exact production history of a recording.

## Documentation

- [Product scope](docs/product-scope.md): Intended behavior, output requirements, and open decisions.
- [Evaluation plan](docs/evaluation.md): How to assess accuracy, speed, cost, and generalization.

## Repository layout

```text
.
├── README.md
├── LICENSE
└── docs/
    ├── product-scope.md
    └── evaluation.md
```

## Development starting point

The next implementation step is to select a baseline detector and assemble an authorized, labeled evaluation dataset. Measure baseline quality, latency, and cost before choosing the serving architecture or making performance claims. Runtime dependencies and setup instructions will be added with the first executable implementation.

Keep project documentation, code identifiers, comments, and user-facing text in English. Do not commit credentials, private audio, datasets, or model weights to Git.

## License

This project is licensed under the [Apache License 2.0](LICENSE). Third-party models, datasets, and dependencies retain their own licenses.
