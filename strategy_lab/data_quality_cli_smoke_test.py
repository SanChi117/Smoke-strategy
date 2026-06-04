#!/usr/bin/env python3
"""Smoke test for standalone candle quality checker CLI."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


def make_candles_csv(path: Path) -> None:
    start = datetime(2025, 1, 1)
    rows: list[dict] = []
    for symbol in ["AAAUSDT", "BBBUSDT"]:
        price = 100.0
        for i in range(120):
            open_p = price
            close_p = open_p + 0.1
            high = max(open_p, close_p) + 0.5
            low = min(open_p, close_p) - 0.5
            rows.append({
                "symbol": symbol,
                "time": (start + timedelta(hours=i)).isoformat(timespec="seconds"),
                "open": round(open_p, 6),
                "high": round(high, 6),
                "low": round(low, 6),
                "close": round(close_p, 6),
                "volume": 1000,
            })
            price = close_p
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        candles = root / "data" / "candles.csv"
        out = root / "quality"
        make_candles_csv(candles)
        cmd = [
            sys.executable,
            "scripts/check_candles_quality.py",
            "--candles", str(candles),
            "--out-dir", str(out),
            "--min-candles", "100",
            "--min-symbols", "2",
        ]
        result = subprocess.run(cmd, cwd=Path.cwd(), text=True, capture_output=True, timeout=30)
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr)
        assert result.returncode == 0, result.stderr
        for name in ["data_quality_summary.csv", "data_quality_report.csv", "data_quality_issues.csv"]:
            path = out / name
            assert path.exists(), f"missing data quality output: {name}"
        summary = read_rows(out / "data_quality_summary.csv")[0]
        assert summary["status"] == "OK", summary
        assert summary["errors"] == "0", summary
        assert summary["symbols"] == "2", summary
        report = read_rows(out / "data_quality_report.csv")
        assert len(report) == 2, report
    print("DATA QUALITY CLI SMOKE TEST OK")


if __name__ == "__main__":
    main()
