#!/usr/bin/env python3
"""Run the integrated Smoke Strategy research pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path

from strategy_lab.pipeline import run_pipeline


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
    parser.add_argument("--profile", default="growth_100_20x")
    args = parser.parse_args()

    input_csv = Path(args.input) if args.input else choose_default_input()
    if not input_csv.exists() or input_csv.stat().st_size == 0:
        raise SystemExit(
            f"Input CSV not found or empty: {input_csv}\n"
            "Create data/real_runner_trades.csv or generate data/sample_runner_trades.csv first."
        )

    summary = run_pipeline(input_csv=input_csv, out_dir=args.out_dir, profile_name=args.profile)
    print("Smoke pipeline complete")
    print(f"Input: {input_csv}")
    print(f"Profile: {summary.profile}")
    print(f"Initial cash: {summary.initial_cash}")
    print(f"Leverage: {summary.leverage}")
    print(f"Base risk pct: {summary.base_risk_pct}")
    print(f"Max risk pct: {summary.max_risk_pct}")
    print(f"Candidates: {summary.candidates}")
    print(f"Allowed candidates: {summary.allowed_candidates}")
    print(f"Executed trades: {summary.executed_trades}")
    print(f"Final cash: {summary.final_cash}")
    print(f"Return: {summary.ret_pct}%")
    print(f"DD: {summary.max_dd_pct}%")
    print(f"PF: {summary.pf}")
    print(f"Winrate: {summary.winrate}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
