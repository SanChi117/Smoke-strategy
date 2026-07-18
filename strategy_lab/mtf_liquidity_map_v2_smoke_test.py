#!/usr/bin/env python3
"""Smoke tests for the unified SMOKE MTF V2 liquidity map."""
from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.market_data import Candle
from strategy_lab.mtf_dealing_range_v2 import MtfDealingRangeEngine
from strategy_lab.mtf_liquidity_map_v2 import build_liquidity_map


def candles(days: int = 40) -> list[Candle]:
    start = datetime(2026, 1, 1)
    rows: list[Candle] = []
    count = days * 24 * 12
    for index in range(count):
        time = start + timedelta(minutes=5 * index)
        wave = (index % 48) / 48.0
        base = 100.0 + (index // 288) * 0.15 + wave
        rows.append(
            Candle(
                symbol="BTCUSDT",
                time=time,
                open=base,
                high=base + 0.35,
                low=base - 0.35,
                close=base + (0.08 if index % 2 == 0 else -0.05),
                volume=100.0,
            )
        )
    return rows


def test_map_contains_previous_period_levels() -> None:
    engine = MtfDealingRangeEngine(candles())
    timestamp = datetime(2026, 2, 9)
    liquidity = build_liquidity_map(engine, "BTCUSDT", timestamp)
    sources = {level.source for level in liquidity.levels}
    assert {"PDH", "PDL", "PWH", "PWL", "PMH", "PML"}.issubset(sources)
    assert all(level.confirmed_at <= timestamp for level in liquidity.levels)


def test_map_orders_nearest_target_first() -> None:
    engine = MtfDealingRangeEngine(candles())
    timestamp = datetime(2026, 2, 9)
    liquidity = build_liquidity_map(engine, "BTCUSDT", timestamp)
    price = 105.0
    above = liquidity.resistances_above(price)
    below = liquidity.supports_below(price)
    assert all(left.low <= right.low for left, right in zip(above, above[1:]))
    assert all(abs(price - left.high) <= abs(price - right.high) for left, right in zip(below, below[1:]))


def test_future_period_bar_is_invisible() -> None:
    rows = candles()
    engine = MtfDealingRangeEngine(rows)
    timestamp = datetime(2026, 2, 1)
    before = build_liquidity_map(engine, "BTCUSDT", timestamp)
    future_rows = rows + [
        Candle(
            symbol="BTCUSDT",
            time=datetime(2026, 12, 31, 23, 55),
            open=1000.0,
            high=2000.0,
            low=1.0,
            close=1500.0,
            volume=9999.0,
        )
    ]
    after = build_liquidity_map(MtfDealingRangeEngine(future_rows), "BTCUSDT", timestamp)
    signature_before = [(level.source, level.low, level.high, level.confirmed_at) for level in before.levels]
    signature_after = [(level.source, level.low, level.high, level.confirmed_at) for level in after.levels]
    assert signature_before == signature_after


def main() -> int:
    test_map_contains_previous_period_levels()
    test_map_orders_nearest_target_first()
    test_future_period_bar_is_invisible()
    print("SMOKE MTF V2 liquidity map tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
