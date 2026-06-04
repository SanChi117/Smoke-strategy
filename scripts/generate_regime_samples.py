#!/usr/bin/env python3
"""Generate deterministic OHLCV samples for distinct market regimes.

Outputs:
- trend_candles.csv
- range_candles.csv
- high_vol_candles.csv
- mixed_regime_candles.csv

Research only. Synthetic data. No exchange calls.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
from pathlib import Path


def candle_row(symbol: str, t, open_p: float, close_p: float, wick: float, volume: float) -> dict:
    high = max(open_p, close_p) + wick
    low = max(0.01, min(open_p, close_p) - wick)
    return {
        "symbol": symbol,
        "time": t.isoformat(timespec="seconds"),
        "open": round(open_p, 6),
        "high": round(high, 6),
        "low": round(low, 6),
        "close": round(close_p, 6),
        "volume": round(volume, 6),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "time", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)


def generate_trend(symbols: int, hours: int) -> list[dict]:
    start = datetime(2025, 1, 1)
    rows: list[dict] = []
    for idx in range(symbols):
        symbol = f"TREND{idx + 1:03d}USDT"
        price = 80.0 + idx * 15.0
        for i in range(hours):
            is_impulse = i % 12 in {0, 1, 2}
            is_pullback = i % 12 in {7, 8}
            drift = 0.13 + idx * 0.01
            impulse = 0.58 if is_impulse else -0.12 if is_pullback else 0.03
            open_p = price
            close_p = max(1.0, open_p + drift + impulse)
            volume = 1200 + idx * 100 + (2100 if is_impulse else 250 if is_pullback else 0)
            rows.append(candle_row(symbol, start + timedelta(hours=i), open_p, close_p, 0.65, volume))
            price = close_p
    return rows


def generate_range(symbols: int, hours: int) -> list[dict]:
    start = datetime(2025, 1, 1)
    rows: list[dict] = []
    for idx in range(symbols):
        symbol = f"RANGE{idx + 1:03d}USDT"
        center = 100.0 + idx * 12.0
        price = center
        for i in range(hours):
            phase = i % 24
            if phase < 6:
                move = -0.22
            elif phase < 12:
                move = 0.24
            elif phase < 18:
                move = 0.18
            else:
                move = -0.20
            # Pull price back toward center so it remains range-bound.
            mean_revert = (center - price) * 0.045
            open_p = price
            close_p = max(1.0, open_p + move + mean_revert)
            near_edge = phase in {5, 6, 17, 18}
            volume = 1000 + idx * 80 + (850 if near_edge else 0)
            rows.append(candle_row(symbol, start + timedelta(hours=i), open_p, close_p, 0.75 if near_edge else 0.45, volume))
            price = close_p
    return rows


def generate_high_vol(symbols: int, hours: int) -> list[dict]:
    start = datetime(2025, 1, 1)
    rows: list[dict] = []
    for idx in range(symbols):
        symbol = f"HVOL{idx + 1:03d}USDT"
        price = 90.0 + idx * 20.0
        for i in range(hours):
            shock = 1.45 if i % 15 in {0, 1} else -1.10 if i % 15 in {7, 8} else 0.08
            drift = 0.03 if idx % 2 == 0 else -0.02
            open_p = price
            close_p = max(1.0, open_p + drift + shock)
            volume = 1400 + idx * 120 + (3200 if abs(shock) > 1 else 400)
            rows.append(candle_row(symbol, start + timedelta(hours=i), open_p, close_p, 1.55, volume))
            price = close_p
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="data/regime_samples")
    parser.add_argument("--symbols", type=int, default=4)
    parser.add_argument("--hours", type=int, default=1200)
    args = parser.parse_args()

    out = Path(args.out_dir)
    trend = generate_trend(args.symbols, args.hours)
    range_rows = generate_range(args.symbols, args.hours)
    high_vol = generate_high_vol(args.symbols, args.hours)
    mixed = trend + range_rows + high_vol

    write_csv(out / "trend_candles.csv", trend)
    write_csv(out / "range_candles.csv", range_rows)
    write_csv(out / "high_vol_candles.csv", high_vol)
    write_csv(out / "mixed_regime_candles.csv", mixed)

    print("Regime sample candles generated")
    print(f"Output: {out}")
    print(f"trend rows: {len(trend)}")
    print(f"range rows: {len(range_rows)}")
    print(f"high-vol rows: {len(high_vol)}")
    print(f"mixed rows: {len(mixed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
