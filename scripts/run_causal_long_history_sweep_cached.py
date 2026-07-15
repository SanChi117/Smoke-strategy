#!/usr/bin/env python3
"""Run the long causal WFO from a prebuilt Binance Futures candle CSV."""

from __future__ import annotations

import csv
import os
import shutil
from pathlib import Path

import run_causal_long_history_sweep as long_sweep
from strategy_lab.binance_market_data import MarketDataSummary


def archive_loader(
    symbols: list[str],
    out_csv: str | Path,
    interval: str = "15m",
    **_kwargs,
) -> MarketDataSummary:
    source = Path(os.environ.get("SMOKE_LONG_CANDLES_SOURCE", "")).expanduser()
    if not source.exists() or source.stat().st_size == 0:
        raise RuntimeError("SMOKE_LONG_CANDLES_SOURCE is missing or empty")
    destination = Path(out_csv)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copyfile(source, destination)

    loaded: set[str] = set()
    rows = 0
    with destination.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"symbol", "time", "open", "high", "low", "close", "volume"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError("Cached futures candles missing columns: " + ", ".join(sorted(missing)))
        for row in reader:
            symbol = str(row.get("symbol", "")).strip().upper()
            if symbol:
                loaded.add(symbol)
            rows += 1
    return MarketDataSummary(
        symbols_requested=len(symbols),
        symbols_loaded=len(loaded),
        candles=rows,
        interval=interval,
        status="OK" if rows else "EMPTY",
    )


def main() -> int:
    long_sweep.load_binance_futures_candles = archive_loader
    return long_sweep.main()


if __name__ == "__main__":
    raise SystemExit(main())
