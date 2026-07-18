#!/usr/bin/env python3
"""Stateful H1 confirmation -> 5m BOS -> next 15m open entry model.

Two causal paths are supported:
1) fresh H1 liquidity raid -> 5m BOS;
2) H1 volume confirmation creates a zone -> later closed 15m test -> 5m BOS.

Research only. This module never sends paper or live orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from strategy_lab.event_risk import EventRiskDecision
from strategy_lab.mtf_dealing_range_v2 import (
    ClosedBar,
    Level,
    MtfContextSnapshot,
    MtfDealingRangeEngine,
    Pivot,
    SetupState,
    confirmed_pivots,
)
from strategy_lab.mtf_liquidity_map_v2 import build_liquidity_map
from strategy_lab.mtf_raid_signal_v2 import RaidSignal, detect_h1_raid_signal
from strategy_lab.mtf_target_selection_v2 import TargetSelection, select_timeframe_matched_target
from strategy_lab.mtf_vc_zone_test_v2 import VcZoneTestSignal, detect_15m_vc_zone_test
from strategy_lab.mtf_volume_confirmation_v2 import (
    VolumeConfirmationSignal,
    detect_h1_volume_confirmation,
)


@dataclass(frozen=True)
class EntryConfig:
    min_rr: float = 1.70
    stop_buffer_atr: float = 0.10
    bos_body_atr: float = 0.50
    bos_close_location: float = 0.70
    poi_distance_atr: float = 0.50
    min_quality_score: float = 55.0
    max_bos_age_minutes: int = 15
    minimum_structural_strength: float = 40.0


@dataclass(frozen=True)
class BosSignal:
    symbol: str
    side: str
    pivot: Pivot
    signal_bar: ClosedBar
    displacement: bool
    imbalance: bool
    strength: float


@dataclass(frozen=True)
class EntryPlan:
    symbol: str
    side: str
    evaluated_at: datetime
    setup_state: SetupState
    allowed: bool
    entry_time: datetime | None
    entry: float | None
    stop: float | None
    target: float | None
    target_timeframe: str | None
    target_source: str | None
    rr: float | None
    quality_score: float
    quality_state: str
    context: MtfContextSnapshot
    poi: Level | None
    h1_raid: bool
    raid: RaidSignal | None
    h1_reaction: bool
    h1_vc: bool
    volume_confirmation: VolumeConfirmationSignal | None
    vc_zone_test: bool
    vc_test: VcZoneTestSignal | None
    bos: BosSignal | None
    event_blocked: bool
    event_risk_multiplier: float
    reasons: tuple[str, ...]


def _bars_asof(bars: Sequence[ClosedBar], symbol: str, timestamp: datetime) -> list[ClosedBar]:
    return [bar for bar in bars if bar.symbol == symbol and bar.close_time <= timestamp]


def _true_range(rows: Sequence[ClosedBar], index: int) -> float:
    bar = rows[index]
    if index == 0:
        return bar.high - bar.low
    previous = rows[index - 1]
    return max(bar.high - bar.low, abs(bar.high - previous.close), abs(bar.low - previous.close))


def _atr(rows: Sequence[ClosedBar], length: int = 14) -> float | None:
    if len(rows) < length:
        return None
    start = len(rows) - length
    return sum(_true_range(rows, index) for index in range(start, len(rows))) / length


def _level_distance(level: Level, price: float) -> float:
    if level.low <= price <= level.high:
        return 0.0
    return min(abs(price - level.low), abs(price - level.high))


def _available_levels(
    engine: MtfDealingRangeEngine,
    symbol: str,
    timestamp: datetime,
    timeframes: tuple[str, ...] = ("1h", "4h", "1d", "1w", "1M"),
) -> list[Level]:
    liquidity = build_liquidity_map(engine, symbol, timestamp)
    return [
        level
        for level in liquidity.levels
        if level.timeframe in timeframes and level.confirmed_at <= timestamp
    ]


def find_active_poi(
    engine: MtfDealingRangeEngine,
    symbol: str,
    timestamp: datetime,
    side: str,
    config: EntryConfig,
) -> Level | None:
    h1 = _bars_asof(engine.bars["1h"], symbol, timestamp)
    if not h1:
        return None
    price = h1[-1].close
    atr = _atr(h1) or max(1e-12, h1[-1].high - h1[-1].low)
    desired = "support" if side == "long" else "resistance"
    candidates = [
        level
        for level in _available_levels(engine, symbol, timestamp)
        if level.side == desired and _level_distance(level, price) <= atr * config.poi_distance_atr
    ]
    if not candidates:
        return None
    timeframe_rank = {"1h": 1, "4h": 2, "1d": 3, "1w": 4, "1M": 5}
    return max(
        candidates,
        key=lambda level: (
            level.strength,
            timeframe_rank.get(level.timeframe, 0),
            int(level.fresh),
            -level.touches,
            -_level_distance(level, price),
            level.confirmed_at,
        ),
    )


def detect_liquidity_raid(
    bars: Sequence[ClosedBar], side: str, timestamp: datetime, lookback_bars: int = 4
) -> bool:
    return detect_h1_raid_signal(bars, side, timestamp, lookback_bars) is not None


def detect_h1_reaction(
    bars: Sequence[ClosedBar],
    poi: Level | None,
    side: str,
    timestamp: datetime,
    lookback_bars: int = 3,
) -> bool:
    """Diagnostic candle reaction; it cannot arm an entry by itself."""
    if poi is None:
        return False
    rows = [bar for bar in bars if bar.close_time <= timestamp]
    for bar in rows[-lookback_bars:]:
        if not (bar.low <= poi.high and bar.high >= poi.low):
            continue
        full_range = max(1e-12, bar.high - bar.low)
        close_location = (bar.close - bar.low) / full_range
        midpoint = (poi.low + poi.high) / 2.0
        if side == "long" and bar.close > bar.open and bar.close >= midpoint and close_location >= 0.60:
            return True
        if side == "short" and bar.close < bar.open and bar.close <= midpoint and close_location <= 0.40:
            return True
    return False


def detect_5m_bos(
    bars: Sequence[ClosedBar],
    side: str,
    timestamp: datetime,
    config: EntryConfig,
    raid: RaidSignal | None = None,
    confirmation_time: datetime | None = None,
) -> BosSignal | None:
    """Detect a fresh body-close BOS after the selected confirmation path."""
    rows = [bar for bar in bars if bar.close_time <= timestamp]
    if len(rows) < 20:
        return None
    signal = rows[-1]
    age = timestamp - signal.close_time
    if age < timedelta(0) or age > timedelta(minutes=config.max_bos_age_minutes):
        return None
    if confirmation_time is not None and signal.open_time < confirmation_time:
        return None

    desired_kind = "high" if side == "long" else "low"
    candidates = [
        pivot
        for pivot in confirmed_pivots(rows[:-1], 2, 2)
        if pivot.kind == desired_kind and pivot.confirmed_at <= signal.open_time
    ]
    if not candidates:
        return None
    pivot = candidates[-1]
    previous = rows[-2]
    crossed = (
        signal.close > pivot.price and previous.close <= pivot.price
        if side == "long"
        else signal.close < pivot.price and previous.close >= pivot.price
    )
    if not crossed:
        return None

    if raid is not None:
        if signal.open_time < raid.raid_bar.close_time:
            return None
        if side == "long" and not (pivot.price > raid.pivot.price and signal.close > raid.pivot.price):
            return None
        if side == "short" and not (pivot.price < raid.pivot.price and signal.close < raid.pivot.price):
            return None

    atr = _atr(rows) or max(1e-12, signal.high - signal.low)
    full_range = max(1e-12, signal.high - signal.low)
    body = abs(signal.close - signal.open)
    close_location = (signal.close - signal.low) / full_range
    directional = signal.close > signal.open if side == "long" else signal.close < signal.open
    displacement = directional and body >= atr * config.bos_body_atr and (
        close_location >= config.bos_close_location
        if side == "long"
        else close_location <= 1.0 - config.bos_close_location
    )
    imbalance = False
    if len(rows) >= 3:
        left = rows[-3]
        imbalance = signal.low > left.high if side == "long" else signal.high < left.low
    if not displacement and not imbalance:
        return None

    strength = min(
        100.0,
        pivot.strength * 0.45
        + min(35.0, body / max(atr, 1e-12) * 20.0)
        + (15.0 if imbalance else 0.0),
    )
    return BosSignal(
        symbol=signal.symbol,
        side=side,
        pivot=pivot,
        signal_bar=signal,
        displacement=displacement,
        imbalance=imbalance,
        strength=round(strength, 4),
    )


def find_next_15m_entry_bar(
    bars: Sequence[ClosedBar], symbol: str, timestamp: datetime, bos: BosSignal | None
) -> ClosedBar | None:
    """Use only the open of the aligned 15m bar at the evaluation timestamp."""
    if bos is None or bos.signal_bar.close_time > timestamp:
        return None
    if timestamp.second != 0 or timestamp.microsecond != 0 or timestamp.minute % 15 != 0:
        return None
    return next(
        (
            bar
            for bar in bars
            if bar.symbol == symbol and bar.timeframe == "15m" and bar.open_time == timestamp
        ),
        None,
    )


def _select_stop(
    engine: MtfDealingRangeEngine,
    symbol: str,
    timestamp: datetime,
    side: str,
    entry: float,
    poi: Level | None,
    raid: RaidSignal | None,
    config: EntryConfig,
) -> float | None:
    h1 = _bars_asof(engine.bars["1h"], symbol, timestamp)
    atr = _atr(h1) if h1 else None
    if atr is None:
        atr = entry * 0.005

    if raid is not None:
        anchor = raid.pivot.price
        if side == "long" and anchor < entry:
            return anchor - atr * config.stop_buffer_atr
        if side == "short" and anchor > entry:
            return anchor + atr * config.stop_buffer_atr

    candidates: list[tuple[float, float, int]] = []
    rank = {"5m": 1, "15m": 2, "1h": 3}
    for timeframe in ("5m", "15m", "1h"):
        bars = _bars_asof(engine.bars[timeframe], symbol, timestamp)
        for pivot in confirmed_pivots(bars, 2, 2)[-12:]:
            if pivot.strength < config.minimum_structural_strength:
                continue
            if side == "long" and pivot.kind == "low" and pivot.price < entry:
                candidates.append((pivot.price, pivot.strength, rank[timeframe]))
            if side == "short" and pivot.kind == "high" and pivot.price > entry:
                candidates.append((pivot.price, pivot.strength, rank[timeframe]))
    if poi is not None:
        level_price = poi.low if side == "long" else poi.high
        poi_rank = {"1h": 3, "4h": 4, "1d": 5, "1w": 6, "1M": 7}.get(poi.timeframe, 3)
        candidates.append((level_price, poi.strength, poi_rank))

    if side == "long":
        valid = [item for item in candidates if item[0] < entry]
        if not valid:
            return None
        anchor = max(valid, key=lambda item: (item[0], item[1], item[2]))[0]
        return anchor - atr * config.stop_buffer_atr
    valid = [item for item in candidates if item[0] > entry]
    if not valid:
        return None
    anchor = min(valid, key=lambda item: (item[0], -item[1], -item[2]))[0]
    return anchor + atr * config.stop_buffer_atr


def _quality_state(score: float) -> str:
    if score >= 75.0:
        return "STRONG"
    if score >= 55.0:
        return "QUALIFIED"
    if score >= 40.0:
        return "WATCH"
    return "POOR"


class MtfEntryModelV2:
    def __init__(self, engine: MtfDealingRangeEngine, config: EntryConfig | None = None):
        self.engine = engine
        self.config = config or EntryConfig()

    def evaluate(
        self,
        symbol: str,
        timestamp: datetime,
        side: str,
        event_decision: EventRiskDecision | None = None,
    ) -> EntryPlan:
        symbol = symbol.upper()
        side = side.lower()
        if side not in {"long", "short"}:
            raise ValueError("side must be long or short")

        snapshot = self.engine.snapshot(symbol, timestamp)
        reasons: list[str] = []
        direction_allowed = snapshot.long_allowed if side == "long" else snapshot.short_allowed
        if not direction_allowed:
            reasons.append(f"context_blocks_{side}:{snapshot.scenario.value}")

        event_blocked = bool(event_decision and event_decision.block_new_entry)
        event_multiplier = event_decision.risk_multiplier if event_decision else 1.0
        if event_blocked:
            reasons.append("high_impact_event_blackout")

        poi = find_active_poi(self.engine, symbol, timestamp, side, self.config)
        if poi is None:
            reasons.append("no_active_htf_poi")

        h1_rows = _bars_asof(self.engine.bars["1h"], symbol, timestamp)
        raid = detect_h1_raid_signal(h1_rows, side, timestamp)
        h1_raid = raid is not None
        h1_reaction = detect_h1_reaction(h1_rows, poi, side, timestamp)
        vc = detect_h1_volume_confirmation(h1_rows, poi, side, timestamp)
        h1_vc = vc is not None
        vc_test = detect_15m_vc_zone_test(self.engine.bars["15m"], vc, side, timestamp)
        vc_zone_test = vc_test is not None

        raid_path_ready = h1_raid
        vc_path_ready = h1_vc and vc_zone_test
        confirmation_ready = poi is not None and (raid_path_ready or vc_path_ready)
        if poi is not None and not h1_raid and not h1_vc:
            reasons.append("poi_has_no_closed_h1_raid_or_vc")
        elif poi is not None and h1_vc and not h1_raid and not vc_zone_test:
            reasons.append("h1_vc_zone_not_tested_on_closed_15m")

        confirmation_time: datetime | None = None
        if raid is not None:
            confirmation_time = raid.raid_bar.close_time
        elif vc_test is not None:
            confirmation_time = vc_test.test_bar.close_time
        bos = detect_5m_bos(
            self.engine.bars["5m"],
            side,
            timestamp,
            self.config,
            raid=raid,
            confirmation_time=confirmation_time,
        )
        if bos is None:
            reasons.append("no_confirmed_5m_bos")

        if not direction_allowed:
            state = SetupState.NO_CONTEXT
        elif poi is None:
            state = SetupState.H4_RANGE_READY
        elif not confirmation_ready:
            state = SetupState.POI_TESTED
        elif bos is None:
            state = SetupState.WAIT_5M_BOS
        else:
            state = SetupState.M5_BOS_CONFIRMED

        entry_bar = find_next_15m_entry_bar(self.engine.bars["15m"], symbol, timestamp, bos)
        if bos is not None and entry_bar is None:
            state = SetupState.M15_ARMED
            reasons.append("next_15m_open_not_available_yet")
        entry = entry_bar.open if entry_bar is not None else None
        stop = (
            _select_stop(self.engine, symbol, timestamp, side, entry, poi, raid, self.config)
            if entry is not None
            else None
        )
        target_selection: TargetSelection | None = (
            select_timeframe_matched_target(
                self.engine,
                snapshot,
                symbol,
                timestamp,
                side,
                entry,
                poi,
                raid,
            )
            if entry is not None
            else None
        )
        target = target_selection.price if target_selection is not None else None

        rr: float | None = None
        if entry is not None and stop is not None and target is not None:
            risk = entry - stop if side == "long" else stop - entry
            reward = target - entry if side == "long" else entry - target
            if risk > 0 and reward > 0:
                rr = reward / risk
            else:
                reasons.append("invalid_structural_stop_or_target")
        elif bos is not None:
            reasons.append("missing_structural_stop_or_timeframe_matched_fta")

        trend_score = snapshot.scenario_strength * 0.30
        poi_score = (poi.strength if poi else 0.0) * 0.25
        if h1_raid:
            confirmation_score = 15.0
        elif vc_zone_test:
            confirmation_score = 14.0
        elif h1_vc:
            confirmation_score = 4.0
        elif h1_reaction:
            confirmation_score = 2.0
        else:
            confirmation_score = 0.0
        bos_score = (bos.strength if bos else 0.0) * 0.20
        target_score = 10.0 if rr is not None and rr >= self.config.min_rr else 0.0
        event_score = 5.0 * max(0.0, min(1.0, event_multiplier))
        quality = min(
            100.0,
            trend_score + poi_score + confirmation_score + bos_score + target_score + event_score,
        )
        quality_state = _quality_state(quality)

        rr_ok = rr is not None and rr >= self.config.min_rr
        if rr is not None and not rr_ok:
            reasons.append(f"rr_below_min:{rr:.4f}<{self.config.min_rr:.4f}")
        quality_ok = quality >= self.config.min_quality_score
        if not quality_ok:
            reasons.append(f"quality_below_min:{quality:.4f}")

        allowed = all(
            (
                direction_allowed,
                not event_blocked,
                confirmation_ready,
                bos is not None,
                entry is not None,
                stop is not None,
                target is not None,
                rr_ok,
                quality_ok,
            )
        )
        if allowed:
            state = SetupState.ENTRY_READY
            reasons.append("entry_ready_next_15m_open")

        return EntryPlan(
            symbol=symbol,
            side=side,
            evaluated_at=timestamp,
            setup_state=state,
            allowed=allowed,
            entry_time=timestamp if entry is not None else None,
            entry=round(entry, 8) if entry is not None else None,
            stop=round(stop, 8) if stop is not None else None,
            target=round(target, 8) if target is not None else None,
            target_timeframe=target_selection.timeframe if target_selection else None,
            target_source=target_selection.source if target_selection else None,
            rr=round(rr, 6) if rr is not None else None,
            quality_score=round(quality, 4),
            quality_state=quality_state,
            context=snapshot,
            poi=poi,
            h1_raid=h1_raid,
            raid=raid,
            h1_reaction=h1_reaction,
            h1_vc=h1_vc,
            volume_confirmation=vc,
            vc_zone_test=vc_zone_test,
            vc_test=vc_test,
            bos=bos,
            event_blocked=event_blocked,
            event_risk_multiplier=round(event_multiplier, 6),
            reasons=tuple(reasons),
        )
