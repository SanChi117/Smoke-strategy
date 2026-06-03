#!/usr/bin/env python3
"""Research API server for Smoke Strategy Lab.

Non-live server wrapper around the research pipeline.

Endpoints:
- GET  /health
- GET  /reports/latest?out_dir=results
- POST /run/pipeline
- POST /run/end-to-end

Research only. No live trading. No exchange keys. No order execution.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from strategy_lab.end_to_end_pipeline import run_end_to_end_pipeline
from strategy_lab.pipeline import run_pipeline


REPORT_FILES = [
    "pipeline_summary.csv",
    "pipeline_validation_summary.csv",
    "pipeline_validation_issues.csv",
    "pipeline_universe_ranking.csv",
    "pipeline_risk_diagnostics.csv",
    "pipeline_risk_policy.csv",
    "pipeline_decisions.csv",
    "end_to_end_summary.csv",
]


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8")
    return json.loads(raw or "{}")


def read_csv_rows(path: Path, limit: int = 50) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = []
        for idx, row in enumerate(csv.DictReader(f)):
            if idx >= limit:
                break
            rows.append(dict(row))
        return rows


def make_safe_path(base_dir: Path, value: str | None, default: str) -> Path:
    rel = value or default
    path = (base_dir / rel).resolve() if not Path(rel).is_absolute() else Path(rel).resolve()
    base = base_dir.resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Path escapes server base directory: {rel}") from exc
    return path


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def create_handler(base_dir: str | Path = "."):
    root = Path(base_dir).resolve()

    class ResearchHandler(BaseHTTPRequestHandler):
        server_version = "SmokeResearchServer/0.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            # Keep stdout clean for scripts/tests. Reverse this if VPS logging is needed.
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/health":
                    json_response(self, 200, {"status": "ok", "mode": "research", "base_dir": str(root)})
                    return
                if parsed.path == "/reports/latest":
                    query = parse_qs(parsed.query)
                    out_dir = make_safe_path(root, query.get("out_dir", ["results"])[0], "results")
                    reports = {name: read_csv_rows(out_dir / name) for name in REPORT_FILES if (out_dir / name).exists()}
                    json_response(self, 200, {"status": "ok", "out_dir": str(out_dir), "reports": reports})
                    return
                json_response(self, 404, {"status": "error", "error": "not_found", "path": parsed.path})
            except Exception as exc:  # pragma: no cover - defensive server boundary
                json_response(self, 500, {"status": "error", "error": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                body = read_json_body(self)
                if parsed.path == "/run/pipeline":
                    input_csv = make_safe_path(root, body.get("input_csv"), "data/sample_runner_trades.csv")
                    out_dir = make_safe_path(root, body.get("out_dir"), "results")
                    profile = str(body.get("profile", "growth_100_20x"))
                    summary = run_pipeline(input_csv=input_csv, out_dir=out_dir, profile_name=profile)
                    json_response(self, 200, {"status": "ok", "summary": asdict(summary), "out_dir": str(out_dir)})
                    return
                if parsed.path == "/run/end-to-end":
                    candles_csv = make_safe_path(root, body.get("candles_csv"), "data/candles.csv")
                    out_dir = make_safe_path(root, body.get("out_dir"), "results")
                    profile = str(body.get("profile", "growth_100_20x"))
                    min_confidence = float(body.get("min_confidence", 50.0))
                    summary = run_end_to_end_pipeline(candles_csv=candles_csv, out_dir=out_dir, profile=profile, min_confidence=min_confidence)
                    json_response(self, 200, {"status": "ok", "summary": asdict(summary), "out_dir": str(out_dir)})
                    return
                json_response(self, 404, {"status": "error", "error": "not_found", "path": parsed.path})
            except Exception as exc:  # pragma: no cover - defensive server boundary
                json_response(self, 500, {"status": "error", "error": str(exc)})

    return ResearchHandler


def run_server(host: str = "127.0.0.1", port: int = 8080, base_dir: str | Path = ".") -> None:
    handler = create_handler(base_dir)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Smoke research server running on http://{host}:{port}")
    print(f"Base directory: {Path(base_dir).resolve()}")
    server.serve_forever()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--base-dir", default=".")
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, base_dir=args.base_dir)


if __name__ == "__main__":
    main()
