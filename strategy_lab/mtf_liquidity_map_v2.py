#!/usr/bin/env python3
"""Unified causal liquidity map for SMOKE MTF V2."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from strategy_lab.mtf_dealing_range_v2 import (
    Level,
    MtfDealingRangeEngine,
    confirmed_pivots,
    imbalance_levels,
    pivot_levels,
)
from strategy_lab.period_liquidity_levels import previous_period_liquidity_levels


@dataclass(frozen=True)
class LiquidityMap:
    symbol: str
    timestamp: datetime
    levels: tuple[Level, ...]

    def supports_below(self, price: float) -> tuple[Level, ...]:
        rows = [level for level in self.levels if level.side == "support" and level.high < price]
        return tuple(sorted(rows, key=lambda level: (price - level.high, -level.strength)))

    def resistances_above(self, price: float) -> tuple[Level, ...]:
        rows = [level for level in self.levels if level.side == "resistance" and level.low > price]
        return tuple(sorted(rows, key=lambda level: (level.low - price, -level.strength)))

    def nearby(self, price: float, distance: float, side: str | None = None) -> tuple[Level, ...]:
        rows: list[Level] = []
        for level in self.levels:
            if side is not None and level.side != side:
                continue
            gap = 0.0 if level.low <= price <= level.high else min(abs(price - level.low), abs(price - level.high))
            if gap <= distance:
                rows.append(level)
        return tuple(sorted(rows, key=lambda level: (-level.strength, level.confirmed_at)))


def build_liquidity_map(
    engine: MtfDealingRangeEngine,
    symbol: str,
    timestamp: datetime,
    structural_timeframes: tuple[str, ...] = ("1h", "4h", "1d", "1w", "1M"),
) -> LiquidityMap:
    normalized = symbol.upper()
    levels: list[Level] = []
    for timeframe in structural_timeframes:
        bars = [
            bar
            for bar in engine.bars.get(timeframe, ())
            if bar.symbol == normalized and bar.close_time <= timestamp
        ]
        levels.extend(pivot_levels(confirmed_pivots(bars, 2, 2), timestamp))
        levels.extend(imbalance_levels(bars, timestamp))
    levels.extend(previous_period_liquidity_levels(engine.bars, normalized, timestamp))

    unique: dict[tuple[object, ...], Level] = {}
    for level in levels:
        if level.confirmed_at > timestamp:
            continue
        key = (
            level.timeframe,
            level.kind,
            level.side,
            round(level.low, 12),
            round(level.high, 12),
            level.confirmed_at,
        )
        current = unique.get(key)
        if current is None or level.strength > current.strength:
            unique[key] = level
    ordered = sorted(unique.values(), key=lambda level: (level.low, level.high, -level.strength, level.source))
    return LiquidityMap(normalized, timestamp, tuple(ordered))
