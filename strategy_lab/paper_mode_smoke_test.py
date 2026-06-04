#!/usr/bin/env python3
"""Smoke test for paper mode skeleton."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path


def write_trades(path: Path) -> None:
    rows = [
        {"symbol": "AAAUSDT", "side": "long", "entry_time": "2025-01-01T00:00:00", "entry": 100, "stop": 98, "target": 104, "setup_type": "breakout", "risk_grade": "A", "target_policy": "rr"},
        {"symbol": "BBBUSDT", "side": "long", "entry_time": "2025-01-01T01:00:00", "entry": 80, "stop": 78, "target": 84, "setup_type": "pullback", "risk_grade": "B", "target_policy": "rr"},
    ]
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
        trades = root / "generated_trades.csv"
        out = root / "paper"
        write_trades(trades)
        cmd = [sys.executable, "scripts/run_paper_mode.py", "--generated-trades", str(trades), "--out-dir", str(out)]
        result = subprocess.run(cmd, cwd=Path.cwd(), text=True, capture_output=True, timeout=30)
        print(result.stdout)
        assert result.returncode == 0, result.stderr
        signals = read_rows(out / "paper_signals.csv")
        summary = read_rows(out / "paper_summary.csv")[0]
        assert len(signals) == 2, signals
        assert signals[0]["status"] == "OPEN_SIGNAL", signals
        assert summary["paper_signals"] == "2", summary
        assert summary["status"] == "OK", summary
    print("PAPER MODE SMOKE TEST OK")


if __name__ == "__main__":
    main()
