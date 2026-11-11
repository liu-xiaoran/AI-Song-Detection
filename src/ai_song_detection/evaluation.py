"""Evaluate a caller-supplied labeled corpus without implying model calibration."""

from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path
from typing import Any

from . import __version__


def read_manifest(path: Path) -> list[tuple[Path, str]]:
    """Read path,label CSV; resolve relative paths against the manifest folder."""
    return _parse_manifest(path, path.read_text(encoding="utf-8-sig"))


def _parse_manifest(path: Path, content: str) -> list[tuple[Path, str]]:
    entries: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    with io.StringIO(content, newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None or not {"path", "label"}.issubset(reader.fieldnames):
            raise ValueError("Evaluation CSV must have path and label columns (human or ai).")
        for line, row in enumerate(reader, start=2):
            label = (row.get("label") or "").strip().lower()
            filename = (row.get("path") or "").strip()
            if label not in {"human", "ai"} or not filename:
                raise ValueError(
                    f"Invalid evaluation row {line}: supply a path and human/ai label."
                )
            audio = Path(filename)
            if not audio.is_absolute():
                audio = path.parent / audio
            audio = audio.resolve()
            if audio in seen:
                raise ValueError(f"Duplicate input in evaluation row {line}: {filename}")
            seen.add(audio)
            entries.append((audio, label))
    if not entries:
        raise ValueError("Evaluation CSV has no labeled inputs.")
    return entries


def evaluation_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Report uncertainty separately; decisive accuracy excludes uncertain and errors."""
    matrix = {"ai_as_ai": 0, "ai_as_human": 0, "human_as_ai": 0, "human_as_human": 0}
    uncertain = {"ai": 0, "human": 0}
    failed = {"ai": 0, "human": 0}
    for record in records:
        label = record["label"]
        if "error" in record:
            failed[label] += 1
        elif record["assessment"] == "uncertain":
            uncertain[label] += 1
        else:
            predicted = "ai" if record["assessment"] == "likely_ai_generated" else "human"
            matrix[f"{label}_as_{predicted}"] += 1
    decisive = sum(matrix.values())
    completed = decisive + sum(uncertain.values())
    correct = matrix["ai_as_ai"] + matrix["human_as_human"]
    human_decisive = matrix["human_as_ai"] + matrix["human_as_human"]
    ai_decisive = matrix["ai_as_ai"] + matrix["ai_as_human"]
    ai_predictions = matrix["ai_as_ai"] + matrix["human_as_ai"]
    f1_denominator = 2 * matrix["ai_as_ai"] + matrix["human_as_ai"] + matrix["ai_as_human"]
    return {
        "total": len(records),
        "completed": completed,
        "decisive": decisive,
        "uncertain": uncertain,
        "failed": failed,
        "confusion_matrix": matrix,
        "metrics": {
            "decisive_accuracy": correct / decisive if decisive else None,
            "decisive_accuracy_denominator": decisive,
            "false_positive_rate_among_decisive_human": (
                matrix["human_as_ai"] / human_decisive if human_decisive else None
            ),
            "false_positive_rate_denominator": human_decisive,
            "false_negative_rate_among_decisive_ai": (
                matrix["ai_as_human"] / ai_decisive if ai_decisive else None
            ),
            "false_negative_rate_denominator": ai_decisive,
            "ai_precision_among_decisive": (
                matrix["ai_as_ai"] / ai_predictions if ai_predictions else None
            ),
            "ai_precision_denominator": ai_predictions,
            "ai_recall_among_decisive": (matrix["ai_as_ai"] / ai_decisive if ai_decisive else None),
            "ai_recall_denominator": ai_decisive,
            "ai_f1_among_decisive": (
                2 * matrix["ai_as_ai"] / f1_denominator if f1_denominator else None
            ),
            "ai_f1_denominator": f1_denominator,
            "decision_coverage_of_completed": decisive / completed if completed else None,
            "completion_rate": completed / len(records) if records else None,
            "correct_decisions_of_all_inputs": correct / len(records) if records else None,
        },
        "limitations": [
            "Labels and corpus representativeness are supplied by the caller and are not verified.",
            "Uncertain results and failures are excluded from decisive accuracy and error rates.",
            "This report measures only this corpus, model, decision policy, and selected audio window.",
            "Model scores are not calibrated probabilities; this is not independent certification.",
        ],
    }


def evaluate(
    manifest: Path,
    detector: Any,
    *,
    start_seconds: float = 0,
    duration_seconds: float = 300,
) -> dict[str, Any]:
    from .detector import DECISION_POLICY, AudioError

    manifest_bytes = manifest.read_bytes()
    entries = _parse_manifest(manifest, manifest_bytes.decode("utf-8-sig"))
    records: list[dict[str, Any]] = []
    for audio, label in entries:
        record = {"input_path": str(audio), "label": label}
        try:
            record.update(
                detector.analyze(
                    audio, start_seconds=start_seconds, duration_seconds=duration_seconds
                )
            )
        except (AudioError, OSError, RuntimeError) as exc:
            record.update(error=str(exc), code=getattr(exc, "code", "file_error"))
        records.append(record)
    return {
        "application_version": __version__,
        "model": dict(getattr(detector, "model", {})),
        "decision_policy": dict(DECISION_POLICY),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "start_seconds": start_seconds,
        "requested_duration_seconds": duration_seconds,
        "summary": evaluation_summary(records),
        "records": records,
    }
