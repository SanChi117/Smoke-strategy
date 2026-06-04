#!/usr/bin/env python3
"""Run end-to-end research flow after filtering candles by requested universe."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from strategy_lab.end_to_end_pipeline import run_end_to_end_pipeline
from strategy_lab.universe_input import write_universe_outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--out-dir", default="results/universe_end_to_end")
    parser.add_argument("--profile", default="growth_100_20x")
    parser.add_argument("--min-confidence", type=float, default=40.0)
    parser.add_argument("--min-candles", type=int, default=100)
    args = parser.parse_args()

    out = Path(args.out_dir)
    universe_dir = out / "universe_input"
    strategy_dir = out / "strategy"
    universe_summary = write_universe_outputs(
        candles_csv=args.candles,
        universe_csv=args.universe,
        out_dir=universe_dir,
        min_candles_per_symbol=args.min_candles,
    )
    if universe_summary.usable_symbols <= 0:
        print("No usable universe symbols. Strategy run skipped.")
        print(f"Universe report: {universe_dir}")
        return 1

    filtered = universe_dir / "filtered_candles.csv"
    strategy_summary = run_end_to_end_pipeline(
        candles_csv=filtered,
        out_dir=strategy_dir,
        profile=args.profile,
        min_confidence=args.min_confidence,
    )

    print("Universe-filtered end-to-end complete")
    print(f"Input candles: {args.candles}")
    print(f"Universe: {args.universe}")
    print(f"Output: {out}")
    print("--- Universe summary ---")
    for key, value in asdict(universe_summary).items():
        print(f"{key}: {value}")
    print("--- Strategy summary ---")
    for key, value in asdict(strategy_summary).items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
