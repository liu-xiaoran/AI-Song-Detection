"""CLI batch behavior, machine output, retry boundaries, and window validation."""

import json
import sys

import pytest

from ai_song_detection import cli, detector, launcher


@pytest.fixture
def fake_detector(monkeypatch):
    calls = []

    class Detector:
        def analyze(self, path, **kwargs):
            calls.append((path, kwargs))
            return {
                "filename": path.name,
                "assessment": "uncertain",
                "ai_score": 0.5,
                "analyzed_duration_seconds": 10,
                "processing_time_ms": 1,
                "warnings": [],
            }

    monkeypatch.setattr(detector, "Detector", Detector)
    return calls


def test_detect_directory_jsonl_summary_and_selected_window(
    tmp_path, monkeypatch, capsys, fake_detector
):
    audio = tmp_path / "song.wav"
    audio.touch()
    report = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "tool",
            "detect",
            str(tmp_path),
            "--json",
            "--start",
            "25",
            "--duration",
            "20",
            "--output",
            str(report),
        ],
    )
    cli.main()
    output = capsys.readouterr()
    record = json.loads(output.out)
    assert record["input_path"] == str(audio)
    assert record["attempts"] == 1
    assert "Summary: 1 inputs, 1 completed, 0 failed" in output.err
    assert json.loads(report.read_text()) == [record]
    assert fake_detector == [(audio, {"start_seconds": 25, "duration_seconds": 20})]


def test_retry_only_transient_errors_and_keep_processing_after_invalid_audio(
    tmp_path, monkeypatch, capsys
):
    first, second = tmp_path / "good.wav", tmp_path / "bad.wav"
    counts = {}

    class Detector:
        def analyze(self, path, **kwargs):
            counts[path] = counts.get(path, 0) + 1
            if path == second:
                raise detector.AudioError("Invalid audio", "invalid_audio")
            if counts[path] == 1:
                raise RuntimeError("Transient inference failure")
            return {"assessment": "uncertain", "filename": path.name}

    monkeypatch.setattr(detector, "Detector", Detector)
    monkeypatch.setattr(
        sys, "argv", ["tool", "detect", str(first), str(second), "--json", "--retries", "3"]
    )
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert counts == {first: 2, second: 1}
    assert records[0]["attempts"] == 2
    assert records[1]["code"] == "invalid_audio"


@pytest.mark.parametrize(
    "options",
    [
        ["--start", "-1"],
        ["--start", "nan"],
        ["--duration", "9"],
        ["--duration", "301"],
        ["--duration", "inf"],
        ["--retries", "4"],
    ],
)
def test_invalid_window_and_retry_bounds_fail_before_detector_start(monkeypatch, options):
    monkeypatch.setattr(sys, "argv", ["tool", "detect", "a.wav", *options])
    monkeypatch.setattr(detector, "Detector", lambda: pytest.fail("Detector must not initialize"))
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


def test_status_url_prints_only_ready_url(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["tool", "status", "--url"])
    monkeypatch.setattr(launcher, "status", lambda: {"ready": True, "url": "http://127.0.0.1:8004"})
    cli.main()
    assert capsys.readouterr().out == "http://127.0.0.1:8004\n"
    monkeypatch.setattr(launcher, "status", lambda: {"status": "stopped"})
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1


def test_launch_passes_strict_port_option(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(sys, "argv", ["tool", "launch", "--strict-port", "--no-browser", "--json"])
    monkeypatch.setattr(
        launcher, "launch", lambda **kwargs: calls.append(kwargs) or {"status": "running"}
    )
    cli.main()
    assert calls[0]["strict_port"] is True
    assert json.loads(capsys.readouterr().out)["status"] == "running"


@pytest.mark.parametrize("command", ["update", "uninstall"])
def test_maintenance_dependency_errors_print_actionable_message_without_traceback(
    monkeypatch, capsys, command
):
    from ai_song_detection import maintenance

    exception = (
        maintenance.installer.InstallError
        if command == "update"
        else maintenance.launcher.LauncherError
    )

    def fail(**kwargs):
        raise exception("Actionable dependency error")

    monkeypatch.setattr(maintenance, command, fail)
    monkeypatch.setattr(sys, "argv", ["tool", command])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    assert capsys.readouterr().err == "AI Song Detection: Actionable dependency error\n"
