"""Command-line entry points for the web application and local inference."""

import argparse
import json
import math
import os
import sys
from pathlib import Path


def _nonnegative(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError(
            "Use a finite number of seconds greater than or equal to 0."
        )
    return number


def _duration(value: str) -> float:
    number = _nonnegative(value)
    if not 10 <= number <= 300:
        raise argparse.ArgumentTypeError("Duration must be between 10 and 300 seconds.")
    return number


def _window_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", type=_nonnegative, default=0, help="Start offset in seconds")
    parser.add_argument(
        "--duration", type=_duration, default=300, help="Analyze 10–300 seconds (default: 300)"
    )


def _detect(args, parser: argparse.ArgumentParser, detector) -> None:
    from .detector import AudioError
    from .reporting import collect_inputs, summarize, write_report

    try:
        inputs = collect_inputs(args.files, recursive=args.recursive)
    except OSError as exc:
        parser.error(f"Cannot enumerate inputs: {exc}")
    if not inputs:
        parser.error("No supported audio files found in the supplied directories.")
    if args.output:
        if args.output.suffix.lower() not in {".json", ".jsonl", ".csv"}:
            parser.error("Report output must end in .json, .jsonl, or .csv.")
        if args.output.resolve() in {path.resolve() for path in inputs}:
            parser.error("The report output must not overwrite an input file.")
    records = []
    for path in inputs:
        record = {"input_path": str(path.resolve()), "filename": path.name}
        for attempt in range(args.retries + 1):
            record["attempts"] = attempt + 1
            try:
                record.update(
                    detector.analyze(path, start_seconds=args.start, duration_seconds=args.duration)
                )
                break
            except (AudioError, OSError, RuntimeError) as exc:
                # Invalid content and missing/inaccessible files cannot improve on retry.
                retryable = not isinstance(exc, (AudioError, FileNotFoundError, PermissionError))
                if retryable and attempt < args.retries:
                    print(f"Retrying {path.name} after error: {exc}", file=sys.stderr)
                    continue
                record.update(error=str(exc), code=getattr(exc, "code", "file_error"))
                break
        records.append(record)
        if args.json:
            print(json.dumps(record, ensure_ascii=True, allow_nan=False))
        elif "error" in record:
            print(f"{path.name}: {record['error']}", file=sys.stderr)
        else:
            label = record["assessment"].replace("_", " ")
            print(
                f"{path.name}: {label} | AI score {record['ai_score']:.1%} | "
                f"{record['analyzed_duration_seconds']:.1f}s analyzed | "
                f"{record['processing_time_ms']:.0f}ms"
            )
            for warning in record["warnings"]:
                print(f"  Note: {warning}")
    if args.output:
        try:
            write_report(args.output, records)
        except (OSError, ValueError) as exc:
            print(f"Cannot save report: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"Report saved: {args.output}", file=sys.stderr)
    summary = summarize(records)
    print(
        f"Summary: {summary['total']} inputs, {summary['completed']} completed, "
        f"{summary['failed']} failed; {summary['likely_ai_generated']} likely AI, "
        f"{summary['likely_human_created']} likely human, {summary['uncertain']} uncertain.",
        file=sys.stderr,
    )
    if summary["failed"]:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local AI song detection")
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{launch,status,stop,serve,detect,evaluate,doctor,logs,diagnostics,update,cleanup,uninstall,shell-setup,bundle}",
    )
    serve = subparsers.add_parser("serve", help="Start the web interface and API")
    serve.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    launch = subparsers.add_parser("launch", help="Start or reopen the app in your default browser")
    launch.add_argument(
        "--port", type=int, default=8000, help="Preferred port; choose another if busy"
    )
    launch.add_argument("--no-browser", action="store_true", help="Start without opening a browser")
    launch.add_argument("--timeout", type=float, default=45, help="Startup timeout in seconds")
    launch.add_argument("--json", action="store_true")
    launch.add_argument("--strict-port", action="store_true", help="Fail if the exact port is busy")
    status = subparsers.add_parser("status", help="Show the managed app's address and status")
    status_format = status.add_mutually_exclusive_group()
    status_format.add_argument("--json", action="store_true")
    status_format.add_argument("--url", action="store_true", help="Print only the running app URL")
    stop = subparsers.add_parser("stop", help="Gracefully stop the managed app")
    stop.add_argument("--timeout", type=float, default=90, help="Shutdown timeout in seconds")
    stop.add_argument("--json", action="store_true")
    managed = subparsers.add_parser("_managed-serve")
    managed.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1")
    managed.add_argument("--port", type=int, required=True)
    detect = subparsers.add_parser("detect", help="Analyze local audio files or directories")
    detect.add_argument("files", nargs="+", type=Path)
    detect.add_argument("--json", action="store_true", help="Print one JSON object per input file")
    detect.add_argument("--recursive", action="store_true", help="Include subdirectories")
    detect.add_argument(
        "--retries", type=int, choices=range(4), default=0, help="Retries per transient error (0–3)"
    )
    detect.add_argument("--output", type=Path, help="Save a .json, .jsonl, or .csv report")
    _window_options(detect)
    evaluate = subparsers.add_parser(
        "evaluate", help="Measure a caller-supplied labeled CSV corpus"
    )
    evaluate.add_argument("manifest", type=Path, help="CSV columns: path,label (human or ai)")
    evaluate.add_argument(
        "--output", type=Path, help="Save the complete evaluation report as .json"
    )
    _window_options(evaluate)
    doctor = subparsers.add_parser("doctor", help="Check installed dependencies and service health")
    doctor.add_argument("--json", action="store_true")
    logs = subparsers.add_parser("logs", help="Read the managed service log")
    logs.add_argument("--follow", action="store_true")
    logs.add_argument("--lines", type=int, default=100)
    diagnostics = subparsers.add_parser("diagnostics", help="Export a sanitized diagnostic ZIP")
    diagnostics.add_argument("--output", type=Path, required=True)
    update = subparsers.add_parser(
        "update", help="Install the latest release or a local source tree"
    )
    update.add_argument("--source", type=Path)
    update.add_argument("--no-launch", action="store_true")
    cleanup = subparsers.add_parser("cleanup", help="Preview or remove inactive releases and cache")
    cleanup.add_argument("--keep", type=int, default=2)
    cleanup.add_argument("--apply", action="store_true", help="Apply the displayed cleanup plan")
    cleanup.add_argument("--cache", action="store_true", help="Include the download cache")
    uninstall = subparsers.add_parser(
        "uninstall", help="Preview or remove this user's installation"
    )
    uninstall.add_argument(
        "--apply", action="store_true", help="Stop the app and remove the installation"
    )
    shell_setup = subparsers.add_parser(
        "shell-setup", help="Create a short CLI entry in a chosen directory"
    )
    shell_setup.add_argument("--directory", type=Path, required=True)
    bundle_parser = subparsers.add_parser(
        "bundle", help="Create a platform-specific offline installer directory"
    )
    bundle_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "bundle":
        from . import bundle

        try:
            print(json.dumps(bundle.create(args.output), ensure_ascii=True, indent=2))
        except (bundle.BundleError, OSError, ValueError) as exc:
            print(f"AI Song Detection: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return

    if args.command in {"launch", "status", "stop"}:
        from . import launcher

        try:
            if args.command == "launch":
                result = launcher.launch(
                    port=args.port,
                    open_browser=not args.no_browser,
                    timeout=args.timeout,
                    strict_port=args.strict_port,
                )
            elif args.command == "stop":
                result = launcher.stop(timeout=args.timeout)
            else:
                result = launcher.status()
        except (launcher.LauncherError, OSError) as exc:
            if args.json:
                print(json.dumps({"status": "error", "message": str(exc)}))
            else:
                print(f"AI Song Detection: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if args.command == "status" and args.url:
            if result.get("ready") and result.get("url"):
                print(result["url"])
            else:
                raise SystemExit(1)
        elif args.json:
            print(json.dumps(result, ensure_ascii=True))
        else:
            print(f"AI Song Detection: {result.get('status', 'unknown')}")
            if result.get("url"):
                print(f"Open: {result['url']}")
            if (
                args.command == "launch"
                and not args.no_browser
                and not result.get("browser_opened")
            ):
                print("The browser could not be opened automatically. Open the address above.")
            if result.get("log_file"):
                print(f"Log: {result['log_file']}")
        return

    if args.command in {
        "doctor",
        "logs",
        "diagnostics",
        "update",
        "cleanup",
        "uninstall",
        "shell-setup",
    }:
        from . import maintenance

        try:
            if args.command == "logs":
                maintenance.logs(follow=args.follow, lines=args.lines)
                return
            if args.command == "doctor":
                result = maintenance.doctor()
            elif args.command == "diagnostics":
                result = maintenance.diagnostics(args.output)
            elif args.command == "update":
                result = maintenance.update(source=args.source, launch=not args.no_launch)
            elif args.command == "cleanup":
                result = maintenance.cleanup(keep=args.keep, apply=args.apply, cache=args.cache)
            elif args.command == "uninstall":
                result = maintenance.uninstall(apply=args.apply)
            else:
                result = maintenance.shell_setup(args.directory)
            print(json.dumps(result, ensure_ascii=True, indent=2))
            if args.command == "doctor" and not result["ok"]:
                raise SystemExit(1)
        except (
            maintenance.MaintenanceError,
            maintenance.installer.InstallError,
            maintenance.launcher.LauncherError,
            OSError,
            ValueError,
        ) as exc:
            print(f"AI Song Detection: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        except KeyboardInterrupt:
            return
        return

    if args.command == "_managed-serve":
        if not os.environ.get("AI_SONG_DETECTION_INSTANCE_ID") or not os.environ.get(
            "AI_SONG_DETECTION_CONTROL_TOKEN"
        ):
            parser.error("Managed service startup requires the launcher. Use 'launch' instead.")
        import uvicorn

        from .launcher import service_lease
        from .server import app

        service = uvicorn.Server(
            uvicorn.Config(
                app, host=args.host, port=args.port, workers=1, timeout_graceful_shutdown=75
            )
        )

        def request_shutdown():
            service.should_exit = True

        app.state.request_shutdown = request_shutdown
        with service_lease():
            service.run()
        return

    if args.command == "serve":
        import uvicorn

        uvicorn.run("ai_song_detection.server:app", host=args.host, port=args.port, workers=1)
        return

    if args.command == "evaluate":
        from .evaluation import read_manifest

        try:
            read_manifest(args.manifest)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        if args.output and args.output.suffix.lower() != ".json":
            parser.error("Evaluation output must end in .json.")

    from .detector import Detector

    try:
        detector = Detector()
    except (RuntimeError, OSError) as exc:
        print(f"Detector initialization failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if args.command == "evaluate":
        from .evaluation import evaluate

        try:
            report = evaluate(
                args.manifest, detector, start_seconds=args.start, duration_seconds=args.duration
            )
            serialized = json.dumps(report, ensure_ascii=True, allow_nan=False, indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(serialized + "\n", encoding="utf-8")
                print(f"Evaluation saved: {args.output}", file=sys.stderr)
            print(serialized)
            if sum(report["summary"]["failed"].values()):
                raise SystemExit(1)
        except (OSError, ValueError) as exc:
            print(f"Cannot evaluate corpus: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return
    _detect(args, parser, detector)
