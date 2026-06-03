#!/usr/bin/env python3
"""Run the full strategy assembly research report."""

from __future__ import annotations

import argparse
from pathlib import Path

from strategy_lab.strategy_assembly import AssemblyConfig, run_strategy_assembly_report


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
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2026-05-31")
    parser.add_argument("--rolling-lookback-days", type=int, default=30)
    parser.add_argument("--rolling-rebalance-days", type=int, default=7)
    parser.add_argument("--rolling-top-n", type=int, default=5)
    parser.add_argument("--leverage", type=float, default=20.0)
    args = parser.parse_args()

    input_csv = Path(args.input) if args.input else choose_default_input()
    if not input_csv.exists() or input_csv.stat().st_size == 0:
        raise SystemExit(
            f"Input CSV not found or empty: {input_csv}\n"
            "Create data/real_runner_trades.csv or generate data/sample_runner_trades.csv first."
        )

    cfg = AssemblyConfig(
        start=args.start,
        end=args.end,
        rolling_lookback_days=args.rolling_lookback_days,
        rolling_rebalance_days=args.rolling_rebalance_days,
        rolling_top_n=args.rolling_top_n,
        leverage=args.leverage,
    )
    rows = run_strategy_assembly_report(input_csv=input_csv, out_dir=args.out_dir, cfg=cfg)

    print("Strategy assembly report complete")
    print(f"Input: {input_csv}")
    for row in rows:
        print(
            f"{row.scenario}: candidates={row.candidates} rawPF={row.raw_pf} "
            f"exec={row.exec_trades} ret={row.ret_pct}% capPF={row.capital_pf} DD={row.max_dd_pct}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
