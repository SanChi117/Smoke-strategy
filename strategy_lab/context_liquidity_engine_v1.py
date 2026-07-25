#!/usr/bin/env python3
"""SMOKE CORE 1.0 P2: causal context and liquidity engine.

Recognition-only module. It consumes closed multi-timeframe bars, produces a
parallel context/regime layer, a causal liquidity map, and target candidates.
It never reads trade outcomes and never moves a target to improve RR.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
import json
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from strategy_lab.mtf_dealing_range_v2 import (
    ClosedBar,
    MarketState,
    MtfDealingRangeEngine,
    TimeframeContext,
    confirmed_pivots,
)
from strategy_lab.period_liquidity_levels import previous_period_liquidity_levels
from strategy_lab.poi_imbalance_engine_v1 import Direction


class ContextRegime(str, Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    TRANSITION = "TRANSITION"
    EXPANSION = "EXPANSION"
    COMPRESSION = "COMPRESSION"
    INSUFFICIENT = "INSUFFICIENT"


class VolatilityRegime(str, Enum):
    EXPANSION = "EXPANSION"
    NORMAL = "NORMAL"
    COMPRESSION = "COMPRESSION"
    INSUFFICIENT = "INSUFFICIENT"


class LiquidityKind(str, Enum):
    SWING_HIGH = "SWING_HIGH"
    SWING_LOW = "SWING_LOW"
    EQUAL_HIGHS = "EQUAL_HIGHS"
    EQUAL_LOWS = "EQUAL_LOWS"
    PDH = "PDH"
    PDL = "PDL"
    PWH = "PWH"
    PWL = "PWL"
    PMH = "PMH"
    PML = "PML"
    SESSION_HIGH = "SESSION_HIGH"
    SESSION_LOW = "SESSION_LOW"
    RANGE_HIGH = "RANGE_HIGH"
    RANGE_LOW = "RANGE_LOW"


class LiquiditySide(str, Enum):
    BUY_SIDE = "BUY_SIDE"
    SELL_SIDE = "SELL_SIDE"


class LiquidityState(str, Enum):
    FRESH = "FRESH"
    PARTIALLY_MITIGATED = "PARTIALLY_MITIGATED"
    SWEPT = "SWEPT"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class SessionSpec:
    name: str
    start_minute_utc: int
    end_minute_utc: int
    base_strength: float

    def __post_init__(self) -> None:
        if not 0 <= self.start_minute_utc < 1440:
            raise ValueError("start_minute_utc must be in [0, 1440)")
        if not 0 <= self.end_minute_utc < 1440:
            raise ValueError("end_minute_utc must be in [0, 1440)")
        if self.start_minute_utc == self.end_minute_utc:
            raise ValueError("session start and end must differ")


@dataclass(frozen=True)
class ContextLiquidityConfig:
    atr_length: int = 14
    volatility_lookback: int = 20
    expansion_ratio: float = 1.35
    compression_ratio: float = 0.75
    direction_threshold: float = 0.15
    equal_tolerance_atr: float = 0.12
    equal_tolerance_pct: float = 0.0012
    equal_min_separation_bars: int = 2
    level_buffer_atr: float = 0.03
    sweep_buffer_atr: float = 0.03
    invalidation_buffer_atr: float = 0.05
    invalidation_closes: int = 2
    touch_strength_decay: float = 7.0
    external_bonus: float = 8.0
    session_specs: tuple[SessionSpec, ...] = (
        SessionSpec("ASIA", 0, 480, 55.0),
        SessionSpec("LONDON", 480, 780, 60.0),
        SessionSpec("NEW_YORK", 780, 1260, 60.0),
    )
    context_weights: tuple[tuple[str, float], ...] = (
        ("1M", 0.10),
        ("1w", 0.20),
        ("1d", 0.35),
        ("4h", 0.35),
    )

    def __post_init__(self) -> None:
        if self.atr_length < 2:
            raise ValueError("atr_length must be >= 2")
        if self.volatility_lookback < 2:
            raise ValueError("volatility_lookback must be >= 2")
        if not 0 < self.compression_ratio < self.expansion_ratio:
            raise ValueError("volatility ratios are inconsistent")
        if not 0 <= self.direction_threshold < 1:
            raise ValueError("direction_threshold must be in [0, 1)")
        if self.invalidation_closes < 1:
            raise ValueError("invalidation_closes must be >= 1")
        total_weight = sum(weight for _, weight in self.context_weights)
        if abs(total_weight - 1.0) > 1e-9:
            raise ValueError("context_weights must sum to 1")


@dataclass(frozen=True)
class TimeframeContextState:
    symbol: str
    timeframe: str
    evaluated_at: datetime
    direction: Direction
    market_state: str
    confidence_0_100: float
    range_low: float | None
    range_high: float | None
    equilibrium: float | None
    premium_discount_0_1: float | None
    protected_level: float | None
    weak_level: float | None
    range_confirmed_at: datetime | None
    atr_pct: float | None
    volatility_regime: VolatilityRegime
    pivot_count: int
    level_count: int
    valid_until: datetime


@dataclass(frozen=True)
class LiquidityLevelV1:
    level_id: str
    symbol: str
    timeframe: str
    kind: LiquidityKind
    side: LiquiditySide
    low: float
    high: float
    formed_at: datetime
    confirmed_at: datetime
    state: LiquidityState
    strength_0_100: float
    touch_count: int
    swept_at: datetime | None
    invalidated_at: datetime | None
    source: str
    source_event_ids: tuple[str, ...]
    external: bool

    @property
    def price(self) -> float:
        return (self.low + self.high) / 2.0


@dataclass(frozen=True)
class TargetCandidateV1:
    target_id: str
    symbol: str
    side: Direction
    level_id: str
    price: float
    timeframe: str
    source: str
    strength_0_100: float
    distance_pct: float
    external: bool
    selected_at: datetime


@dataclass(frozen=True)
class ContextLiquiditySnapshotV1:
    symbol: str
    evaluated_at: datetime
    direction: Direction
    regime: ContextRegime
    confidence_0_100: float
    timeframe_states: tuple[TimeframeContextState, ...]
    liquidity_levels: tuple[LiquidityLevelV1, ...]
    long_targets: tuple[TargetCandidateV1, ...]
    short_targets: tuple[TargetCandidateV1, ...]
    dependencies: tuple[str, ...]
    conflicts: tuple[str, ...]
    hard_block: bool
    hard_block_reason: str | None
    reasons: tuple[str, ...]
    valid_until: datetime


FORBIDDEN_KEY_FRAGMENTS = (
    "pnl",
    "future_return",
    "trade_outcome",
    "tp_result",
    "sl_result",
    "mfe",
    "mae",
    "profit_factor",
    "net_return",
    "drawdown",
    "exit_price",
    "exit_reason",
)


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}_{sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _true_range(rows: Sequence[ClosedBar], index: int) -> float:
    current = rows[index]
    if index == 0:
        return max(0.0, current.high - current.low)
    previous = rows[index - 1]
    return max(
        current.high - current.low,
        abs(current.high - previous.close),
        abs(current.low - previous.close),
    )


def _atr_values(rows: Sequence[ClosedBar], length: int) -> list[float | None]:
    values: list[float | None] = []
    tr: list[float] = []
    for index in range(len(rows)):
        tr.append(_true_range(rows, index))
        values.append(sum(tr[-length:]) / length if len(tr) >= length else None)
    return values


def _atr_at_or_before(rows: Sequence[ClosedBar], timestamp: datetime, length: int) -> float | None:
    available = [row for row in rows if row.close_time <= timestamp]
    if not available:
        return None
    return _atr_values(available, length)[-1]


def _volatility_regime(
    rows: Sequence[ClosedBar],
    config: ContextLiquidityConfig,
) -> tuple[float | None, VolatilityRegime]:
    if not rows:
        return None, VolatilityRegime.INSUFFICIENT
    atrs = _atr_values(rows, config.atr_length)
    current = atrs[-1]
    if current is None:
        return None, VolatilityRegime.INSUFFICIENT
    history = [value for value in atrs[-config.volatility_lookback - 1 : -1] if value is not None]
    baseline = median(history) if history else current
    ratio = current / max(1e-12, baseline)
    if ratio >= config.expansion_ratio:
        regime = VolatilityRegime.EXPANSION
    elif ratio <= config.compression_ratio:
        regime = VolatilityRegime.COMPRESSION
    else:
        regime = VolatilityRegime.NORMAL
    atr_pct = current / max(1e-12, rows[-1].close) * 100.0
    return round(atr_pct, 6), regime


def _direction_from_state(state: MarketState) -> Direction:
    if state == MarketState.BULLISH:
        return Direction.LONG
    if state == MarketState.BEARISH:
        return Direction.SHORT
    return Direction.NEUTRAL


def _timeframe_valid_until(timestamp: datetime, timeframe: str) -> datetime:
    if timeframe == "1M":
        start = timestamp.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    if timeframe == "1w":
        day = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        return day + timedelta(days=7 - day.weekday())
    if timeframe == "1d":
        return timestamp.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    if timeframe == "4h":
        start = timestamp.replace(hour=(timestamp.hour // 4) * 4, minute=0, second=0, microsecond=0)
        return start + timedelta(hours=4)
    if timeframe == "1h":
        return timestamp.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return timestamp + timedelta(minutes=15)


def build_timeframe_state(
    symbol: str,
    timeframe: str,
    context: TimeframeContext,
    bars: Sequence[ClosedBar],
    evaluated_at: datetime,
    config: ContextLiquidityConfig | None = None,
) -> TimeframeContextState:
    cfg = config or ContextLiquidityConfig()
    closed = [bar for bar in bars if bar.symbol == symbol and bar.close_time <= evaluated_at]
    atr_pct, vol_regime = _volatility_regime(closed, cfg)
    direction = _direction_from_state(context.state)
    confidence = context.trend_strength
    if context.dealing_range is not None:
        confidence += 8.0
    if context.pivot_count >= 4:
        confidence += 4.0
    if context.state == MarketState.TRANSITION:
        confidence *= 0.65
    if context.state == MarketState.RANGE:
        confidence *= 0.75
    dealing_range = context.dealing_range
    return TimeframeContextState(
        symbol=symbol,
        timeframe=timeframe,
        evaluated_at=evaluated_at,
        direction=direction,
        market_state=context.state.value,
        confidence_0_100=round(_clamp(confidence), 4),
        range_low=dealing_range.low if dealing_range else None,
        range_high=dealing_range.high if dealing_range else None,
        equilibrium=dealing_range.equilibrium if dealing_range else None,
        premium_discount_0_1=context.premium_discount,
        protected_level=dealing_range.protected_level if dealing_range else None,
        weak_level=dealing_range.weak_level if dealing_range else None,
        range_confirmed_at=dealing_range.confirmed_at if dealing_range else None,
        atr_pct=atr_pct,
        volatility_regime=vol_regime,
        pivot_count=context.pivot_count,
        level_count=context.level_count,
        valid_until=_timeframe_valid_until(evaluated_at, timeframe),
    )


def _aggregate_context(
    states: Mapping[str, TimeframeContextState],
    config: ContextLiquidityConfig,
) -> tuple[Direction, ContextRegime, float, tuple[str, ...]]:
    signed = 0.0
    total = 0.0
    conflicts: list[str] = []
    directional: list[tuple[str, Direction]] = []
    for timeframe, weight in config.context_weights:
        state = states.get(timeframe)
        if state is None or state.market_state == MarketState.INSUFFICIENT.value:
            continue
        sign = 1.0 if state.direction == Direction.LONG else -1.0 if state.direction == Direction.SHORT else 0.0
        contribution = weight * state.confidence_0_100
        signed += sign * contribution
        total += contribution
        if state.direction != Direction.NEUTRAL:
            directional.append((timeframe, state.direction))
    if total <= 1e-12:
        return Direction.NEUTRAL, ContextRegime.INSUFFICIENT, 0.0, ("insufficient_macro_context",)
    ratio = signed / total
    if ratio > config.direction_threshold:
        direction = Direction.LONG
    elif ratio < -config.direction_threshold:
        direction = Direction.SHORT
    else:
        direction = Direction.NEUTRAL
    direction_set = {item[1] for item in directional}
    if len(direction_set) > 1:
        conflicts.append("macro_timeframe_direction_conflict")
    volatility = [states[tf].volatility_regime for tf, _ in config.context_weights if tf in states]
    market_states = [states[tf].market_state for tf, _ in config.context_weights if tf in states]
    if volatility.count(VolatilityRegime.EXPANSION) >= 2:
        regime = ContextRegime.EXPANSION
    elif volatility.count(VolatilityRegime.COMPRESSION) >= 2:
        regime = ContextRegime.COMPRESSION
    elif direction == Direction.LONG and abs(ratio) >= 0.35:
        regime = ContextRegime.TREND_UP
    elif direction == Direction.SHORT and abs(ratio) >= 0.35:
        regime = ContextRegime.TREND_DOWN
    elif market_states.count(MarketState.RANGE.value) >= 2:
        regime = ContextRegime.RANGE
    else:
        regime = ContextRegime.TRANSITION
    confidence = abs(ratio) * 100.0
    if conflicts:
        confidence *= 0.82
    return direction, regime, round(_clamp(confidence), 4), tuple(conflicts)


def _liquidity_kind_from_period(source: str) -> LiquidityKind:
    return LiquidityKind[source]


def _level_side(kind: LiquidityKind) -> LiquiditySide:
    return LiquiditySide.BUY_SIDE if kind in {
        LiquidityKind.SWING_HIGH,
        LiquidityKind.EQUAL_HIGHS,
        LiquidityKind.PDH,
        LiquidityKind.PWH,
        LiquidityKind.PMH,
        LiquidityKind.SESSION_HIGH,
        LiquidityKind.RANGE_HIGH,
    } else LiquiditySide.SELL_SIDE


def _make_level(
    *,
    symbol: str,
    timeframe: str,
    kind: LiquidityKind,
    low: float,
    high: float,
    formed_at: datetime,
    confirmed_at: datetime,
    strength: float,
    source: str,
    source_event_ids: Iterable[str],
    external: bool,
) -> LiquidityLevelV1:
    level_id = _stable_id(
        "liq",
        symbol,
        timeframe,
        kind.value,
        round(low, 12),
        round(high, 12),
        confirmed_at.isoformat(),
        source,
    )
    return LiquidityLevelV1(
        level_id=level_id,
        symbol=symbol,
        timeframe=timeframe,
        kind=kind,
        side=_level_side(kind),
        low=low,
        high=high,
        formed_at=formed_at,
        confirmed_at=confirmed_at,
        state=LiquidityState.FRESH,
        strength_0_100=round(_clamp(strength), 4),
        touch_count=0,
        swept_at=None,
        invalidated_at=None,
        source=source,
        source_event_ids=tuple(sorted(set(source_event_ids))),
        external=external,
    )


def _pivot_liquidity_levels(
    engine: MtfDealingRangeEngine,
    symbol: str,
    evaluated_at: datetime,
    config: ContextLiquidityConfig,
) -> list[LiquidityLevelV1]:
    output: list[LiquidityLevelV1] = []
    for timeframe in ("1h", "4h", "1d", "1w", "1M"):
        bars = [bar for bar in engine.bars.get(timeframe, ()) if bar.symbol == symbol and bar.close_time <= evaluated_at]
        pivots = confirmed_pivots(bars, 2, 2)
        for pivot in pivots:
            atr = _atr_at_or_before(bars, pivot.confirmed_at, config.atr_length) or pivot.price * 0.001
            buffer_ = max(pivot.price * 0.0002, atr * config.level_buffer_atr)
            kind = LiquidityKind.SWING_HIGH if pivot.kind == "high" else LiquidityKind.SWING_LOW
            outpu