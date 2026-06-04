#!/usr/bin/env python3
"""Smoke test for universe input checker."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def make_candles(path: Path) -> None:
    start = datetime(2025, 1, 1)
    rows: list[dict] = []
    for symbol in ["AAAUSDT", "BBBUSDT", "CCCUSDT"]:
        price = 100.0
        for i in range(120):
            rows.append({
                "symbol": symbol,
                "time": (start + timedelta(hours=i)).isoformat(timespec="seconds"),
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price + 0.1,
                "volume": 1000,
            })
            price += 0.1
    write_csv(path, rows)


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        candles = root / "candles.csv"
        universe = root / "universe.csv"
        out = root / "out"
        make_candles(candles)
        write_csv(universe, [{"symbol": "AAAUSDT"}, {"symbol": "BBBUSDT"}, {"symbol": "MISSINGUSDT"}])
        cmd = [
            sys.executable,
            "scripts/check_universe_input.py",
            "--candles", str(candles),
            "--universe", str(universe),
            "--out-dir", str(out),
            "--min-candles", "100",
        ]
        result = subprocess.run(cmd, cwd=Path.cwd(), text=True, capture_output=True, timeout=30)
        print(result.stdout)
        assert result.returncode == 0, result.stderr
        summary = read_rows(out / "universe_input_summary.csv")[0]
        report = read_rows(out / "universe_input_report.csv")
        filtered = read_rows(out / "filtered_candles.csv")
        assert summary["status"] == "WARN", summary
        assert summary["usable_symbols"] == "2", summary
        assert summary["missing_symbols"] == "1", summary
        assert len(report) == 4, report
        assert len(filtered) == 240, len(filtered)
    print("UNIVERSE INPUT SMOKE TEST OK")


if __name__ == "__main__":
    main()
