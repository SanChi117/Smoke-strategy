#!/usr/bin/env python3
"""Download official Binance Vision USD-M Futures kline archives."""

from __future__ import annotations

import argparse
from dataclasses import asdict

from strategy_lab.binance_vision_archive import read_symbols_file
from strategy_lab.binance_vision_download import download_archives


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Binance Vision USD-M futures archives")
    parser.add_argument("--symbols-file", required=True)
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    summary = download_archives(
        symbols=read_symbols_file(args.symbols_file),
        interval=args.interval,
        start_date=args.start_date,
        end_date=args.end_date,
        out_dir=args.out_dir,
        summary_json=args.summary_json,
        workers=args.workers,
        retries=args.retries,
        timeout=args.timeout,
    )
    print("Binance Vision USD-M Futures archive download complete")
    for key, value in asdict(summary).items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
