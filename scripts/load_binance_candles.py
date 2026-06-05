#!/usr/bin/env python3
"""Load public Binance USDT-M Futures candles into project candles.csv format.

Research only. No API keys. No private account data. No order execution.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from strategy_lab.binance_market_data import load_binance_futures_candles, parse_symbols


DEFAULT_SYMBOLS = "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,LINKUSDT,AVAXUSDT,TONUSDT"


def read_symbols_file(path: str | Path) -> list[str]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Symbols file not found: {p}")
    return parse_symbols(p.read_text(encoding="utf-8"))


def resolve_symbols(symbols_arg: str | None, symbols_file: str | None) -> list[str]:
    symbols: list[str] = []
    if symbols_arg:
        symbols.extend(parse_symbols(symbols_arg))
    if symbols_file:
        symbols.extend(read_symbols_file(symbols_file))
    if not symbols:
        symbols.extend(parse_symbols(DEFAULT_SYMBOLS))
    seen: set[str] = set()
    unique: list[str] = []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            unique.append(symbol)
    return unique


def main() -> int:
    parser = argparse.ArgumentParser(description="Load public Binance Futures candles for Smoke Strategy Lab research.")
    parser.add_argument("--symbols", default=None, help="Comma/newline separated symbols, e.g. BTCUSDT,ETHUSDT,SOLUSDT")
    parser.add_argument("--symbols-file", default=None, help="Text file with comma/newline separated symbols")
    parser.add_argument("--interval", default="1h", help="Binance kline interval, e.g. 15m, 1h, 4h, 1d")
    parser.add_argument("--limit", type=int, default=1000, help="Candles per symbol. Binance public endpoint caps this at 1500.")
    parser.add_argument("--out", default="data/candles.csv", help="Output CSV path")
    parser.add_argument("--sleep-sec", type=float, default=0.05, help="Delay between symbols to be gentle with public API")
    args = parser.parse_args()

    symbols = resolve_symbols(args.symbols, args.symbols_file)
    if not symbols:
        raise SystemExit("No symbols provided.")

    print("Smoke Strategy Lab Binance candle loader")
    print("Mode: research-only public market data")
    print("API keys: not used")
    print(f"Symbols: {len(symbols)}")
    print(f"Interval: {args.interval}")
    print(f"Limit per symbol: {args.limit}")
    print(f"Output: {args.out}")

    summary = load_binance_futures_candles(
        symbols=symbols,
        out_csv=args.out,
        interval=args.interval,
        limit=args.limit,
        sleep_sec=args.sleep_sec,
    )

    print("Load complete")
    for key, value in asdict(summary).items():
        print(f"{key}: {value}")

    return 0 if summary.status == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
