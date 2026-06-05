#!/usr/bin/env python3
"""Fetch public Binance Futures candles into candles.csv."""

from __future__ import annotations

import argparse
from dataclasses import asdict

from strategy_lab.binance_market_data import load_binance_futures_candles, parse_symbols


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True, help="Comma-separated symbols, e.g. BTCUSDT,ETHUSDT,SOLUSDT")
    parser.add_argument("--out", default="data/candles.csv")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--sleep-sec", type=float, default=0.05)
    args = parser.parse_args()

    symbols = parse_symbols(args.symbols)
    if not symbols:
        raise SystemExit("No symbols provided")

    summary = load_binance_futures_candles(
        symbols=symbols,
        out_csv=args.out,
        interval=args.interval,
        limit=args.limit,
        sleep_sec=args.sleep_sec,
    )
    print("Binance public candle fetch complete")
    for key, value in asdict(summary).items():
        print(f"{key}: {value}")
    return 0 if summary.status == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
