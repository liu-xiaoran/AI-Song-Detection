# Evaluation Plan

## Claim and current evidence

The project targets **99% song-level accuracy**. No benchmark has been run in this repository, and no accuracy, latency, or cost result is currently established.

A future performance claim must identify the dataset, model version, thresholds, sample size, class distribution, uncertainty handling, and confidence interval. Results apply to the evaluated conditions; they do not guarantee performance on every song or future generator.

## Dataset design

- Use authorized recordings with documented provenance and label definitions from [Product Scope](product-scope.md).
- Include diverse genres, languages, durations, recording conditions, codecs, and bitrates.
- Include multiple AI generators and versions, with release dates and generation settings where available.
- Split training, validation, and test data at the source-song level before segmenting. Keep edits, encodings, stems, and near duplicates from the same source in one split.
- Group related sources where necessary to reduce artist, album, and collection leakage.
- Reserve generators or generator versions absent from training for a separate generalization test.
- Keep mixed-production and unknown-provenance examples in separately reported evaluation sets.
- Include ordinary human production tools and processing in the human-created set to measure false accusations.

## Protocol

1. Establish a reproducible baseline with a versioned model and preprocessing pipeline.
2. Select thresholds and any abstention policy using validation data only.
3. Freeze the model, preprocessing, aggregation strategy, and thresholds before testing.
4. Evaluate held-out songs and report song-level metrics. Segment-level results are supplemental.
5. Evaluate robustness under transcoding, resampling, trimming, mastering, and other realistic audio changes.
6. Report performance on unseen generators and mixed-production audio separately.
7. Record failures, unsupported inputs, and uncertain assessments instead of silently dropping them.

## Quality metrics

For binary evaluation, treat AI-generated audio as the positive class. Report the confusion matrix, accuracy, precision, recall, F1 score, false-positive rate, and false-negative rate, with sample counts and confidence intervals.

Report class balance and per-generator, genre, language, and audio-quality breakdowns where sample sizes support them. Overall accuracy alone can hide poor performance on a minority class.

If the system can abstain, publish both decision coverage and accuracy among decided cases. For the primary 99% target, divide correct song-level decisions by all eligible test songs, counting uncertain outcomes as unsuccessful decisions. Disclose coverage and all exclusions alongside this metric. Invalid inputs should be tracked separately using rules defined before evaluation.

Report calibration if model scores are presented as probabilities. Choose a sample size that supports the intended claim with a meaningful confidence interval; a small test set with 99% observed accuracy is insufficient evidence for a broad claim.

## Speed and cost

For each benchmark, record:

| Dimension | Required information |
| --- | --- |
| Environment | Hardware, operating system, inference runtime, model version, and precision. |
| Workload | Song count, duration distribution, analyzed duration, concurrency, and batch size. |
| Latency | Median and p95 end-to-end latency, plus decoding and inference time; distinguish cold and warm runs. |
| Throughput | Songs per minute and analyzed audio duration per unit of processing time. |
| Cost | Currency, pricing date, compute or service rates, utilization, and measured cost per song. |
| Boundaries | Whether upload, queueing, storage, network transfer, and model loading are included. |

Compare candidate detectors on the same dataset and hardware or document differences explicitly. Evaluate quality, speed, and cost together so that savings from shorter audio coverage do not conceal missed detections.

## Evidence required for published results

Publish a benchmark report containing the dataset manifest or an access-controlled reference, provenance and split method, exact model and code revisions, thresholds, reproduction steps, metric definitions, confidence intervals, latency, cost, exclusions, and known limitations.

Update the README with measured results only after this evidence exists.
