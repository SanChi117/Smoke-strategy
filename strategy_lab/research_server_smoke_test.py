#!/usr/bin/env python3
"""Smoke test for research API server."""

from __future__ import annotations

import csv
import json
import os
import tempfile
import threading
from datetime import datetime, timedelta
from http.client import HTTPConnection
from pathlib import Path
from socket import socket

from strategy_lab.research_server import create_handler
from http.server import ThreadingHTTPServer


def free_port() -> int:
    with socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def make_candles_csv(path: Path) -> None:
    start = datetime(2025, 1, 1)
    rows: list[dict] = []
    symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"]
    for idx, symbol in enumerate(symbols):
        price = 90.0 + idx * 20.0
        for i in range(1000):
            is_impulse = i % 10 in {0, 1, 2}
            drift = 0.18 if idx < 3 else -0.02
            impulse = 0.55 if is_impulse else -0.05
            open_p = price
            close_p = max(1.0, open_p + drift + impulse)
            high = max(open_p, close_p) + 0.75
            low = min(open_p, close_p) - 0.55
            volume = 1000 + idx * 120 + (1800 if is_impulse else 0)
            rows.append({
                "symbol": symbol,
                "time": (start + timedelta(hours=i)).isoformat(timespec="seconds"),
                "open": round(open_p, 6),
                "high": round(high, 6),
                "low": round(low, 6),
                "close": round(close_p, 6),
                "volume": round(volume, 6),
            })
            price = close_p
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def request_json(port: int, method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    conn = HTTPConnection("127.0.0.1", port, timeout=20)
    payload = json.dumps(body or {}).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["X-Research-Token"] = token
    conn.request(method, path, body=payload, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    conn.close()
    return resp.status, json.loads(data)


def run_open_server_check(root: Path, candles: Path) -> None:
    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), create_handler(root))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = request_json(port, "GET", "/health")
        assert status == 200, payload
        assert payload["status"] == "ok", payload
        assert payload["mode"] == "research", payload
        assert payload["auth_enabled"] is False, payload
        assert "server_version" in payload, payload

        status, payload = request_json(port, "POST", "/run/end-to-end", {
            "candles_csv": "data/candles.csv",
            "out_dir": "results",
            "profile": "growth_100_20x",
            "min_confidence": 40,
        })
        assert status == 200, payload
        assert payload["status"] == "ok", payload
        assert payload["run_id"], payload
        run_id = payload["run_id"]
        assert payload["out_dir"].endswith(f"results/runs/{run_id}"), payload
        assert payload["summary"]["generated_trades"] > 0, payload
        assert payload["summary"]["pipeline_candidates"] == payload["summary"]["generated_trades"], payload
        assert payload["summary"]["allowed_candidates"] > 0, payload
        assert payload["summary"]["executed_trades"] > 0, payload
        assert payload["summary"]["avg_risk_pct"] > 0, payload
        assert payload["summary"]["paper_signals"] > 0, payload
        assert payload["summary"]["paper_closed"] > 0, payload
        assert payload["summary"]["sanity_status"] in {"OK", "WARN", "FAIL"}, payload
        generated_path = root / "results" / "runs" / run_id / "generated_trades.csv"
        assert generated_path.exists(), "missing generated trades for paper run"
        assert (root / "results" / "runs" / run_id / "run_metadata.json").exists(), "missing run metadata"

        status, payload = request_json(port, "POST", "/run/paper", {
            "generated_trades_csv": str(generated_path.relative_to(root)),
            "out_dir": "results",
        })
        assert status == 200, payload
        assert payload["status"] == "ok", payload
        assert payload["run_id"], payload
        paper_run_id = payload["run_id"]
        assert paper_run_id.startswith("paper-"), payload
        assert payload["summary"]["paper_signals"] > 0, payload
        assert payload["summary"]["closed_paper"] > 0, payload
        assert (root / "results" / "runs" / paper_run_id / "paper" / "paper_summary.csv").exists(), "missing standalone paper summary"
        assert (root / "results" / "runs" / paper_run_id / "paper" / "paper_decision_summary.csv").exists(), "missing standalone paper decision summary"
        assert (root / "results" / "runs" / paper_run_id / "run_metadata.json").exists(), "missing standalone paper metadata"

        status, payload = request_json(port, "GET", "/runs/list?runs_dir=results/runs&limit=5")
        assert status == 200, payload
        assert payload["status"] == "ok", payload
        assert payload["count"] >= 2, payload
        assert payload["runs"][0]["run_id"] == paper_run_id, payload
        assert payload["runs"][0]["type"] == "paper", payload
        assert payload["runs"][0]["paper_signals"] != "", payload
        assert payload["runs"][0]["paper_closed"] != "", payload

        status, payload = request_json(port, "GET", "/reports/latest?out_dir=results")
        assert status == 200, payload
        assert payload["status"] == "ok", payload
        assert payload["run_id"] == paper_run_id, payload
        assert "paper/paper_signals.csv" in payload["reports"], payload
        assert "paper/paper_journal.csv" in payload["reports"], payload
        assert "paper/paper_positions.csv" in payload["reports"], payload
        assert "paper/paper_review.csv" in payload["reports"], payload
        assert "paper/paper_review_summary.csv" in payload["reports"], payload
        assert "paper/paper_decision_summary.csv" in payload["reports"], payload
        assert "paper/paper_summary.csv" in payload["reports"], payload
        assert len(payload["reports"]["paper/paper_positions.csv"]) > 0, payload
        assert payload["reports"]["paper/paper_decision_summary.csv"][0]["decision"] in {"PASS", "WATCH", "BLOCK"}, payload

        status, payload = request_json(port, "GET", f"/reports/latest?out_dir=results&run_id={run_id}")
        assert status == 200, payload
        assert payload["run_id"] == run_id, payload
        assert "pipeline_summary.csv" in payload["reports"], payload
        assert "end_to_end_summary.csv" in payload["reports"], payload
        assert "report_sanity_summary.csv" in payload["reports"], payload
        assert "report_sanity_issues.csv" in payload["reports"], payload
        assert "candle_research_report.csv" in payload["reports"], payload
        assert "candle_exit_diagnostics.csv" in payload["reports"], payload
        assert "generated_trades.csv" in payload["reports"], payload
        assert "paper/paper_summary.csv" in payload["reports"], payload
        assert "paper/paper_decision_summary.csv" in payload["reports"], payload
        report_metrics = {row.get("metric") for row in payload["reports"]["candle_research_report.csv"]}
        assert "avg_r" in report_metrics, payload
        assert "best_setup_type" in report_metrics, payload
    finally:
        server.shutdown()
        thread.join(timeout=5)


def run_auth_server_check(root: Path) -> None:
    old_token = os.environ.get("RESEARCH_SERVER_TOKEN")
    os.environ["RESEARCH_SERVER_TOKEN"] = "test-token"
    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), create_handler(root))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, payload = request_json(port, "GET", "/health")
        assert status == 200, payload
        assert payload["auth_enabled"] is True, payload

        status, payload = request_json(port, "GET", "/runs/list?runs_dir=results/runs")
        assert status == 401, payload
        assert payload["error"] == "unauthorized", payload

        status, payload = request_json(port, "POST", "/run/paper", {"generated_trades_csv": "results/generated_trades.csv"})
        assert status == 401, payload
        assert payload["error"] == "unauthorized", payload

        status, payload = request_json(port, "GET", "/reports/latest?out_dir=results")
        assert status == 401, payload
        assert payload["error"] == "unauthorized", payload

        status, payload = request_json(port, "GET", "/reports/latest?out_dir=results", token="bad-token")
        assert status == 401, payload

        status, payload = request_json(port, "GET", "/reports/latest?out_dir=results", token="test-token")
        assert status == 200, payload
        assert payload["status"] == "ok", payload

        status, payload = request_json(port, "GET", "/runs/list?runs_dir=results/runs", token="test-token")
        assert status == 200, payload
        assert payload["status"] == "ok", payload
    finally:
        server.shutdown()
        thread.join(timeout=5)
        if old_token is None:
            os.environ.pop("RESEARCH_SERVER_TOKEN", None)
        else:
            os.environ["RESEARCH_SERVER_TOKEN"] = old_token


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        candles = root / "data" / "candles.csv"
        make_candles_csv(candles)
        run_open_server_check(root, candles)
        run_auth_server_check(root)
    print("RESEARCH SERVER SMOKE TEST OK")


if __name__ == "__main__":
    main()
