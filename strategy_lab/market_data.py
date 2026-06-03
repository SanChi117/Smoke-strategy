#!/usr/bin/env python3
"""Market data schemas and CSV helpers for Smoke Strategy Lab.

This is the data layer for the future executable strategy pipeline.
Research only. No exchange API calls. No live trading.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Candle:
    symbol: str
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def parse_dt(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    txt = str(value).strip().replace("Z", "")
    return datetime.fromisoformat(txt)


def read_candles_csv(path: str | Path) -> list[Candle]:
    candles: list[Candle] = []
    with Path(path).open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"symbol", "time", "open", "high", "low", "close", "volume"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required candle columns: {sorted(missing)}")
        for row in reader:
            candles.append(Candle(
                symbol=str(row["symbol"]).strip().upper(),
                time=parse_dt(row["time"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            ))
    return sorted(candles, key=lambda c: (c.symbol, c.time))


def write_candles_csv(path: str | Path, candles: Iterable[Candle]) -> None:
    rows = [asdict(c) for c in candles]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    for row in rows:
        row["time"] = row["time"].isoformat(timespec="seconds")
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def group_candles_by_symbol(candles: Iterable[Candle]) -> dict[str, list[Candle]]:
    out: dict[str, list[Candle]] = {}
    for candle in sorted(candles, key=lambda c: (c.symbol, c.time)):
        out.setdefault(candle.symbol, []).append(candle)
    return out


def validate_candles(candles: Iterable[Candle]) -> None:
    for candle in candles:
        if candle.open <= 0 or candle.high <= 0 or candle.low <= 0 or candle.close <= 0:
            raise ValueError(f"Invalid non-positive OHLC value: {candle}")
        if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close):
            raise ValueError(f"Invalid OHLC relationship: {candle}")
        if candle.volume < 0:
            raise ValueError(f"Invalid negative volume: {candle}")
