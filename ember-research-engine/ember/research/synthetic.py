"""Deterministic synthetic candles for sanity checks, not profitability claims."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import polars as pl


def trending_synthetic_data(
    bars: int = 1000,
    symbol: str = "DOGEUSDT",
    start_price: float = 500.0,
    start_time: datetime | None = None,
) -> pl.DataFrame:
    """Create a bearish trend with repeatable pullbacks and continuations."""

    if bars < 100:
        raise ValueError("bars must be at least 100")
    start_time = start_time or datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = start_price
    rows: list[dict[str, object]] = []
    for index in range(bars):
        phase = index % 20
        open_price = price
        if phase <= 7:
            change = -0.007
            volume = 1100.0
        elif phase <= 11:
            change = 0.012
            volume = 900.0
        elif phase == 12:
            change = -0.004
            volume = 1800.0
        else:
            change = -0.009
            volume = 1300.0
        close_price = max(5.0, open_price * (1.0 + change))
        if phase == 12:
            high = open_price * 1.012
            low = close_price * 0.994
        else:
            high = max(open_price, close_price) * 1.003
            low = min(open_price, close_price) * 0.997
        rows.append(
            {
                "symbol": symbol,
                "time": start_time + timedelta(minutes=15 * index),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close_price,
                "volume": volume,
            }
        )
        price = close_price
    return pl.DataFrame(rows)
