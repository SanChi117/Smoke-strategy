#!/usr/bin/env python3
"""Run paper mode from generated_trades.csv."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from strategy_lab.paper_mode import run_paper_mode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated-trades", default="results/generated_trades.csv")
    parser.add_argument("--out-dir", default="results/paper")
    args = parser.parse_args()

    summary = run_paper_mode(args.generated_trades, args.out_dir)
    print("Paper mode complete")
    print(f"Input: {args.generated_trades}")
    print(f"Output: {Path(args.out_dir)}")
    for key, value in asdict(summary).items():
        print(f"{key}: {value}")
    return 1 if summary.status == "EMPTY" else 0


if __name__ == "__main__":
    raise SystemExit(main())
