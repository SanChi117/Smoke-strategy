#!/usr/bin/env python3
"""Generate deterministic sample runner trades for rolling selector development."""

from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime, timedelta
from pathlib import Path


def quality_for_symbol(symbol_index: int, day_index: int) -> float:
    # Deterministic changing symbol quality. Some symbols are stable, some rotate by regime.
    base = 0.35 + (symbol_index % 7) * 0.08
    regime = math.sin((day_index / 22.0) + symbol_index * 0.7) * 0.55
    cycle = math.cos((day_index / 47.0) - symbol_index * 0.3) * 0.25
    return base + regime + cycle


def make_trade(symbol: str, symbol_index: int, day_index: int, trade_index: int, start: datetime) -> dict:
    entry_time = start + timedelta(days=day_index, hours=(trade_index * 3 + symbol_index) % 20)
    exit_time = entry_time + timedelta(hours=8 + ((symbol_index + trade_index) % 24))
    side = "long" if (day_index + symbol_index + trade_index) % 2 == 0 else "short"
    q = quality_for_symbol(symbol_index, day_index)
    noise = math.sin(day_index * 1.91 + trade_index * 2.17 + symbol_index * 0.41)
    win = (q + noise * 0.38) > 0.55
    if win:
        r_mult = 1.8 + (symbol_index % 4) * 0.35 + max(0.0, q) * 0.45
    else:
        r_mult = -1.0
    entry = 100.0 + symbol_index * 3.0 + math.sin(day_index / 5.0) * 2.0
    risk = entry * (0.015 + (symbol_index % 5) * 0.002)
    if side == "long":
        stop = entry - risk
        exit_price = entry + r_mult * risk
    else:
        stop = entry + risk
        exit_price = entry - r_mult * risk
    return {
        "symbol": symbol,
        "side": side,
        "entry_time": entry_time.isoformat(timespec="seconds"),
        "exit_time": exit_time.isoformat(timespec="seconds"),
        "entry": round(entry, 6),
        "stop": round(stop, 6),
        "exit": round(exit_price, 6),
        "r_mult": round(r_mult, 6),
        "kind": "runner",
        "source": "sample_generator",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/sample_runner_trades.csv")
    parser.add_argument("--symbols", type=int, default=40)
    parser.add_argument("--days", type=int, default=520)
    parser.add_argument("--start", default="2025-01-01")
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    start = datetime.fromisoformat(args.start)
    symbols = [f"SYM{i:03d}USDT" for i in range(1, args.symbols + 1)]
    rows = []
    for day in range(args.days):
        for idx, symbol in enumerate(symbols):
            # Not every symbol trades every day. Stronger periods create more opportunities.
            q = quality_for_symbol(idx, day)
            raw = math.sin(day * 0.73 + idx * 1.37)
            if q + raw * 0.2 < 0.2:
                continue
            trades_today = 1 + (1 if q > 0.8 and day % 3 == 0 else 0)
            for ti in range(trades_today):
                rows.append(make_trade(symbol, idx, day, ti, start))

    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} trades for {len(symbols)} symbols -> {out}")


if __name__ == "__main__":
    main()
