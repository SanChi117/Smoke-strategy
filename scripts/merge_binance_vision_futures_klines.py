#!/usr/bin/env python3
"""CLI wrapper for official Binance Vision USD-M Futures archives."""

from __future__ import annotations

import argparse
from dataclasses import asdict

from strategy_lab.binance_vision_archive import merge_archives, read_symbols_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge Binance Vision USD-M futures kline ZIP archives")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--symbols-file", required=True)
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--start-date", required=True, help="Inclusive UTC date, YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="Inclusive UTC date, YYYY-MM-DD")
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--min-coverage", type=float, default=0.75)
    args = parser.parse_args()

    summary = merge_archives(
        input_dir=args.input_dir,
        out_csv=args.out,
        symbols=read_symbols_file(args.symbols_file),
        interval=args.interval,
        start_date=args.start_date,
        end_date=args.end_date,
        summary_json=args.summary_json,
        min_coverage=args.min_coverage,
    )
    print("Binance Vision USD-M Futures archive merge complete")
    for key, value in asdict(summary).items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
