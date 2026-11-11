# Evaluation Plan

## Model and coverage

The application runs inference using the bundled upstream fakeprint model. This plan describes how to evaluate song-level results, processing speed, and cost on a labeled collection of recordings.

[Upstream's pinned README](https://github.com/lofcz/ai-music-detector/tree/6ba389e94a179ac90f3eb134b741ef37baa30434#performance) reports 99.88% accuracy on 17,866 held-out samples: 5,741 human and 12,125 AI-generated. The saved model configuration records the same metrics. Its stated coverage is Suno ≤ 5 and Udio ≤ 1.5. The model card lists FMA, SONICS, and proprietary recordings as training sources, so its complete data is not included here.

## Dataset design

- Use authorized recordings with documented provenance and the reference labels in [Product Scope](product-scope.md).
- Include diverse genres, languages, durations, recording conditions, codecs, and bitrates.
- Include multiple AI generators and versions; record release dates and generation settings where available.
- Split at source-song level before segmenting. Keep edits, encodings, stems, and near duplicates from the same source together.
- Group related sources where necessary to reduce artist, album, and collection leakage.
- Reserve unseen generators or versions for a separate generalization test.
- Report mixed-production and unknown-provenance examples separately.
- Include human recordings with ordinary production tools and processing to measure false accusations.

## Protocol

1. Record the application revision, bundled model checksum, preprocessing, and exact selected-window coverage policy (default first 300 seconds).
2. Select any revised thresholds or abstention policy using validation data only.
3. Freeze all settings before running the held-out test.
4. Evaluate at song level and retain failures, unsupported inputs, and uncertain outcomes in the report.
5. Test transcoding, resampling, trimming, pitch changes, mastering, and other realistic modifications.
6. Report results for known generators, unseen generators, and mixed-production audio separately.

## Quality metrics

Treat AI-generated audio as the positive class. Report the confusion matrix, accuracy, precision, recall, F1 score, false-positive rate, and false-negative rate, with sample counts and confidence intervals. Publish class balance and per-generator, genre, language, and quality breakdowns where sample sizes support them.

Publish both decision coverage and accuracy among decided cases. Also divide correct song-level decisions by all eligible test songs, counting uncertain outcomes as unsuccessful decisions. Define exclusions before testing and report invalid inputs separately so that the report accounts for difficult songs.

Record sample counts and confidence intervals for each metric. Include reliability curves when evaluating score calibration, and choose sample sizes appropriate to the comparisons being made.

## Speed and cost

| Dimension | Required information |
| --- | --- |
| Environment | Hardware, operating system, runtime, model checksum, and numeric precision. |
| Workload | Song count, duration distribution, analyzed duration, concurrency, and rejection count. |
| Latency | Median and p95 end-to-end latency, decoding and inference time; separate cold and warm runs. |
| Throughput | Songs per minute and analyzed audio duration per unit of processing time. |
| Cost | Currency, pricing date, compute rates, utilization, and measured cost per song. |
| Boundaries | Whether upload, queueing, storage, networking, and model loading are included. |

The current service runs one analysis per process; jobs wait in a bounded queue, while synchronous submissions receive HTTP 429 during other work. Account for rejections in load tests. `processing_time_ms` covers the detector's work after upload; measure client-observed latency separately.

Compare candidates on the same dataset and hardware or document differences. Evaluate quality, speed, and cost together so that shorter audio coverage does not conceal missed detections.

## Published results

A benchmark report should include the dataset manifest or access-controlled reference, provenance and split method, exact code and model revisions, thresholds, reproduction commands, metric definitions, confidence intervals, latency, cost, exclusions, and known limitations. Attribute upstream metrics separately from locally measured results.


## Reproducible local evaluation

Supply authorized, independently labeled audio and a UTF-8 CSV:

```csv
path,label
songs/human-recording.flac,human
songs/generated-song.wav,ai
```

Paths are relative to the manifest unless absolute. Run:

```bash
ai-song-detection evaluate labeled-songs.csv --start 0 --duration 300 --output evaluation.json
```

The report retains each input's provenance, failures and uncertain decisions, the model and application metadata, and the current policy. It reports confusion counts with AI as positive, decision coverage, accuracy among decided cases, correct decisions divided by all inputs, and precision/recall/F1/false-positive/false-negative rates with denominators. Missing denominators yield null. Failures produce a nonzero exit code and remain in the output. Prepare labels and grouped held-out splits using the protocol above, and calculate confidence intervals when publishing results. Define a separate labeling protocol for mixed-production recordings before including them in a binary manifest.
