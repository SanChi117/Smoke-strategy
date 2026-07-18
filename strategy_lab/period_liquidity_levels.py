#!/usr/bin/env python3
"""Causal previous-day/week/month liquidity levels for SMOKE MTF V2.

PDH/PDL, PWH/PWL and PMH/PML become available only when the corresponding
calendar bar has fully closed. They are liquidity references and targets; they
never replace the H1 reaction and 5m BOS entry chain.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from strategy_lab.mtf_dealing_range_v2 import ClosedBar, Level


@dataclass(frozen=True)
class PeriodLiquiditySpec:
    timeframe: str
    high_name: str
    low_name: str
    base_strength: float


SPECS = (
    PeriodLiquiditySpec("1d", "PDH", "PDL", 65.0),
    PeriodLiquiditySpec("1w", "PWH", "PWL", 80.0),
    PeriodLiquiditySpec("1M", "PMH", "PML", 92.0),
)


def _touch_count(
    level_price: float,
    confirmed_at: datetime,
    lower_bars: Sequence[ClosedBar],
    symbol: str,
    timestamp: datetime,
) -> int:
    return sum(
        1
        for bar in lower_bars
        if bar.symbol == symbol
        and confirmed_at < bar.close_time <= timestamp
        and bar.low <= level_price <= bar.high
    )


def _level(
    period_bar: ClosedBar,
    lower_bars: Sequence[ClosedBar],
    timestamp: datetime,
    name: str,
    side: str,
    price: float,
    base_strength: float,
) -> Level:
    touches = _touch_count(price, period_bar.close_time, lower_bars, period_bar.symbol, timestamp)
    # First revisit is informative but no longer pristine; repeated revisits decay.
    decay = min(42.0, touches * 8.0)
    return Level(
        symbol=period_bar.symbol,
        timeframe=period_bar.timeframe,
        kind="period_liquidity",
        side=side,
        low=price,
        high=price,
        formed_at=period_bar.close_time,
        confirmed_at=period_bar.close_time,
        strength=round(max(0.0, base_strength - decay), 4),
        source=name,
        fresh=touches == 0,
        touches=touches,
    )


def previous_period_liquidity_levels(
    bars_by_timeframe: Mapping[str, Sequence[ClosedBar]],
    symbol: str,
    timestamp: datetime,
) -> list[Level]:
    """Return latest fully closed D/W/M highs and lows as known at timestamp."""
    normalized = symbol.upper()
    lower_bars = bars_by_timeframe.get("5m", ())
    output: list[Level] = []
    for spec in SPECS:
        completed = [
            bar
            for bar in bars_by_timeframe.get(spec.timeframe, ())
            if bar.symbol == normalized and bar.close_time <= timestamp
        ]
        if not completed:
            continue
        previous = max(completed, key=lambda bar: bar.close_time)
        output.append(
            _level(
                previous,
                lower_bars,
                timestamp,
                spec.high_name,
                "resistance",
                previous.high,
                spec.base_strength,
            )
        )
        output.append(
            _level(
                previous,
                lower_bars,
                timestamp,
                spec.low_name,
                "support",
                previous.low,
                spec.base_strength,
            )
        )
    return sorted(output, key=lambda item: (item.timeframe, item.side, item.source))
