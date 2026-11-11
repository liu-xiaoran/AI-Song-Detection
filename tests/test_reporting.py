"""Reports preserve traceability while remaining safe for spreadsheet readers."""

import csv
import json

import pytest

from ai_song_detection.reporting import collect_inputs, summarize, write_report


def test_directory_expansion_deduplicates_and_only_recurses_when_requested(tmp_path):
    first = tmp_path / "A.wav"
    first.touch()
    (tmp_path / "notes.txt").touch()
    nested = tmp_path / "nested"
    nested.mkdir()
    second = nested / "b.MP3"
    second.touch()
    assert collect_inputs([tmp_path, first]) == [first]
    assert collect_inputs([tmp_path, first], recursive=True) == [first, second]


def test_csv_neutralizes_filename_path_and_error_formulas_preserving_numeric_scores(tmp_path):
    output = tmp_path / "result.csv"
    record = {
        "input_path": '  =HYPERLINK("bad")',
        "filename": "+evil.wav",
        "error": "\t@command",
        "ai_score": 0.25,
        "model": {"sha256": "abc"},
        "decision_policy": {"version": 1},
        "warnings": ["review"],
    }
    write_report(output, [record])
    with output.open(newline="") as saved:
        row = next(csv.DictReader(saved))
    assert row["input_path"].startswith("'  =")
    assert row["filename"] == "'+evil.wav"
    assert row["error"] == "'\t@command"
    assert row["ai_score"] == "0.25"
    assert row["model_sha256"] == "abc"
    assert json.loads(row["decision_policy"]) == {"version": 1}


def test_json_jsonl_and_summary_include_success_uncertain_and_failure(tmp_path):
    records = [
        {"filename": "AI.wav", "assessment": "likely_ai_generated", "input_sha256": "a"},
        {"filename": "human.wav", "assessment": "likely_human_created"},
        {"filename": "maybe.wav", "assessment": "uncertain"},
        {"filename": "bad.wav", "error": "not audio", "code": "invalid_audio"},
    ]
    for suffix in ("json", "jsonl"):
        output = tmp_path / f"reports.{suffix}"
        write_report(output, records)
        parsed = (
            json.loads(output.read_text())
            if suffix == "json"
            else [json.loads(line) for line in output.read_text().splitlines()]
        )
        assert parsed == records
    assert summarize(records) == {
        "total": 4,
        "completed": 3,
        "failed": 1,
        "likely_ai_generated": 1,
        "likely_human_created": 1,
        "uncertain": 1,
    }


def test_invalid_report_does_not_replace_existing_output(tmp_path):
    output = tmp_path / "report.json"
    output.write_text("existing")
    with pytest.raises(ValueError):
        write_report(output, [{"ai_score": float("nan")}])
    assert output.read_text() == "existing"
    assert list(tmp_path.iterdir()) == [output]
