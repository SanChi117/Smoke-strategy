#!/usr/bin/env python3
"""Closed-candle multi-timeframe context and dealing-range engine for SMOKE V2.

This module is the recognition layer only. It builds complete 5m/15m/1h/4h/
1d/1w/1M bars, confirmed pivots/fractals, structural dealing ranges, imbalance
levels and trend/level strength snapshots. It does not place orders.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from statistics import median
from typing import Iterable, Sequence

from strategy_lab.market_data import Candle, group_candles_by_symbol


class MarketState(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGE = "RANGE"
    TRANSITION = "TRANSITION"
    INSUFFICIENT = "INSUFFICIENT"


class SetupState(str, Enum):
    NO_CONTEXT = "NO_CONTEXT"
    MACRO_SCENARIO_READY = "MACRO_SCENARIO_READY"
    DAILY_RANGE_READY = "DAILY_RANGE_READY"
    H4_RANGE_READY = "H4_RANGE_READY"
    POI_APPROACH = "POI_APPROACH"
    POI_TESTED = "POI_TESTED"
    H1_REACTION_OR_RAID = "H1_REACTION_OR_RAID"
    WAIT_5M_BOS = "WAIT_5M_BOS"
    M5_BOS_CONFIRMED = "M5_BOS_CONFIRMED"
    M15_ARMED = "M15_ARMED"
    ENTRY_READY = "ENTRY_READY"
    INVALIDATED_OR_EXPIRED = "INVALIDATED_OR_EXPIRED"


_TIMEFRAME_WEIGHT = {
    "5m": 0.45,
    "15m": 0.60,
    "1h": 0.80,
    "4h": 1.00,
    "1d": 1.25,
    "1w": 1.50,
    "1M": 1.75,
}


@dataclass(frozen=True)
class ClosedBar:
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Pivot:
    symbol: str
    timeframe: str
    kind: str
    bar_open_time: datetime
    bar_close_time: datetime
    confirmed_at: datetime
    price: float
    left_bars: int
    right_bars: int
    prominence_pct: float
    displacement_pct: float
    strength: float


@dataclass(frozen=True)
class Level:
    symbol: str
    timeframe: str
    kind: str
    side: str
    low: float
    high: float
    formed_at: datetime
    confirmed_at: datetime
    strength: float
    source: str
    fresh: bool = True
    touches: int = 0


@dataclass(frozen=True)
class DealingRange:
    symbol: str
    timeframe: str
    state: MarketState
    low: float
    high: float
    equilibrium: float
    protected_level: float | None
    weak_level: float | None
    direction_strength: float
    confirmed_at: datetime
    reason: str


@dataclass(frozen=True)
class TimeframeContext:
    symbol: str
    timeframe: str
    timestamp: datetime
    state: MarketState
    trend_strength: float
    dealing_range: DealingRange | None
    last_close: float | None
    premium_discount: float | None
    pivot_count: int
    level_count: int
    nearest_support: Level | None
    nearest_resistance: Level | None


@dataclass(frozen=True)
class MtfContextSnapshot:
    symbol: str
    timestamp: datetime
    monthly: TimeframeContext
    weekly: TimeframeContext
    daily: TimeframeContext
    h4: TimeframeContext
    h1: TimeframeContext
    m15: TimeframeContext
    m5: TimeframeContext
    scenario: MarketState
    scenario_strength: float
    setup_state: SetupState
    long_allowed: bool
    short_allowed: bool
    reasons: tuple[str, ...]


def _infer_source_interval(rows: Sequence[Candle]) -> timedelta:
    ordered = sorted(rows, key=lambda row: row.time)
    seconds = [
        int((right.time - left.time).total_seconds())
        for left, right in zip(ordered, ordered[1:])
        if right.time > left.time
    ]
    if not seconds:
        return timedelta(minutes=5)
    return timedelta(seconds=max(60, int(median(seconds))))


def _floor_fixed(value: datetime, minutes: int) -> datetime:
    midnight = value.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = int((value - midnight).total_seconds() // 60)
    return midnight + timedelta(minutes=(elapsed // minutes) * minutes)


def _bucket_bounds(value: datetime, timeframe: str) -> tuple[datetime, datetime]:
    if timeframe == "5m":
        start = _floor_fixed(value, 5)
        return start, start + timedelta(minutes=5)
    if timeframe == "15m":
        start = _floor_fixed(value, 15)
        return start, start + timedelta(minutes=15)
    if timeframe == "1h":
        start = value.replace(minute=0, second=0, microsecond=0)
        return start, start + timedelta(hours=1)
    if timeframe == "4h":
        start = value.replace(hour=(value.hour // 4) * 4, minute=0, second=0, microsecond=0)
        return start, start + timedelta(hours=4)
    if timeframe == "1d":
        start = value.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)
    if timeframe == "1w":
        day = value.replace(hour=0, minute=0, second=0, microsecond=0)
        start = day - timedelta(days=day.weekday())
        return start, start + timedelta(days=7)
    if timeframe == "1M":
        start = value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)
        return start, end
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def resample_complete_bars(candles: Iterable[Candle], timeframe: str) -> list[ClosedBar]:
    """Build only complete UTC buckets from a continuous lower-timeframe feed."""
    output: list[ClosedBar] = []
    for symbol, source_rows in group_candles_by_symbol(candles).items():
        rows = sorted(source_rows, key=lambda row: row.time)
        if not rows:
            continue
        source_step = _infer_source_interval(rows)
        buckets: dict[datetime, tuple[datetime, list[Candle]]] = {}
        for row in rows:
            start, end = _bucket_bounds(row.time, timeframe)
            buckets.setdefault(start, (end, []))[1].append(row)

        for start, (end, bucket_rows) in sorted(buckets.items()):
            bucket_rows = sorted(bucket_rows, key=lambda row: row.time)
            expected = int((end - start) / source_step)
            if expected <= 0 or len(bucket_rows) != expected:
                continue
            if bucket_rows[0].time != start:
                continue
            if bucket_rows[-1].time + source_step != end:
                continue
            if any(
                right.time - left.time != source_step
                for left, right in zip(bucket_rows, bucket_rows[1:])
            ):
                continue
            output.append(
                ClosedBar(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=start,
                    close_time=end,
                    open=bucket_rows[0].open,
                    high=max(row.high for row in bucket_rows),
                    low=min(row.low for row in bucket_rows),
                    close=bucket_rows[-1].close,
                    volume=sum(row.volume for row in bucket_rows),
                )
            )
    return sorted(output, key=lambda row: (row.symbol, row.close_time))


def _true_range(rows: Sequence[ClosedBar], index: int) -> float:
    current = rows[index]
    if index == 0:
        return current.high - current.low
    previous = rows[index - 1]
    return max(
        current.high - current.low,
        abs(current.high - previous.close),
        abs(current.low - previous.close),
    )


def _atr(rows: Sequence[ClosedBar], index: int, length: int = 14) -> float | None:
    if index < length - 1:
        return None
    values = [_true_range(rows, current) for current in range(index - length + 1, index + 1)]
    return sum(values) / length


def confirmed_pivots(
    bars: Sequence[ClosedBar],
    left_bars: int = 2,
    right_bars: int = 2,
) -> list[Pivot]:
    """Return pivots only when all right-side candles have closed."""
    if left_bars < 1 or right_bars < 1:
        raise ValueError("Pivot left/right bars must be positive")
    rows = sorted(bars, key=lambda row: row.close_time)
    output: list[Pivot] = []
    for index in range(left_bars, len(rows) - right_bars):
        center = rows[index]
        left = rows[index - left_bars : index]
        right = rows[index + 1 : index + right_bars + 1]
        local_low = min(row.low for row in left + [center] + right)
        local_high = max(row.high for row in left + [center] + right)
        span = max(1e-12, local_high - local_low)
        atr = _atr(rows, index) or span

        high_pivot = center.high > max(row.high for row in left) and center.high >= max(row.high for row in right)
        low_pivot = center.low < min(row.low for row in left) and center.low <= min(row.low for row in right)
        confirmed_at = right[-1].close_time

        if high_pivot:
            prominence = max(0.0, (center.high - max(min(row.low for row in left), min(row.low for row in right))))
            displacement = max(0.0, center.high - min(row.low for row in right))
            output.append(
                Pivot(
                    symbol=center.symbol,
                    timeframe=center.timeframe,
                    kind="high",
                    bar_open_time=center.open_time,
                    bar_close_time=center.close_time,
                    confirmed_at=confirmed_at,
                    price=center.high,
                    left_bars=left_bars,
                    right_bars=right_bars,
                    prominence_pct=round(prominence / max(center.high, 1e-12) * 100.0, 6),
                    displacement_pct=round(displacement / max(atr, 1e-12), 6),
                    strength=round(_pivot_strength(center.timeframe, prominence / span, displacement / max(atr, 1e-12)), 4),
                )
            )
        if low_pivot:
            prominence = max(0.0, min(max(row.high for row in left), max(row.high for row in right)) - center.low)
            displacement = max(0.0, max(row.high for row in right) - center.low)
            output.append(
                Pivot(
                    symbol=center.symbol,
                    timeframe=center.timeframe,
                    kind="low",
                    bar_open_time=center.open_time,
                    bar_close_time=center.close_time,
                    confirmed_at=confirmed_at,
                    price=center.low,
                    left_bars=left_bars,
                    right_bars=right_bars,
                    prominence_pct=round(prominence / max(center.low, 1e-12) * 100.0, 6),
                    displacement_pct=round(displacement / max(atr, 1e-12), 6),
                    strength=round(_pivot_strength(center.timeframe, prominence / span, displacement / max(atr, 1e-12)), 4),
                )
            )
    return sorted(output, key=lambda pivot: (pivot.confirmed_at, pivot.kind, pivot.price))


def _pivot_strength(timeframe: str, prominence_ratio: float, displacement_atr: float) -> float:
    weight = _TIMEFRAME_WEIGHT.get(timeframe, 0.5)
    prominence_score = min(35.0, max(0.0, prominence_ratio) * 35.0)
    displacement_score = min(35.0, max(0.0, displacement_atr) * 12.0)
    return min(100.0, 20.0 * weight + prominence_score + displacement_score)


def imbalance_levels(bars: Sequence[ClosedBar], asof: datetime | None = None) -> list[Level]:
    rows = sorted(bars, key=lambda row: row.close_time)
    output: list[Level] = []
    cutoff = asof or datetime.max
    for index in range(2, len(rows)):
        left, middle, right = rows[index - 2], rows[index - 1], rows[index]
        if right.close_time > cutoff:
            break
        body_ratio = abs(middle.close - middle.open) / max(1e-12, middle.high - middle.low)
        displacement = min(1.0, body_ratio)
        weight = _TIMEFRAME_WEIGHT.get(right.timeframe, 0.5)
        if right.low > left.high:
            output.append(
                Level(
                    symbol=right.symbol,
                    timeframe=right.timeframe,
                    kind="imbalance",
                    side="support",
                    low=left.high,
                    high=right.low,
                    formed_at=right.close_time,
                    confirmed_at=right.close_time,
                    strength=round(min(100.0, 30.0 * weight + 35.0 * displacement), 4),
                    source="three_candle_bull_fvg",
                )
            )
        if right.high < left.low:
            output.append(
                Level(
                    symbol=right.symbol,
                    timeframe=right.timeframe,
                    kind="imbalance",
                    side="resistance",
                    low=right.high,
                    high=left.low,
                    formed_at=right.close_time,
                    confirmed_at=right.close_time,
                    strength=round(min(100.0, 30.0 * weight + 35.0 * displacement), 4),
                    source="three_candle_bear_fvg",
                )
            )
    return output


def pivot_levels(pivots: Sequence[Pivot], asof: datetime | None = None) -> list[Level]:
    cutoff = asof or datetime.max
    output: list[Level] = []
    for pivot in pivots:
        if pivot.confirmed_at > cutoff:
            continue
        buffer_pct = max(0.0002, min(0.003, pivot.prominence_pct / 100.0 * 0.08))
        low = pivot.price * (1.0 - buffer_pct)
        high = pivot.price * (1.0 + buffer_pct)
        output.append(
            Level(
                symbol=pivot.symbol,
                timeframe=pivot.timeframe,
                kind="pivot_fractal",
                side="resistance" if pivot.kind == "high" else "support",
                low=low,
                high=high,
                formed_at=pivot.bar_close_time,
                confirmed_at=pivot.confirmed_at,
                strength=pivot.strength,
                source=f"confirmed_{pivot.kind}_pivot",
            )
        )
    return output


def _mark_level_usage(levels: Sequence[Level], bars: Sequence[ClosedBar], asof: datetime) -> list[Level]:
    output: list[Level] = []
    for level in levels:
        touches = 0
        for bar in bars:
            if not (level.confirmed_at < bar.close_time <= asof):
                continue
            if bar.low <= level.high and bar.high >= level.low:
                touches += 1
        decay = min(35.0, touches * 9.0)
        output.append(
            Level(
                **{
                    **asdict(level),
                    "strength": round(max(0.0, level.strength - decay), 4),
                    "fresh": touches == 0,
                    "touches": touches,
                }
            )
        )
    return output


def build_dealing_range(
    bars: Sequence[ClosedBar],
    pivots: Sequence[Pivot],
    asof: datetime,
) -> DealingRange | None:
    available_bars = [bar for bar in bars if bar.close_time <= asof]
    available = [pivot for pivot in pivots if pivot.confirmed_at <= asof]
    highs = [pivot for pivot in available if pivot.kind == "high"]
    lows = [pivot for pivot in available if pivot.kind == "low"]
    if len(highs) < 2 or len(lows) < 2 or not available_bars:
        return None
    high_prev, high_last = highs[-2], highs[-1]
    low_prev, low_last = lows[-2], lows[-1]

    higher_high = high_last.price > high_prev.price
    higher_low = low_last.price > low_prev.price
    lower_high = high_last.price < high_prev.price
    lower_low = low_last.price < low_prev.price
    if higher_high and higher_low:
        state = MarketState.BULLISH
        protected = low_last.price
        weak = high_last.price
        strength = (high_last.strength + low_last.strength) / 2.0
        reason = "confirmed_HH_and_HL"
    elif lower_high and lower_low:
        state = MarketState.BEARISH
        protected = high_last.price
        weak = low_last.price
        strength = (high_last.strength + low_last.strength) / 2.0
        reason = "confirmed_LH_and_LL"
    elif (higher_high and lower_low) or (lower_high and higher_low):
        state = MarketState.TRANSITION
        protected = None
        weak = None
        strength = min(high_last.strength, low_last.strength) * 0.5
        reason = "expanding_or_conflicting_structure"
    else:
        state = MarketState.RANGE
        protected = None
        weak = None
        strength = (high_last.strength + low_last.strength) / 2.0 * 0.65
        reason = "no_confirmed_directional_sequence"

    low = min(low_last.price, low_prev.price)
    high = max(high_last.price, high_prev.price)
    if high <= low:
        return None
    return DealingRange(
        symbol=available_bars[-1].symbol,
        timeframe=available_bars[-1].timeframe,
        state=state,
        low=low,
        high=high,
        equilibrium=(low + high) / 2.0,
        protected_level=protected,
        weak_level=weak,
        direction_strength=round(max(0.0, min(100.0, strength)), 4),
        confirmed_at=max(high_last.confirmed_at, low_last.confirmed_at),
        reason=reason,
    )


def _nearest_levels(levels: Sequence[Level], price: float) -> tuple[Level | None, Level | None]:
    support = [level for level in levels if level.high <= price]
    resistance = [level for level in levels if level.low >= price]
    nearest_support = max(support, key=lambda level: (level.high, level.strength), default=None)
    nearest_resistance = min(resistance, key=lambda level: (level.low, -level.strength), default=None)
    return nearest_support, nearest_resistance


def build_timeframe_context(
    symbol: str,
    timeframe: str,
    bars: Sequence[ClosedBar],
    timestamp: datetime,
    left_bars: int = 2,
    right_bars: int = 2,
) -> TimeframeContext:
    available_bars = [bar for bar in bars if bar.symbol == symbol and bar.close_time <= timestamp]
    if not available_bars:
        return TimeframeContext(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=timestamp,
            state=MarketState.INSUFFICIENT,
            trend_strength=0.0,
            dealing_range=None,
            last_close=None,
            premium_discount=None,
            pivot_count=0,
            level_count=0,
            nearest_support=None,
            nearest_resistance=None,
        )
    pivots = confirmed_pivots(available_bars, left_bars, right_bars)
    dealing_range = build_dealing_range(available_bars, pivots, timestamp)
    levels = pivot_levels(pivots, timestamp) + imbalance_levels(available_bars, timestamp)
    levels = _mark_level_usage(levels, available_bars, timestamp)
    last_close = available_bars[-1].close
    nearest_support, nearest_resistance = _nearest_levels(levels, last_close)
    if dealing_range is None:
        state = MarketState.INSUFFICIENT
        trend_strength = 0.0
        pd = None
    else:
        state = dealing_range.state
        trend_strength = dealing_range.direction_strength
        pd = (last_close - dealing_range.low) / max(1e-12, dealing_range.high - dealing_range.low)
        pd = max(0.0, min(1.0, pd))
    return TimeframeContext(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp,
        state=state,
        trend_strength=round(trend_strength, 4),
        dealing_range=dealing_range,
        last_close=last_close,
        premium_discount=round(pd, 6) if pd is not None else None,
        pivot_count=len(pivots),
        level_count=len(levels),
        nearest_support=nearest_support,
        nearest_resistance=nearest_resistance,
    )


def _state_vote(context: TimeframeContext) -> int:
    if context.state == MarketState.BULLISH:
        return 1
    if context.state == MarketState.BEARISH:
        return -1
    return 0


class MtfDealingRangeEngine:
    """Build causal snapshots from a closed 5m candle history."""

    def __init__(self, candles_5m: Iterable[Candle]):
        source = list(candles_5m)
        self.bars = {
            timeframe: resample_complete_bars(source, timeframe)
            for timeframe in ("5m", "15m", "1h", "4h", "1d", "1w", "1M")
        }

    def snapshot(self, symbol: str, timestamp: datetime) -> MtfContextSnapshot:
        symbol = symbol.upper()
        contexts = {
            timeframe: build_timeframe_context(symbol, timeframe, self.bars[timeframe], timestamp)
            for timeframe in ("1M", "1w", "1d", "4h", "1h", "15m", "5m")
        }
        weights = {"1M": 0.10, "1w": 0.20, "1d": 0.30, "4h": 0.40}
        signed = sum(_state_vote(contexts[tf]) * weights[tf] for tf in weights)
        strength = sum(contexts[tf].trend_strength * weights[tf] for tf in weights)
        if abs(signed) < 0.20:
            scenario = MarketState.RANGE
        elif signed > 0:
            scenario = MarketState.BULLISH
        else:
            scenario = MarketState.BEARISH
        if contexts["1d"].state == MarketState.TRANSITION or contexts["4h"].state == MarketState.TRANSITION:
            scenario = MarketState.TRANSITION

        daily_ready = contexts["1d"].dealing_range is not None
        h4_ready = contexts["4h"].dealing_range is not None
        macro_ready = contexts["1w"].state != MarketState.INSUFFICIENT
        if not macro_ready:
            setup_state = SetupState.NO_CONTEXT
        elif not daily_ready:
            setup_state = SetupState.MACRO_SCENARIO_READY
        elif not h4_ready:
            setup_state = SetupState.DAILY_RANGE_READY
        else:
            setup_state = SetupState.H4_RANGE_READY

        long_allowed = scenario == MarketState.BULLISH and h4_ready
        short_allowed = scenario == MarketState.BEARISH and h4_ready
        reasons = [
            f"monthly={contexts['1M'].state.value}",
            f"weekly={contexts['1w'].state.value}",
            f"daily={contexts['1d'].state.value}",
            f"h4={contexts['4h'].state.value}",
            f"signed_vote={signed:.4f}",
        ]
        if scenario == MarketState.TRANSITION:
            reasons.append("daily_or_h4_transition_blocks_direction")
            long_allowed = False
            short_allowed = False

        return MtfContextSnapshot(
            symbol=symbol,
            timestamp=timestamp,
            monthly=contexts["1M"],
            weekly=contexts["1w"],
            daily=contexts["1d"],
            h4=contexts["4h"],
            h1=contexts["1h"],
            m15=contexts["15m"],
            m5=contexts["5m"],
            scenario=scenario,
            scenario_strength=round(max(0.0, min(100.0, strength)), 4),
            setup_state=setup_state,
            long_allowed=long_allowed,
            short_allowed=short_allowed,
            reasons=tuple(reasons),
        )
