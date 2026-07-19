#!/usr/bin/env python3
"""Timeframe-matched FTA/target selection for SMOKE MTF V2."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from strategy_lab.mtf_dealing_range_v2 import Level, MtfContextSnapshot, MtfDealingRangeEngine
from strategy_lab.mtf_liquidity_map_v2 import build_liquidity_map
from strategy_lab.mtf_raid_signal_v2 import RaidSignal


@dataclass(frozen=True)
class TargetSelection:
    symbol: str
    side: str
    price: float
    timeframe: str
    source: str
    strength: float


def preferred_target_timeframe(poi: Level | None, raid: RaidSignal | None) -> str | None:
    """Map the entry model to the timeframe whose FTA must be respected."""
    if raid is not None:
        return raid.pivot.timeframe
    if poi is None:
        return None
    if poi.timeframe in {"1h", "4h", "1d"}:
        return poi.timeframe
    # Weekly/monthly context still executes intraday; Daily is the highest
    # tradable target map for that route rather than an unbounded W/M objective.
    if poi.timeframe in {"1w", "1M"}:
        return "1d"
    return "4h"


def directional_target_levels(
    levels: Iterable[Level],
    side: str,
    entry: float,
    timeframe: str,
) -> list[Level]:
    normalized_side = side.lower()
    rows: list[Level] = []
    for level in levels:
        if level.timeframe != timeframe:
            continue
        if normalized_side == "long" and level.side == "resistance" and level.low > entry:
            rows.append(level)
        if normalized_side == "short" and level.side == "support" and level.high < entry:
            rows.append(level)
    return rows


def _context_range_candidates(
    snapshot: MtfContextSnapshot,
    timeframe: str,
    side: str,
    entry: float,
) -> list[TargetSelection]:
    context_by_timeframe = {
        "1h": snapshot.h1,
        "4h": snapshot.h4,
        "1d": snapshot.daily,
        "1w": snapshot.weekly,
        "1M": snapshot.monthly,
    }
    context = context_by_timeframe.get(timeframe)
    if context is None or context.dealing_range is None:
        return []
    dealing_range = context.dealing_range
    values = (
        (("weak_high", dealing_range.weak_level), ("range_high", dealing_range.high))
        if side == "long"
        else (("weak_low", dealing_range.weak_level), ("range_low", dealing_range.low))
    )
    output: list[TargetSelection] = []
    for source, value in values:
        if value is None:
            continue
        if side == "long" and value <= entry:
            continue
        if side == "short" and value >= entry:
            continue
        output.append(
            TargetSelection(
                symbol=dealing_range.symbol,
                side=side,
                price=value,
                timeframe=timeframe,
                source=source,
                strength=dealing_range.direction_strength,
            )
        )
    return output


def select_timeframe_matched_target(
    engine: MtfDealingRangeEngine,
    snapshot: MtfContextSnapshot,
    symbol: str,
    timestamp: datetime,
    side: str,
    entry: float,
    poi: Level | None,
    raid: RaidSignal | None,
) -> TargetSelection | None:
    timeframe = preferred_target_timeframe(poi, raid)
    if timeframe is None:
        return None
    liquidity = build_liquidity_map(engine, symbol, timestamp)
    candidates: list[TargetSelection] = []
    for level in directional_target_levels(liquidity.levels, side, entry, timeframe):
        price = level.low if side == "long" else level.high
        candidates.append(
            TargetSelection(
                symbol=symbol.upper(),
                side=side,
                price=price,
                timeframe=timeframe,
                source=level.source,
                strength=level.strength,
            )
        )
    candidates.extend(_context_range_candidates(snapshot, timeframe, side, entry))
    if not candidates:
        return None
    if side == "long":
        return min(candidates, key=lambda target: (target.price - entry, -target.strength, target.source))
    return min(candidates, key=lambda target: (entry - target.price, -target.strength, target.source))
