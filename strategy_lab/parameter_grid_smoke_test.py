#!/usr/bin/env python3
"""Smoke test for parameter grid runner."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.generate_regime_samples import generate_high_vol, generate_range, generate_trend, write_csv


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        candles = root / "candles.csv"
        rows = generate_trend(2, 720) + generate_range(2, 720) + generate_high_vol(2, 720)
        write_csv(candles, rows)
        out = root / "grid"
        cmd = [
            sys.executable,
            "scripts/run_parameter_grid.py",
            "--candles", str(candles),
            "--out-dir", str(out),
            "--min-confidence-values", "30,40",
            "--window-days", "20",
            "--step-days", "10",
            "--min-candles", "100",
        ]
        result = subprocess.run(cmd, cwd=Path.cwd(), text=True, capture_output=True, timeout=180)
        print(result.stdout)
        assert result.returncode == 0, result.stderr
        summary = read_rows(out / "parameter_grid_summary.csv")
        report = read_rows(out / "parameter_grid_report.csv")
        assert len(summary) == 2, summary
        assert {row["param_value"] for row in summary} == {"30.0", "40.0"}, summary
        assert {row["metric"] for row in report} >= {"grid_rows", "best_param_value", "best_stability_score"}, report
    print("PARAMETER GRID SMOKE TEST OK")


if __name__ == "__main__":
    main()
