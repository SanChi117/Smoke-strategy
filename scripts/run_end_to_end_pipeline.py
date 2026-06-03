#!/usr/bin/env python3
"""Run end-to-end candle-to-pipeline research flow."""

from __future__ import annotations

import argparse
from dataclasses import asdict

from strategy_lab.end_to_end_pipeline import run_end_to_end_pipeline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", required=True)
    parser.add_argument("--out-dir", default="results")
    parser.add_argument("--profile", default="growth_100_20x")
    parser.add_argument("--min-confidence", type=float, default=50.0)
    args = parser.parse_args()

    summary = run_end_to_end_pipeline(
        candles_csv=args.candles,
        out_dir=args.out_dir,
        profile=args.profile,
        min_confidence=args.min_confidence,
    )
    print("End-to-end pipeline complete")
    for key, value in asdict(summary).items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
