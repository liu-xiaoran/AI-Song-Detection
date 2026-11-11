"""Evaluate metric denominators and corpus input validation, not detection quality."""

import pytest

from ai_song_detection.detector import AudioError
from ai_song_detection.evaluation import evaluate, evaluation_summary, read_manifest


def test_metrics_do_not_hide_uncertain_or_failed_inputs():
    records = [
        {"label": "ai", "assessment": "likely_ai_generated"},
        {"label": "ai", "assessment": "likely_human_created"},
        {"label": "human", "assessment": "likely_ai_generated"},
        {"label": "human", "assessment": "likely_human_created"},
        {"label": "human", "assessment": "uncertain"},
        {"label": "ai", "error": "unreadable"},
    ]
    summary = evaluation_summary(records)
    metrics = summary["metrics"]
    assert summary["decisive"] == 4
    assert summary["completed"] == 5
    assert summary["uncertain"] == {"ai": 0, "human": 1}
    assert summary["failed"] == {"ai": 1, "human": 0}
    assert metrics["decisive_accuracy"] == 0.5
    assert metrics["decisive_accuracy_denominator"] == 4
    assert metrics["false_positive_rate_among_decisive_human"] == 0.5
    assert metrics["false_negative_rate_among_decisive_ai"] == 0.5
    assert metrics["ai_precision_among_decisive"] == 0.5
    assert metrics["ai_precision_denominator"] == 2
    assert metrics["ai_recall_among_decisive"] == 0.5
    assert metrics["ai_recall_denominator"] == 2
    assert metrics["ai_f1_among_decisive"] == 0.5
    assert metrics["ai_f1_denominator"] == 4
    assert metrics["decision_coverage_of_completed"] == 0.8
    assert metrics["correct_decisions_of_all_inputs"] == pytest.approx(1 / 3)


def test_no_decisive_predictions_produces_null_metrics():
    summary = evaluation_summary([{"label": "ai", "assessment": "uncertain"}])
    assert summary["metrics"]["decisive_accuracy"] is None
    assert summary["metrics"]["false_positive_rate_among_decisive_human"] is None
    assert summary["metrics"]["decision_coverage_of_completed"] == 0
    assert summary["metrics"]["ai_precision_among_decisive"] is None
    assert summary["metrics"]["ai_recall_among_decisive"] is None
    assert summary["metrics"]["ai_f1_among_decisive"] is None


@pytest.mark.parametrize(
    "content",
    [
        "name,label\na.wav,human\n",
        "path,label\n",
        "path,label\na.wav,unknown\n",
        "path,label\na.wav,ai\na.wav,human\n",
    ],
)
def test_manifest_rejects_missing_columns_empty_invalid_labels_and_duplicates(tmp_path, content):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(content)
    with pytest.raises(ValueError):
        read_manifest(manifest)


def test_evaluate_resolves_relative_inputs_preserves_labels_and_captures_failures(tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("path,label\ngood.wav,human\nbad.wav,ai\n")
    calls = []

    class Detector:
        def analyze(self, path, **kwargs):
            calls.append((path, kwargs))
            if path.name == "bad.wav":
                raise AudioError("unreadable", "invalid_audio")
            return {"assessment": "likely_human_created", "input_sha256": "a", "report_id": "r"}

    report = evaluate(manifest, Detector(), start_seconds=20, duration_seconds=30)
    assert calls[0] == (tmp_path / "good.wav", {"start_seconds": 20, "duration_seconds": 30})
    assert report["records"][0]["label"] == "human"
    assert report["records"][1]["code"] == "invalid_audio"
    assert report["summary"]["failed"]["ai"] == 1
    assert len(report["manifest_sha256"]) == 64
