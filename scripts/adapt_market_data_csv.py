#!/usr/bin/env python3
"""Normalize external OHLCV CSV into Smoke Strategy Lab candle format."""

from __future__ import annotations

import argparse
from pathlib import Path

from strategy_lab.market_data_adapter import adapt_ohlcv_csv


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="data/candles.csv")
    parser.add_argument("--report-dir", default="results/market_data_adapter")
    parser.add_argument("--default-symbol", default=None)
    parser.add_argument("--default-quote", default="USDT")
    args = parser.parse_args()

    summary = adapt_ohlcv_csv(
        input_csv=args.input,
        output_csv=args.output,
        report_dir=args.report_dir,
        default_symbol=args.default_symbol,
        default_quote=args.default_quote,
    )
    print("Market data CSV adapter complete")
    print(f"Input: {args.input}")
    print(f"Output: {Path(args.output)}")
    print(f"Report dir: {Path(args.report_dir)}")
    print(f"Input rows: {summary.input_rows}")
    print(f"Output rows: {summary.output_rows}")
    print(f"Skipped rows: {summary.skipped_rows}")
    print(f"Issues: {summary.issues}")
    print(f"Status: {summary.status}")
    return 1 if summary.output_rows <= 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
