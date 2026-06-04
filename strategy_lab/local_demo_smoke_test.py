#!/usr/bin/env python3
"""Smoke test for one-command local demo script."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path


def count_rows(path: Path) -> int:
    with path.open("r", newline="", encoding="utf-8") as f:
        return max(0, sum(1 for _ in csv.DictReader(f)))


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        candles = root / "data" / "demo_candles.csv"
        out = root / "results" / "demo"
        cmd = [
            sys.executable,
            "scripts/run_local_demo.py",
            "--candles", str(candles),
            "--out-dir", str(out),
            "--symbols", "4",
            "--hours", "1000",
            "--min-confidence", "40",
        ]
        result = subprocess.run(cmd, cwd=Path.cwd(), text=True, capture_output=True, timeout=60)
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr)
        assert result.returncode == 0, result.stderr
        assert candles.exists(), "demo candles were not created"
        required = [
            "end_to_end_summary.csv",
            "candle_research_report.csv",
            "candle_exit_diagnostics.csv",
            "generated_trades.csv",
            "pipeline_summary.csv",
            "pipeline_risk_diagnostics.csv",
        ]
        for name in required:
            path = out / name
            assert path.exists(), f"missing demo report: {name}"
            assert count_rows(path) > 0, f"empty demo report: {name}"
    print("LOCAL DEMO SMOKE TEST OK")


if __name__ == "__main__":
    main()
