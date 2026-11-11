"""Command-line entry points for the web application and local inference."""

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Local AI song detection")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve", help="Start the web interface and API")
    serve.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8000, help="Port (default: 8000)")
    detect = subparsers.add_parser("detect", help="Analyze one or more local audio files")
    detect.add_argument("files", nargs="+", type=Path)
    detect.add_argument("--json", action="store_true", help="Print one JSON object per input file")
    args = parser.parse_args()

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
