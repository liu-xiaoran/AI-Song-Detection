"""Command-line entry points for the web application and local inference."""

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Local AI song detection")
    subparsers = parser.add_subparsers(
        dest="command", required=True, metavar="{launch,status,stop,serve,detect}"
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
    status = subparsers.add_parser("status", help="Show the managed app's address and status")
    status.add_argument("--json", action="store_true")
    stop = subparsers.add_parser("stop", help="Gracefully stop the managed app")
    stop.add_argument("--timeout", type=float, default=90, help="Shutdown timeout in seconds")
    stop.add_argument("--json", action="store_true")
    managed = subparsers.add_parser("_managed-serve")
    managed.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1")
    managed.add_argument("--port", type=int, required=True)
    detect = subparsers.add_parser("detect", help="Analyze one or more local audio files")
    detect.add_argument("files", nargs="+", type=Path)
    detect.add_argument("--json", action="store_true", help="Print one JSON object per input file")
    args = parser.parse_args()

    if args.command in {"launch", "status", "stop"}:
        from . import launcher

        try:
            if args.command == "launch":
                result = launcher.launch(
                    port=args.port, open_browser=not args.no_browser, timeout=args.timeout
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
        if args.json:
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

    from .detector import AudioError, Detector

    try:
        detector = Detector()
    except (RuntimeError, OSError) as exc:
        print(f"Detector initialization failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    failed = False
    for path in args.files:
        try:
            result = detector.analyze(path)
        except (AudioError, OSError, RuntimeError) as exc:
            failed = True
            if args.json:
                print(
                    json.dumps(
                        {
                            "filename": path.name,
                            "error": str(exc),
                            "code": getattr(exc, "code", "file_error"),
                        }
                    )
                )
            else:
                print(f"{path.name}: {exc}", file=sys.stderr)
            continue
        if args.json:
            print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        else:
            label = result["assessment"].replace("_", " ")
            print(
                f"{path.name}: {label} | AI score {result['ai_score']:.1%} | "
                f"{result['analyzed_duration_seconds']:.1f}s analyzed | "
                f"{result['processing_time_ms']:.0f}ms"
            )
            for warning in result["warnings"]:
                print(f"  Note: {warning}")
    if failed:
        raise SystemExit(1)
