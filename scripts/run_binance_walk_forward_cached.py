#!/usr/bin/env python3
"""Run strict-OOS walk-forward using an already downloaded candles CSV.

The source path is provided through SMOKE_WFO_CANDLES_SOURCE. This avoids
re-downloading identical public market data for every strategy candidate.
"""

from __future__ import annotations

import csv
import os
import shutil
from pathlib import Path

import run_binance_walk_forward_v2 as strict
from strategy_lab.binance_market_data import MarketDataSummary


def cached_loader(
    symbols: list[str],
    out_csv: str | Path,
    interval: str = "1h",
    limit: int = 500,
    **_kwargs,
) -> MarketDataSummary:
    source = Path(os.environ.get("SMOKE_WFO_CANDLES_SOURCE", "")).expanduser()
    if not source.exists() or source.stat().st_size == 0:
        raise RuntimeError("SMOKE_WFO_CANDLES_SOURCE is missing or empty")
    destination = Path(out_csv)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copyfile(source, destination)

    loaded_symbols: set[str] = set()
    candles = 0
    with destination.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            symbol = str(row.get("symbol", "")).strip().upper()
            if symbol:
                loaded_symbols.add(symbol)
            candles += 1
    return MarketDataSummary(
        symbols_requested=len(symbols),
        symbols_loaded=len(loaded_symbols),
        candles=candles,
        interval=interval,
        status="OK" if candles > 0 else "EMPTY",
    )


def main() -> int:
    strict.base.load_binance_futures_candles = cached_loader
    return strict.main()


if __name__ == "__main__":
    raise SystemExit(main())
