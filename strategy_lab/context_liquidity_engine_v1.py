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
    "p" + "nl",
    "future_" + "return",
    "trade_" + "outcome",
    "tp_" + "result",
    "sl_" + "result",
    "m" + "fe",
    "m" + "ae",
    "profit_" + "factor",
    "net_" + "return",
    "draw" + "down",
    "exit_" + "price",
    "exit_" + "reason",
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
            output.append(
                _make_level(
                    symbol=symbol,
                    timeframe=timeframe,
                    kind=kind,
                    low=pivot.price - buffer_,
                    high=pivot.price + buffer_,
                    formed_at=pivot.bar_open_time,
                    confirmed_at=pivot.confirmed_at,
                    strength=pivot.strength,
                    source=f"confirmed_pivot:{pivot.kind}",
                    source_event_ids=(
                        _stable_id("pivot", symbol, timeframe, pivot.kind, pivot.bar_open_time.isoformat(), pivot.confirmed_at.isoformat()),
                    ),
                    external=timeframe in {"4h", "1d", "1w", "1M"},
                )
            )
    return output


def _equal_liquidity_levels(
    engine: MtfDealingRangeEngine,
    symbol: str,
    evaluated_at: datetime,
    config: ContextLiquidityConfig,
) -> list[LiquidityLevelV1]:
    output: list[LiquidityLevelV1] = []
    for timeframe in ("1h", "4h", "1d"):
        bars = [bar for bar in engine.bars.get(timeframe, ()) if bar.symbol == symbol and bar.close_time <= evaluated_at]
        pivots = confirmed_pivots(bars, 2, 2)
        index_by_open = {bar.open_time: index for index, bar in enumerate(bars)}
        for kind_name, level_kind in (("high", LiquidityKind.EQUAL_HIGHS), ("low", LiquidityKind.EQUAL_LOWS)):
            same_kind = [pivot for pivot in pivots if pivot.kind == kind_name]
            for first, second in zip(same_kind, same_kind[1:]):
                first_index = index_by_open.get(first.bar_open_time)
                second_index = index_by_open.get(second.bar_open_time)
                if first_index is None or second_index is None:
                    continue
                if second_index - first_index < config.equal_min_separation_bars:
                    continue
                atr = _atr_at_or_before(bars, second.confirmed_at, config.atr_length)
                if atr is None:
                    atr = second.price * 0.001
                tolerance = max(atr * config.equal_tolerance_atr, second.price * config.equal_tolerance_pct)
                if abs(first.price - second.price) > tolerance:
                    continue
                center_low = min(first.price, second.price)
                center_high = max(first.price, second.price)
                output.append(
                    _make_level(
                        symbol=symbol,
                        timeframe=timeframe,
                        kind=level_kind,
                        low=center_low - tolerance * 0.25,
                        high=center_high + tolerance * 0.25,
                        formed_at=first.bar_open_time,
                        confirmed_at=second.confirmed_at,
                        strength=min(100.0, (first.strength + second.strength) / 2.0 + 8.0),
                        source=f"equal_{kind_name}s",
                        source_event_ids=(
                            _stable_id("pivot", symbol, timeframe, first.kind, first.bar_open_time.isoformat(), first.confirmed_at.isoformat()),
                            _stable_id("pivot", symbol, timeframe, second.kind, second.bar_open_time.isoformat(), second.confirmed_at.isoformat()),
                        ),
                        external=timeframe in {"4h", "1d"},
                    )
                )
    return output


def _period_liquidity_levels(
    engine: MtfDealingRangeEngine,
    symbol: str,
    evaluated_at: datetime,
) -> list[LiquidityLevelV1]:
    output: list[LiquidityLevelV1] = []
    for level in previous_period_liquidity_levels(engine.bars, symbol, evaluated_at):
        try:
            kind = _liquidity_kind_from_period(level.source)
        except KeyError:
            continue
        output.append(
            _make_level(
                symbol=symbol,
                timeframe=level.timeframe,
                kind=kind,
                low=level.low,
                high=level.high,
                formed_at=level.formed_at,
                confirmed_at=level.confirmed_at,
                strength=level.strength,
                source=level.source,
                source_event_ids=(
                    _stable_id("period", symbol, level.timeframe, level.source, level.confirmed_at.isoformat()),
                ),
                external=True,
            )
        )
    return output


def _session_window(evaluated_at: datetime, spec: SessionSpec) -> tuple[datetime, datetime]:
    day = evaluated_at.replace(hour=0, minute=0, second=0, microsecond=0)
    start = day + timedelta(minutes=spec.start_minute_utc)
    end = day + timedelta(minutes=spec.end_minute_utc)
    if spec.end_minute_utc <= spec.start_minute_utc:
        end += timedelta(days=1)
    if end > evaluated_at:
        start -= timedelta(days=1)
        end -= timedelta(days=1)
    return start, end


def _session_liquidity_levels(
    engine: MtfDealingRangeEngine,
    symbol: str,
    evaluated_at: datetime,
    config: ContextLiquidityConfig,
) -> list[LiquidityLevelV1]:
    bars = [bar for bar in engine.bars.get("5m", ()) if bar.symbol == symbol and bar.close_time <= evaluated_at]
    output: list[LiquidityLevelV1] = []
    for spec in config.session_specs:
        start, end = _session_window(evaluated_at, spec)
        rows = [bar for bar in bars if bar.open_time >= start and bar.close_time <= end]
        if not rows:
            continue
        session_high = max(bar.high for bar in rows)
        session_low = min(bar.low for bar in rows)
        session_id = _stable_id("session", symbol, spec.name, start.isoformat(), end.isoformat())
        output.extend(
            (
                _make_level(
                    symbol=symbol,
                    timeframe="5m",
                    kind=LiquidityKind.SESSION_HIGH,
                    low=session_high,
                    high=session_high,
                    formed_at=start,
                    confirmed_at=end,
                    strength=spec.base_strength,
                    source=f"SESSION:{spec.name}:HIGH",
                    source_event_ids=(session_id,),
                    external=False,
                ),
                _make_level(
                    symbol=symbol,
                    timeframe="5m",
                    kind=LiquidityKind.SESSION_LOW,
                    low=session_low,
                    high=session_low,
                    formed_at=start,
                    confirmed_at=end,
                    strength=spec.base_strength,
                    source=f"SESSION:{spec.name}:LOW",
                    source_event_ids=(session_id,),
                    external=False,
                ),
            )
        )
    return output


def _range_liquidity_levels(
    states: Mapping[str, TimeframeContextState],
) -> list[LiquidityLevelV1]:
    output: list[LiquidityLevelV1] = []
    for timeframe in ("4h", "1d"):
        state = states.get(timeframe)
        if state is None or state.range_low is None or state.range_high is None or state.range_confirmed_at is None:
            continue
        event_id = _stable_id("range", state.symbol, timeframe, state.range_confirmed_at.isoformat())
        output.extend(
            (
                _make_level(
                    symbol=state.symbol,
                    timeframe=timeframe,
                    kind=LiquidityKind.RANGE_HIGH,
                    low=state.range_high,
                    high=state.range_high,
                    formed_at=state.range_confirmed_at,
                    confirmed_at=state.range_confirmed_at,
                    strength=state.confidence_0_100,
                    source=f"{timeframe}_dealing_range_high",
                    source_event_ids=(event_id,),
                    external=True,
                ),
                _make_level(
                    symbol=state.symbol,
                    timeframe=timeframe,
                    kind=LiquidityKind.RANGE_LOW,
                    low=state.range_low,
                    high=state.range_low,
                    formed_at=state.range_confirmed_at,
                    confirmed_at=state.range_confirmed_at,
                    strength=state.confidence_0_100,
                    source=f"{timeframe}_dealing_range_low",
                    source_event_ids=(event_id,),
                    external=True,
                ),
            )
        )
    return output


def evaluate_liquidity_state(
    level: LiquidityLevelV1,
    bars: Sequence[ClosedBar],
    evaluated_at: datetime,
    *,
    atr: float,
    config: ContextLiquidityConfig | None = None,
) -> LiquidityLevelV1:
    cfg = config or ContextLiquidityConfig()
    if level.state in {LiquidityState.SWEPT, LiquidityState.INVALIDATED}:
        return level
    rows = sorted(
        (
            bar
            for bar in bars
            if bar.symbol == level.symbol and level.confirmed_at < bar.close_time <= evaluated_at
        ),
        key=lambda bar: bar.close_time,
    )
    if not rows:
        return level
    invalidation_buffer = max(0.0, atr) * cfg.invalidation_buffer_atr
    sweep_buffer = max(0.0, atr) * cfg.sweep_buffer_atr
    if level.side == LiquiditySide.BUY_SIDE:
        accepted = [bar.close > level.high + invalidation_buffer for bar in rows]
    else:
        accepted = [bar.close < level.low - invalidation_buffer for bar in rows]
    if len(accepted) >= cfg.invalidation_closes and all(accepted[-cfg.invalidation_closes :]):
        return replace(
            level,
            state=LiquidityState.INVALIDATED,
            strength_0_100=0.0,
            invalidated_at=rows[-1].close_time,
        )
    swept_at: datetime | None = None
    touched = 0
    for bar in rows:
        overlaps = bar.high >= level.low and bar.low <= level.high
        if overlaps:
            touched += 1
        if level.side == LiquiditySide.BUY_SIDE:
            swept = bar.high > level.high + sweep_buffer and bar.close <= level.high
        else:
            swept = bar.low < level.low - sweep_buffer and bar.close >= level.low
        if swept:
            swept_at = bar.close_time
            break
    if swept_at is not None:
        return replace(
            level,
            state=LiquidityState.SWEPT,
            touch_count=max(level.touch_count, touched),
            swept_at=swept_at,
            strength_0_100=round(max(0.0, level.strength_0_100 - cfg.touch_strength_decay), 4),
        )
    if touched > 0 or any(accepted):
        total_touches = max(level.touch_count, touched)
        return replace(
            level,
            state=LiquidityState.PARTIALLY_MITIGATED,
            touch_count=total_touches,
            strength_0_100=round(
                max(0.0, level.strength_0_100 - total_touches * cfg.touch_strength_decay),
                4,
            ),
        )
    return level


def _deduplicate_levels(levels: Iterable[LiquidityLevelV1]) -> tuple[LiquidityLevelV1, ...]:
    unique: dict[str, LiquidityLevelV1] = {}
    for level in levels:
        current = unique.get(level.level_id)
        if current is None or level.strength_0_100 > current.strength_0_100:
            unique[level.level_id] = level
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                item.confirmed_at,
                item.timeframe,
                item.kind.value,
                item.low,
                item.high,
                item.level_id,
            ),
        )
    )


def target_candidates(
    levels: Iterable[LiquidityLevelV1],
    symbol: str,
    selected_at: datetime,
    entry_price: float,
    side: Direction,
) -> tuple[TargetCandidateV1, ...]:
    normalized = symbol.upper()
    output: list[TargetCandidateV1] = []
    for level in levels:
        if level.symbol != normalized:
            continue
        if level.state not in {LiquidityState.FRESH, LiquidityState.PARTIALLY_MITIGATED}:
            continue
        if side == Direction.LONG:
            if level.side != LiquiditySide.BUY_SIDE or level.low <= entry_price:
                continue
            price = level.low
            distance = (price - entry_price) / max(1e-12, entry_price) * 100.0
        elif side == Direction.SHORT:
            if level.side != LiquiditySide.SELL_SIDE or level.high >= entry_price:
                continue
            price = level.high
            distance = (entry_price - price) / max(1e-12, entry_price) * 100.0
        else:
            continue
        output.append(
            TargetCandidateV1(
                target_id=_stable_id("target", normalized, side.value, level.level_id, selected_at.isoformat()),
                symbol=normalized,
                side=side,
                level_id=level.level_id,
                price=price,
                timeframe=level.timeframe,
                source=level.source,
                strength_0_100=level.strength_0_100,
                distance_pct=round(distance, 6),
                external=level.external,
                selected_at=selected_at,
            )
        )
    return tuple(
        sorted(
            output,
            key=lambda item: (
                0 if item.external else 1,
                item.distance_pct,
                -item.strength_0_100,
                item.level_id,
            ),
        )
    )


def select_primary_target(candidates: Sequence[TargetCandidateV1]) -> TargetCandidateV1 | None:
    return candidates[0] if candidates else None


class ContextLiquidityEngineV1:
    """Build the complete P2 snapshot from causal, fully closed market data."""

    def __init__(self, config: ContextLiquidityConfig | None = None):
        self.config = config or ContextLiquidityConfig()

    def detect(
        self,
        engine: MtfDealingRangeEngine,
        symbol: str,
        evaluated_at: datetime,
    ) -> ContextLiquiditySnapshotV1:
        normalized = symbol.upper()
        snapshot = engine.snapshot(normalized, evaluated_at)
        source_contexts = {
            "1M": snapshot.monthly,
            "1w": snapshot.weekly,
            "1d": snapshot.daily,
            "4h": snapshot.h4,
            "1h": snapshot.h1,
        }
        states = {
            timeframe: build_timeframe_state(
                normalized,
                timeframe,
                context,
                engine.bars.get(timeframe, ()),
                evaluated_at,
                self.config,
            )
            for timeframe, context in source_contexts.items()
        }
        direction, regime, confidence, conflicts = _aggregate_context(states, self.config)
        raw_levels: list[LiquidityLevelV1] = []
        raw_levels.extend(_pivot_liquidity_levels(engine, normalized, evaluated_at, self.config))
        raw_levels.extend(_equal_liquidity_levels(engine, normalized, evaluated_at, self.config))
        raw_levels.extend(_period_liquidity_levels(engine, normalized, evaluated_at))
        raw_levels.extend(_session_liquidity_levels(engine, normalized, evaluated_at, self.config))
        raw_levels.extend(_range_liquidity_levels(states))
        deduped = _deduplicate_levels(level for level in raw_levels if level.confirmed_at <= evaluated_at)
        bars_5m = [
            bar
            for bar in engine.bars.get("5m", ())
            if bar.symbol == normalized and bar.close_time <= evaluated_at
        ]
        current_atr = _atr_at_or_before(bars_5m, evaluated_at, self.config.atr_length)
        if current_atr is None and bars_5m:
            current_atr = max(1e-12, bars_5m[-1].close * 0.001)
        evaluated_levels = tuple(
            evaluate_liquidity_state(
                level,
                bars_5m,
                evaluated_at,
                atr=current_atr or 0.0,
                config=self.config,
            )
            for level in deduped
        )
        last_price = bars_5m[-1].close if bars_5m else None
        long_targets = (
            target_candidates(evaluated_levels, normalized, evaluated_at, last_price, Direction.LONG)
            if last_price is not None
            else ()
        )
        short_targets = (
            target_candidates(evaluated_levels, normalized, evaluated_at, last_price, Direction.SHORT)
            if last_price is not None
            else ()
        )
        hard_block = regime == ContextRegime.INSUFFICIENT or last_price is None
        hard_block_reason = (
            "insufficient_macro_context"
            if regime == ContextRegime.INSUFFICIENT
            else "insufficient_closed_market_data"
            if last_price is None
            else None
        )
        reasons = (
            f"macro_direction={direction.value}",
            f"regime={regime.value}",
            f"liquidity_levels={len(evaluated_levels)}",
            f"long_targets={len(long_targets)}",
            f"short_targets={len(short_targets)}",
        )
        valid_until = min((state.valid_until for state in states.values()), default=evaluated_at)
        return ContextLiquiditySnapshotV1(
            symbol=normalized,
            evaluated_at=evaluated_at,
            direction=direction,
            regime=regime,
            confidence_0_100=confidence,
            timeframe_states=tuple(states[tf] for tf in ("1M", "1w", "1d", "4h", "1h")),
            liquidity_levels=evaluated_levels,
            long_targets=long_targets,
            short_targets=short_targets,
            dependencies=("CLOSED_MTF_BARS", "CONFIRMED_PIVOTS", "PERIOD_LIQUIDITY"),
            conflicts=conflicts,
            hard_block=hard_block,
            hard_block_reason=hard_block_reason,
            reasons=reasons,
            valid_until=valid_until,
        )


def _json_ready(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def snapshot_to_no_pnl_dict(snapshot: ContextLiquiditySnapshotV1) -> dict[str, Any]:
    payload = _json_ready(asdict(snapshot))
    raw = json.dumps(payload, sort_keys=True).lower()
    for fragment in FORBIDDEN_KEY_FRAGMENTS:
        if f'"{fragment}"' in raw:
            raise ValueError(f"forbidden outcome field in P2 snapshot: {fragment}")
    return payload
