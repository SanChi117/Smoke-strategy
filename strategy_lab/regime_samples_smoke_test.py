#!/usr/bin/env python3
"""Smoke test for deterministic regime sample generator."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path

from strategy_lab.end_to_end_pipeline import run_end_to_end_pipeline


def count_rows(path: Path) -> int:
    with path.open("r", newline="", encoding="utf-8") as f:
        return max(0, sum(1 for _ in csv.DictReader(f)))


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        out = root / "regime_samples"
        cmd = [
            sys.executable,
            "scripts/generate_regime_samples.py",
            "--out-dir", str(out),
            "--symbols", "3",
            "--hours", "900",
        ]
        result = subprocess.run(cmd, cwd=Path.cwd(), text=True, capture_output=True, timeout=60)
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr)
        assert result.returncode == 0, result.stderr

        required = ["trend_candles.csv", "range_candles.csv", "high_vol_candles.csv", "mixed_regime_candles.csv"]
        for name in required:
            path = out / name
            assert path.exists(), f"missing regime sample: {name}"
            assert count_rows(path) > 0, f"empty regime sample: {name}"

        report_out = root / "results" / "mixed"
        summary = run_end_to_end_pipeline(out / "mixed_regime_candles.csv", report_out, profile="growth_100_20x", min_confidence=35)
        print(summary)
        assert summary.candles > 0, "expected candles"
        assert summary.features > 0, "expected features"
        assert summary.generated_trades > 0, "expected generated trades"
        assert summary.final_cash > 0, "final cash must stay positive"
        for name in ["data_quality_summary.csv", "candle_research_report.csv", "pipeline_summary.csv"]:
            path = report_out / name
            assert path.exists(), f"missing mixed regime report: {name}"
            assert count_rows(path) > 0, f"empty mixed regime report: {name}"
    print("REGIME SAMPLES SMOKE TEST OK")


if __name__ == "__main__":
    main()
