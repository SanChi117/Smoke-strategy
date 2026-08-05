#!/usr/bin/env python3
"""Fresh-fractal H1 liquidity raid recognition for SMOKE MTF V2."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from strategy_lab.mtf_dealing_range_v2 import ClosedBar, Pivot, confirmed_pivots


@dataclass(frozen=True)
class RaidSignal:
    symbol: str
    side: str
    pivot: Pivot
    raid_bar: ClosedBar
    fresh: bool
    strength: float


def _crossed_reference(bar: ClosedBar, pivot: Pivot) -> bool:
    if pivot.kind == "low":
        return bar.low <= pivot.price
    return bar.high >= pivot.price


def _is_raid(bar: ClosedBar, pivot: Pivot, side: str) -> bool:
    if side == "long":
        return pivot.kind == "low" and bar.low < pivot.price and bar.close > pivot.price
    return pivot.kind == "high" and bar.high > pivot.price and bar.close < pivot.price


def detect_h1_raid_signal(
    bars: Sequence[ClosedBar],
    side: str,
    timestamp: datetime,
    lookback_bars: int = 4,
) -> RaidSignal | None:
    """Return a closed raid of a fresh confirmed H1 fractal.

    Fresh means no completed bar touched or crossed that fractal between pivot
    confirmation and the raid candle. The raid itself must sweep by wick and
    close back on the original side.
    """
    normalized_side = side.lower()
    if normalized_side not in {"long", "short"}:
        raise ValueError("side must be long or short")
    rows = sorted((bar for bar in bars if bar.close_time <= timestamp), key=lambda bar: bar.close_time)
    if len(rows) < 6:
        return None
    desired = "low" if normalized_side == "long" else "high"
    pivots = [pivot for pivot in confirmed_pivots(rows, 2, 2) if pivot.kind == desired]
    if not pivots:
        return None

    recent_raid_bars = rows[-lookback_bars:]
    for raid_bar in reversed(recent_raid_bars):
        candidates = [
            pivot
            for pivot in pivots
            if pivot.confirmed_at <= raid_bar.open_time and _is_raid(raid_bar, pivot, normalized_side)
        ]
        for pivot in reversed(candidates):
            prior = [
                bar
                for bar in rows
                if pivot.confirmed_at < bar.close_time <= raid_bar.open_time
            ]
            fresh = not any(_crossed_reference(bar, pivot) for bar in prior)
            if not fresh:
                continue
            full_range = max(1e-12, raid_bar.high - raid_bar.low)
            reclaim = (
                (raid_bar.close - raid_bar.low) / full_range
                if normalized_side == "long"
                else (raid_bar.high - raid_bar.close) / full_range
            )
            sweep = (
                (pivot.price - raid_bar.low) / max(abs(pivot.price), 1e-12)
                if normalized_side == "long"
                else (raid_bar.high - pivot.price) / max(abs(pivot.price), 1e-12)
            )
            strength = min(100.0, pivot.strength * 0.60 + reclaim * 25.0 + min(15.0, sweep * 10000.0))
            return RaidSignal(
                symbol=raid_bar.symbol,
                side=normalized_side,
                pivot=pivot,
                raid_bar=raid_bar,
                fresh=True,
                strength=round(strength, 4),
            )
    return None
