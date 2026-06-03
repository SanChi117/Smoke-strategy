#!/usr/bin/env python3
"""Run the research-only Structure Learning report."""

from __future__ import annotations

import argparse
from pathlib import Path

from strategy_lab.structure_learning import StructureLearningConfig, run_structure_learning_report


def choose_default_input() -> Path:
    real = Path("data/real_runner_trades.csv")
    sample = Path("data/sample_runner_trades.csv")
    if real.exists() and real.stat().st_size > 0:
        return real
    if sample.exists() and sample.stat().st_size > 0:
        return sample
    return real


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=None)
    parser.add_argument("--out-dir", default="results")
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--min-exact-trades", type=int, default=8)
    parser.add_argument("--min-fallback-trades", type=int, default=20)
    parser.add_argument("--take-threshold", type=float, default=64.0)
    parser.add_argument("--watch-threshold", type=float, default=52.0)
    args = parser.parse_args()

    input_csv = Path(args.input) if args.input else choose_default_input()
    if not input_csv.exists() or input_csv.stat().st_size == 0:
        raise SystemExit(
            f"Input CSV not found or empty: {input_csv}\n"
            "Create data/real_runner_trades.csv or generate data/sample_runner_trades.csv first."
        )

    cfg = StructureLearningConfig(
        lookback_days=args.lookback_days,
        min_exact_trades=args.min_exact_trades,
        min_fallback_trades=args.min_fallback_trades,
        take_threshold=args.take_threshold,
        watch_threshold=args.watch_threshold,
    )
    summary = run_structure_learning_report(input_csv=input_csv, out_dir=args.out_dir, cfg=cfg)

    print("Structure Learning report complete")
    print(f"Input: {input_csv}")
    print(f"Trades: {summary['trades']}")
    print(f"PF: {summary['pf']}")
    print(f"Winrate: {summary['winrate']}")
    print(f"Avg structure score: {summary['avg_structure_score']}")
    print(f"TAKE trades: {summary['take_trades']} | TAKE avg R: {summary['take_avg_r']} | TAKE PF: {summary['take_pf']}")
    print(f"SKIP trades: {summary['skip_trades']} | SKIP avg R: {summary['skip_avg_r']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
