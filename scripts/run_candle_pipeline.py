#!/usr/bin/env python3
"""Run candle-to-trades research pipeline."""

from __future__ import annotations

import argparse

from strategy_lab.candle_pipeline import run_candle_pipeline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", required=True)
    parser.add_argument("--out-dir", default="results")
    parser.add_argument("--min-confidence", type=float, default=50.0)
    args = parser.parse_args()

    summary = run_candle_pipeline(args.candles, args.out_dir, min_confidence=args.min_confidence)
    print("Candle pipeline complete")
    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
