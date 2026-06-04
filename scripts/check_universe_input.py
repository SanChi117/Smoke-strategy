#!/usr/bin/env python3
"""Validate a requested universe against an OHLCV candle CSV."""

from __future__ import annotations

import argparse
from pathlib import Path

from strategy_lab.universe_input import write_universe_outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", required=True)
    parser.add_argument("--universe", required=True)
    parser.add_argument("--out-dir", default="results/universe_input")
    parser.add_argument("--min-candles", type=int, default=100)
    parser.add_argument("--fail-on-warn", action="store_true")
    args = parser.parse_args()

    summary = write_universe_outputs(
        candles_csv=args.candles,
        universe_csv=args.universe,
        out_dir=args.out_dir,
        min_candles_per_symbol=args.min_candles,
    )
    out = Path(args.out_dir)
    print("Universe input check complete")
    print(f"Candles: {args.candles}")
    print(f"Universe: {args.universe}")
    print(f"Output: {out}")
    print(f"Requested symbols: {summary.requested_symbols}")
    print(f"Candle symbols: {summary.candle_symbols}")
    print(f"Usable symbols: {summary.usable_symbols}")
    print(f"Missing symbols: {summary.missing_symbols}")
    print(f"Under-min-history symbols: {summary.under_min_history_symbols}")
    print(f"Filtered candles: {summary.filtered_candles}")
    print(f"Status: {summary.status}")
    print(out / "universe_input_summary.csv")
    print(out / "universe_input_report.csv")
    print(out / "filtered_candles.csv")

    if summary.status == "FAIL":
        return 1
    if args.fail_on_warn and summary.status == "WARN":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
