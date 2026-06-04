#!/usr/bin/env python3
"""Run walk-forward parameter grid skeleton."""

from __future__ import annotations

import argparse
from pathlib import Path

from strategy_lab.parameter_grid import run_parameter_grid


def parse_values(raw: str) -> list[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", required=True)
    parser.add_argument("--out-dir", default="results/parameter_grid")
    parser.add_argument("--profile", default="growth_100_20x")
    parser.add_argument("--min-confidence-values", default="30,40,50")
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--step-days", type=int, default=15)
    parser.add_argument("--min-candles", type=int, default=100)
    args = parser.parse_args()

    rows = run_parameter_grid(
        candles_csv=args.candles,
        out_dir=args.out_dir,
        profile=args.profile,
        min_confidence_values=parse_values(args.min_confidence_values),
        window_days=args.window_days,
        step_days=args.step_days,
        min_candles=args.min_candles,
    )
    print("Parameter grid complete")
    print(f"Input: {args.candles}")
    print(f"Output: {Path(args.out_dir)}")
    print(f"Rows: {len(rows)}")
    print(Path(args.out_dir) / "parameter_grid_summary.csv")
    print(Path(args.out_dir) / "parameter_grid_report.csv")
    return 1 if not rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
