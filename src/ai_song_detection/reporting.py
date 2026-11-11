"""Portable detection reports; all audio and result storage is explicitly requested."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".aiff",
    ".aif",
    ".wma",
}
CSV_FIELDS = (
    "input_path",
    "filename",
    "assessment",
    "ai_score",
    "analyzed_start_seconds",
    "analyzed_end_seconds",
    "analyzed_duration_seconds",
    "audio_duration_seconds",
    "requested_duration_seconds",
    "truncated",
    "processing_time_ms",
    "input_sha256",
    "input_size_bytes",
    "application_version",
    "analyzed_at",
    "report_id",
    "attempts",
    "model_sha256",
    "decision_policy",
    "warnings",
    "code",
    "error",
)


def collect_inputs(inputs: list[Path], *, recursive: bool = False) -> list[Path]:
    """Expand directories in a stable order and avoid duplicate resolved paths."""
    collected: list[Path] = []
    seen: set[str] = set()
    for source in inputs:
        candidates = [source]
        if source.is_dir():
            candidates = sorted(
                (
                    path
                    for path in (source.rglob("*") if recursive else source.iterdir())
                    if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
                ),
                key=lambda path: str(path).casefold(),
            )
        for candidate in candidates:
            identity = os.path.normcase(str(candidate.resolve()))
            if identity not in seen:
                seen.add(identity)
                collected.append(candidate)
    return collected


def summarize(records: list[dict[str, Any]]) -> dict[str, int]:
    assessments = Counter(record.get("assessment") for record in records if "error" not in record)
    failed = sum("error" in record for record in records)
    return {
        "total": len(records),
        "completed": len(records) - failed,
        "failed": failed,
        "likely_ai_generated": assessments["likely_ai_generated"],
        "likely_human_created": assessments["likely_human_created"],
        "uncertain": assessments["uncertain"],
    }


def safe_csv_cell(value: Any) -> Any:
    """Neutralize text formulas when opened in spreadsheet software."""
    if isinstance(value, str) and value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    if isinstance(value, str) and value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def write_report(path: Path, records: list[dict[str, Any]]) -> None:
    """Atomically save JSON, JSONL, or CSV based on the requested file extension."""
    suffix = path.suffix.lower()
    if suffix not in {".json", ".jsonl", ".csv"}:
        raise ValueError("Report output must end in .json, .jsonl, or .csv.")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as output:
            if suffix == ".json":
                json.dump(records, output, ensure_ascii=False, allow_nan=False, indent=2)
                output.write("\n")
            elif suffix == ".jsonl":
                for record in records:
                    output.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            else:
                writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction="ignore")
                writer.writeheader()
                for record in records:
                    row = dict(record)
                    row["model_sha256"] = record.get("model", {}).get("sha256", "")
                    for field in ("decision_policy", "warnings"):
                        if field in row:
                            row[field] = json.dumps(row[field], ensure_ascii=False, allow_nan=False)
                    writer.writerow({field: safe_csv_cell(value) for field, value in row.items()})
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
