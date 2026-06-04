#!/usr/bin/env python3
"""Smoke test for walk-forward research skeleton."""

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
        candles = root / "mixed_regime_candles.csv"
        rows = generate_trend(2, 900) + generate_range(2, 900) + generate_high_vol(2, 900)
        write_csv(candles, rows)
        out = root / "walk_forward"
        cmd = [
            sys.executable,
            "scripts/run_walk_forward.py",
            "--candles", str(candles),
            "--out-dir", str(out),
            "--window-days", "20",
            "--step-days", "10",
            "--min-candles", "100",
            "--min-confidence", "30",
        ]
        result = subprocess.run(cmd, cwd=Path.cwd(), text=True, capture_output=True, timeout=120)
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr)
        assert result.returncode == 0, result.stderr
        windows_path = out / "walk_forward_windows.csv"
        summary_path = out / "walk_forward_summary.csv"
        report_path = out / "walk_forward_report.csv"
        assert windows_path.exists(), "missing walk_forward_windows.csv"
        assert summary_path.exists(), "missing walk_forward_summary.csv"
        assert report_path.exists(), "missing walk_forward_report.csv"
        windows = read_rows(windows_path)
        summary = read_rows(summary_path)
        report = read_rows(report_path)
        assert len(windows) > 0, "expected at least one WFO window"
        assert len(summary) == len(windows), "summary rows must match windows"
        assert any(row["status"] == "OK" for row in summary), summary
        for row in summary:
            assert int(float(row["candles"])) > 0, row
            assert int(float(row["symbols"])) > 0, row
            assert row["reports_dir"], row
        metrics = {row["metric"] for row in report}
        for metric in ["windows_total", "windows_ok", "profitable_windows", "avg_ret_pct", "avg_max_dd_pct", "stability_score", "stability_status"]:
            assert metric in metrics, f"missing WFO report metric: {metric}"
    print("WALK-FORWARD SMOKE TEST OK")


if __name__ == "__main__":
    main()
