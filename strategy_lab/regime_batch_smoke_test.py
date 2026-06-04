#!/usr/bin/env python3
"""Smoke test for batch regime runner."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sample_dir = root / "samples"
        reports_dir = root / "reports"
        cmd = [
            sys.executable,
            "scripts/run_regime_batch.py",
            "--sample-dir", str(sample_dir),
            "--reports-dir", str(reports_dir),
            "--symbols", "3",
            "--hours", "900",
            "--min-confidence", "35",
        ]
        result = subprocess.run(cmd, cwd=Path.cwd(), text=True, capture_output=True, timeout=120)
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr)
        assert result.returncode == 0, result.stderr

        summary_path = reports_dir / "regime_batch_summary.csv"
        assert summary_path.exists(), "missing regime batch summary"
        rows = read_rows(summary_path)
        assert len(rows) == 4, rows
        regimes = {row["regime"] for row in rows}
        assert regimes == {"trend", "range", "high_vol", "mixed"}, regimes
        for row in rows:
            assert int(float(row["candles"])) > 0, row
            assert int(float(row["features"])) > 0, row
            assert int(float(row["generated_trades"])) > 0, row
            assert float(row["final_cash"]) > 0, row
            assert row["candle_avg_r"] != "missing", row
            assert row["best_setup_type"] != "missing", row
            regime_dir = reports_dir / row["regime"]
            for name in ["data_quality_summary.csv", "candle_research_report.csv", "pipeline_summary.csv"]:
                assert (regime_dir / name).exists(), f"missing {name} for {row['regime']}"
    print("REGIME BATCH SMOKE TEST OK")


if __name__ == "__main__":
    main()
