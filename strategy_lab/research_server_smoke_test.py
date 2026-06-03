#!/usr/bin/env python3
"""Smoke test for research API server."""

from __future__ import annotations

import csv
import json
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
        # More than 30 days of hourly candles so the server end-to-end test
        # gives rolling selector enough lookback after feature/setup generation.
        for i in range(1000):
            is_impulse = i % 10 in {0, 1, 2}
            drift = 0.18 if idx < 3 else -0.02
            impulse = 0.55 if is_impulse else -0.05
            open_p = price
            close_p = max(1.0, open_p + drift + impulse)
            high = max(open_p, close_p) + 0.75
            low = min(open_p, close_p) - 0.55
            # Strong synthetic volume surge. The feature builder requires
            # volume_ratio >= 1.25/1.8 for actionable continuation setups.
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


def request_json(port: int, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    conn = HTTPConnection("127.0.0.1", port, timeout=20)
    payload = json.dumps(body or {}).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    conn.request(method, path, body=payload, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    conn.close()
    return resp.status, json.loads(data)


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        candles = root / "data" / "candles.csv"
        make_candles_csv(candles)

        port = free_port()
        server = ThreadingHTTPServer(("127.0.0.1", port), create_handler(root))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            status, payload = request_json(port, "GET", "/health")
            assert status == 200, payload
            assert payload["status"] == "ok", payload
            assert payload["mode"] == "research", payload

            status, payload = request_json(port, "POST", "/run/end-to-end", {
                "candles_csv": "data/candles.csv",
                "out_dir": "results",
                "profile": "growth_100_20x",
                "min_confidence": 40,
            })
            assert status == 200, payload
            assert payload["status"] == "ok", payload
            assert payload["summary"]["generated_trades"] > 0, payload
            assert payload["summary"]["pipeline_candidates"] == payload["summary"]["generated_trades"], payload
            assert payload["summary"]["allowed_candidates"] > 0, payload
            assert payload["summary"]["executed_trades"] > 0, payload
            assert payload["summary"]["avg_risk_pct"] > 0, payload

            status, payload = request_json(port, "GET", "/reports/latest?out_dir=results")
            assert status == 200, payload
            assert payload["status"] == "ok", payload
            assert "pipeline_summary.csv" in payload["reports"], payload
            assert "end_to_end_summary.csv" in payload["reports"], payload
        finally:
            server.shutdown()
            thread.join(timeout=5)
    print("RESEARCH SERVER SMOKE TEST OK")


if __name__ == "__main__":
    main()
