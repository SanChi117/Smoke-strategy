#!/usr/bin/env python3
"""Run walk-forward research skeleton."""

from __future__ import annotations

import argparse
from pathlib import Path

from strategy_lab.walk_forward import run_walk_forward


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", required=True)
    parser.add_argument("--out-dir", default="results/walk_forward")
    parser.add_argument("--profile", default="growth_100_20x")
    parser.add_argument("--min-confidence", type=float, default=40.0)
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--step-days", type=int, default=15)
    parser.add_argument("--min-candles", type=int, default=100)
    args = parser.parse_args()

    rows = run_walk_forward(
        candles_csv=args.candles,
        out_dir=args.out_dir,
        profile=args.profile,
        min_confidence=args.min_confidence,
        window_days=args.window_days,
        step_days=args.step_days,
        min_candles=args.min_candles,
    )
    ok = sum(1 for row in rows if row.status == "OK")
    errors = sum(1 for row in rows if row.status != "OK")
    print("Walk-forward complete")
    print(f"Input: {args.candles}")
    print(f"Output: {Path(args.out_dir)}")
    print(f"Windows: {len(rows)}")
    print(f"OK: {ok}")
    print(f"Errors: {errors}")
    print(Path(args.out_dir) / "walk_forward_summary.csv")
    return 1 if not rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
