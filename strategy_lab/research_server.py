#!/usr/bin/env python3
"""Research API server for Smoke Strategy Lab.

Non-live server wrapper around the research pipeline.

Endpoints:
- GET  /health
- GET  /runs/list?runs_dir=results/runs&limit=20
- GET  /runs/latest?runs_dir=results/runs
- GET  /reports/latest?out_dir=results&run_id=<optional>
- POST /run/pipeline
- POST /run/end-to-end
- POST /run/paper

Optional auth:
- Set RESEARCH_SERVER_TOKEN to protect all non-health endpoints.
- Pass token via X-Research-Token header or research_token JSON body field.

Research only. No live trading. No exchange keys. No order execution.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from strategy_lab.end_to_end_pipeline import run_end_to_end_pipeline
from strategy_lab.paper_mode import run_paper_mode
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
    "report_sanity_summary.csv",
    "report_sanity_issues.csv",
    "data_quality_summary.csv",
    "data_quality_report.csv",
    "data_quality_issues.csv",
    "candle_research_report.csv",
    "candle_exit_diagnostics.csv",
    "candle_exit_results.csv",
    "generated_trades.csv",
    "paper/paper_signals.csv",
    "paper/paper_journal.csv",
    "paper/paper_positions.csv",
    "paper/paper_review.csv",
    "paper/paper_review_summary.csv",
    "paper/paper_decision_summary.csv",
    "paper/paper_summary.csv",
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


def make_run_id(prefix: str) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ")
    safe_prefix = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in prefix).strip("-") or "run"
    return f"{safe_prefix}-{stamp}"


def resolve_run_out_dir(root: Path, body: dict[str, Any], default_out_dir: str, run_prefix: str) -> tuple[Path, str | None]:
    if body.get("run_id"):
        run_id = str(body["run_id"])
        out_dir = make_safe_path(root, body.get("out_dir"), default_out_dir) / "runs" / run_id
        return out_dir, run_id
    if bool(body.get("per_run", True)):
        run_id = make_run_id(run_prefix)
        out_dir = make_safe_path(root, body.get("out_dir"), default_out_dir) / "runs" / run_id
        return out_dir, run_id
    out_dir = make_safe_path(root, body.get("out_dir"), default_out_dir)
    return out_dir, None


def write_run_metadata(out_dir: Path, payload: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    (out_dir / "run_metadata.json").write_bytes(data)


def read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def latest_run_dir(runs_dir: Path) -> Path | None:
    if not runs_dir.exists():
        return None
    dirs = [p for p in runs_dir.iterdir() if p.is_dir()]
    if not dirs:
        return None
    return sorted(dirs, key=lambda p: p.name)[-1]


def list_run_records(runs_dir: Path, limit: int = 20) -> list[dict[str, Any]]:
    if not runs_dir.exists():
        return []
    dirs = sorted([p for p in runs_dir.iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True)
    records: list[dict[str, Any]] = []
    for run_dir in dirs[: max(1, limit)]:
        metadata = read_json_file(run_dir / "run_metadata.json")
        summary = metadata.get("summary", {}) if isinstance(metadata, dict) else {}
        records.append({
            "run_id": run_dir.name,
            "out_dir": str(run_dir),
            "type": metadata.get("type", "unknown") if isinstance(metadata, dict) else "unknown",
            "started_at": metadata.get("started_at", "") if isinstance(metadata, dict) else "",
            "completed_at": metadata.get("completed_at", "") if isinstance(metadata, dict) else "",
            "profile": metadata.get("profile", "") if isinstance(metadata, dict) else "",
            "sanity_status": summary.get("sanity_status", "") if isinstance(summary, dict) else "",
            "generated_trades": summary.get("generated_trades", "") if isinstance(summary, dict) else "",
            "executed_trades": summary.get("executed_trades", "") if isinstance(summary, dict) else "",
            "paper_signals": summary.get("paper_signals", "") if isinstance(summary, dict) else "",
            "paper_closed": summary.get("paper_closed", summary.get("closed_paper", "")) if isinstance(summary, dict) else "",
            "paper_review_status": summary.get("review_status", "") if isinstance(summary, dict) else "",
            "ret_pct": summary.get("ret_pct", "") if isinstance(summary, dict) else "",
            "max_dd_pct": summary.get("max_dd_pct", "") if isinstance(summary, dict) else "",
        })
    return records


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def expected_token() -> str:
    return os.environ.get("RESEARCH_SERVER_TOKEN", "").strip()


def token_from_request(handler: BaseHTTPRequestHandler, body: dict[str, Any] | None = None) -> str:
    header = handler.headers.get("X-Research-Token", "")
    if header:
        return header.strip()
    if body and body.get("research_token"):
        return str(body.get("research_token", "")).strip()
    parsed = urlparse(handler.path)
    query = parse_qs(parsed.query)
    return str(query.get("research_token", [""])[0]).strip()


def is_authorized(handler: BaseHTTPRequestHandler, body: dict[str, Any] | None = None) -> bool:
    required = expected_token()
    if not required:
        return True
    return token_from_request(handler, body) == required


def auth_error(handler: BaseHTTPRequestHandler) -> None:
    json_response(handler, 401, {"status": "error", "error": "unauthorized", "message": "Missing or invalid research token."})


def create_handler(base_dir: str | Path = "."):
    root = Path(base_dir).resolve()

    class ResearchHandler(BaseHTTPRequestHandler):
        server_version = "SmokeResearchServer/0.7"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                query = parse_qs(parsed.query)
                if parsed.path == "/health":
                    json_response(self, 200, {"status": "ok", "mode": "research", "base_dir": str(root), "server_version": self.server_version, "auth_enabled": bool(expected_token())})
                    return
                if not is_authorized(self):
                    auth_error(self)
                    return
                if parsed.path == "/runs/list":
                    runs_dir = make_safe_path(root, query.get("runs_dir", ["results/runs"])[0], "results/runs")
                    limit = int(query.get("limit", ["20"])[0])
                    records = list_run_records(runs_dir, limit=limit)
                    json_response(self, 200, {"status": "ok", "runs_dir": str(runs_dir), "count": len(records), "runs": records})
                    return
                if parsed.path == "/runs/latest":
                    runs_dir = make_safe_path(root, query.get("runs_dir", ["results/runs"])[0], "results/runs")
                    run_dir = latest_run_dir(runs_dir)
                    if not run_dir:
                        json_response(self, 404, {"status": "error", "error": "no_runs_found", "runs_dir": str(runs_dir)})
                        return
                    json_response(self, 200, {"status": "ok", "run_id": run_dir.name, "out_dir": str(run_dir), "metadata": read_json_file(run_dir / "run_metadata.json")})
                    return
                if parsed.path == "/reports/latest":
                    base_out = make_safe_path(root, query.get("out_dir", ["results"])[0], "results")
                    run_id = query.get("run_id", [None])[0]
                    if run_id:
                        out_dir = make_safe_path(root, f"{base_out.relative_to(root)}/runs/{run_id}", "results")
                    elif (base_out / "runs").exists():
                        out_dir = latest_run_dir(base_out / "runs") or base_out
                    else:
                        out_dir = base_out
                    reports = {name: read_csv_rows(out_dir / name) for name in REPORT_FILES if (out_dir / name).exists()}
                    json_response(self, 200, {"status": "ok", "out_dir": str(out_dir), "run_id": out_dir.name if out_dir.parent.name == "runs" else None, "reports": reports})
                    return
                json_response(self, 404, {"status": "error", "error": "not_found", "path": parsed.path})
            except Exception as exc:  # pragma: no cover - defensive server boundary
                json_response(self, 500, {"status": "error", "error": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                body = read_json_body(self)
                if not is_authorized(self, body):
                    auth_error(self)
                    return
                if parsed.path == "/run/pipeline":
                    input_csv = make_safe_path(root, body.get("input_csv"), "data/sample_runner_trades.csv")
                    out_dir, run_id = resolve_run_out_dir(root, body, "results", "pipeline")
                    profile = str(body.get("profile", "growth_100_20x"))
                    started_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                    summary = run_pipeline(input_csv=input_csv, out_dir=out_dir, profile_name=profile)
                    metadata = {"run_id": run_id, "type": "pipeline", "started_at": started_at, "completed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z", "input_csv": str(input_csv), "profile": profile, "summary": asdict(summary)}
                    write_run_metadata(out_dir, metadata)
                    json_response(self, 200, {"status": "ok", "run_id": run_id, "summary": asdict(summary), "out_dir": str(out_dir)})
                    return
                if parsed.path == "/run/end-to-end":
                    candles_csv = make_safe_path(root, body.get("candles_csv"), "data/candles.csv")
                    out_dir, run_id = resolve_run_out_dir(root, body, "results", "end-to-end")
                    profile = str(body.get("profile", "growth_100_20x"))
                    min_confidence = float(body.get("min_confidence", 50.0))
                    started_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                    summary = run_end_to_end_pipeline(candles_csv=candles_csv, out_dir=out_dir, profile=profile, min_confidence=min_confidence)
                    metadata = {"run_id": run_id, "type": "end-to-end", "started_at": started_at, "completed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z", "candles_csv": str(candles_csv), "profile": profile, "min_confidence": min_confidence, "summary": asdict(summary)}
                    write_run_metadata(out_dir, metadata)
                    json_response(self, 200, {"status": "ok", "run_id": run_id, "summary": asdict(summary), "out_dir": str(out_dir)})
                    return
                if parsed.path == "/run/paper":
                    generated_trades_csv = make_safe_path(root, body.get("generated_trades_csv"), "results/generated_trades.csv")
                    out_dir, run_id = resolve_run_out_dir(root, body, "results", "paper")
                    paper_out = out_dir / "paper"
                    started_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
                    summary = run_paper_mode(generated_trades_csv=generated_trades_csv, out_dir=paper_out)
                    metadata = {"run_id": run_id, "type": "paper", "started_at": started_at, "completed_at": datetime.utcnow().isoformat(timespec="seconds") + "Z", "generated_trades_csv": str(generated_trades_csv), "summary": asdict(summary)}
                    write_run_metadata(out_dir, metadata)
                    json_response(self, 200, {"status": "ok", "run_id": run_id, "summary": asdict(summary), "out_dir": str(out_dir)})
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
    print(f"Auth enabled: {bool(expected_token())}")
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
