#!/usr/bin/env python3
"""Causal FTA-first recognition model for SMOKE MTF V3.

This module is recognition-only. It never resolves future trade outcomes and
never places paper or live orders.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Sequence

from strategy_lab.event_risk import EventRiskDecision
from strategy_lab.mtf_dealing_range_v2 import (
    ClosedBar,
    Level,
    MtfContextSnapshot,
    MtfDealingRangeEngine,
    Pivot,
    confirmed_pivots,
)
from strategy_lab.mtf_entry_model_v2 import (
    BosSignal,
    EntryConfig,
    detect_5m_bos,
    find_active_poi,
)
from strategy_lab.mtf_liquidity_map_v2 import build_liquidity_map
from strategy_lab.mtf_raid_signal_v2 import RaidSignal, detect_h1_raid_signal
from strategy_lab.mtf_vc_zone_test_v2 import VcZoneTestSignal, detect_15m_vc_zone_test
from strategy_lab.mtf_volume_confirmation_v2 import (
    VolumeConfirmationSignal,
    detect_h1_volume_confirmation,
)


class FtaFirstState(str, Enum):
    NO_CONTEXT = "NO_CONTEXT"
    WAIT_EXTERNAL_FTA = "WAIT_EXTERNAL_FTA"
    WAIT_HTF_POI = "WAIT_HTF_POI"
    WAIT_H1_ROUTE = "WAIT_H1_ROUTE"
    WAIT_5M_BOS = "WAIT_5M_BOS"
    WAIT_15M_PULLBACK = "WAIT_15M_PULLBACK"
    WAIT_NEXT_15M_OPEN = "WAIT_NEXT_15M_OPEN"
    WAIT_POST_BOS_STOP = "WAIT_POST_BOS_STOP"
    RR_BLOCKED = "RR_BLOCKED"
    QUALITY_BLOCKED = "QUALITY_BLOCKED"
    ENTRY_READY = "ENTRY_READY"


@dataclass(frozen=True)
class FtaFirstConfig:
    min_rr: float = 1.70
    min_quality_score: float = 55.0
    bos_body_atr: float = 0.50
    bos_close_location: float = 0.70
    max_bos_age_minutes: int = 15
    max_pullback_bars: int = 8
    pullback_tolerance_h1_atr: float = 0.10
    stop_buffer_h1_atr: float = 0.10
    poi_distance_atr: float = 0.50
    minimum_structural_strength: float = 40.0
    external_timeframes: tuple[str, ...] = ("4h", "1d", "1w", "1M")

    def v2_entry_config(self) -> EntryConfig:
        return EntryConfig(
            min_rr=self.min_rr,
            stop_buffer_atr=self.stop_buffer_h1_atr,
            bos_body_atr=self.bos_body_atr,
            bos_close_location=self.bos_close_location,
            poi_distance_atr=self.poi_distance_atr,
            min_quality_score=self.min_quality_score,
            max_bos_age_minutes=self.max_bos_age_minutes,
            minimum_structural_strength=self.minimum_structural_strength,
        )


@dataclass(frozen=True)
class ExternalFta:
    symbol: str
    side: str
    price: float
    timeframe: str
    source: str
    strength: float
    confirmed_at: datetime


@dataclass(frozen=True)
class RouteSignalV3:
    name: str
    confirmation_time: datetime
    raid: RaidSignal | None
    volume_confirmation: VolumeConfirmationSignal | None
    vc_test: VcZoneTestSignal | None


@dataclass(frozen=True)
class PullbackSignalV3:
    bar: ClosedBar
    reference_price: float
    tolerance: float


@dataclass(frozen=True)
class StopSelectionV3:
    price: float
    anchor_price: float
    anchor_time: datetime
    source: str
    timeframe: str


@dataclass(frozen=True)
class FtaFirstPlan:
    symbol: str
    side: str
    evaluated_at: datetime
    state: FtaFirstState
    allowed: bool
    context: MtfContextSnapshot
    external_fta: ExternalFta | None
    poi: Level | None
    route: RouteSignalV3 | None
    bos: BosSignal | None
    pullback: PullbackSignalV3 | None
    stop_selection: StopSelectionV3 | None
    entry_time: datetime | None
    entry: float | None
    stop: float | None
    target: float | None
    rr: float | None
    quality_score: float
    event_blocked: bool
    event_risk_multiplier: float
    reasons: tuple[str, ...]


def _bars_asof(bars: Sequence[ClosedBar], symbol: str, timestamp: datetime) -> list[ClosedBar]:
    normalized = symbol.upper()
    return [bar for bar in bars if bar.symbol == normalized and bar.close_time <= timestamp]


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


def _reference_price(engine: MtfDealingRangeEngine, symbol: str, timestamp: datetime) -> float | None:
    for timeframe in ("15m", "1h", "4h"):
        rows = _bars_asof(engine.bars[timeframe], symbol, timestamp)
        if rows:
            return rows[-1].close
    return None


def directional_external_levels(
    levels: Sequence[Level],
    *,
    side: str,
    reference_price: float,
    timeframes: tuple[str, ...],
) -> list[ExternalFta]:
    output: list[ExternalFta] = []
    for level in levels:
        if level.timeframe not in timeframes or not level.fresh:
            continue
        if side == "long" and level.side == "resistance" and level.low > reference_price:
            output.append(
                ExternalFta(
                    symbol=level.symbol,
                    side=side,
                    price=level.low,
                    timeframe=level.timeframe,
                    source=level.source,
                    strength=level.strength,
                    confirmed_at=level.confirmed_at,
                )
            )
        elif side == "short" and level.side == "support" and level.high < reference_price:
            output.append(
                ExternalFta(
                    symbol=level.symbol,
                    side=side,
                    price=level.high,
                    timeframe=level.timeframe,
                    source=level.source,
                    strength=level.strength,
                    confirmed_at=level.confirmed_at,
                )
            )
    return output


def select_external_fta(
    engine: MtfDealingRangeEngine,
    symbol: str,
    timestamp: datetime,
    side: str,
    config: FtaFirstConfig,
) -> ExternalFta | None:
    reference_price = _reference_price(engine, symbol, timestamp)
    if reference_price is None:
        return None
    liquidity = build_liquidity_map(
        engine,
        symbol,
        timestamp,
        structural_timeframes=config.external_timeframes,
    )
    candidates = directional_external_levels(
        liquidity.levels,
        side=side,
        reference_price=reference_price,
        timeframes=config.external_timeframes,
    )
    if not candidates:
        return None
    if side == "long":
        return min(candidates, key=lambda item: (item.price - reference_price, -item.strength, item.timeframe, item.source))
    return min(candidates, key=lambda item: (reference_price - item.price, -item.strength, item.timeframe, item.source))


def _bar_touches_level(bar: ClosedBar, level: Level) -> bool:
    return bar.low <= level.high and bar.high >= level.low


def detect_route_v3(
    engine: MtfDealingRangeEngine,
    symbol: str,
    timestamp: datetime,
    side: str,
    poi: Level | None,
) -> RouteSignalV3 | None:
    if poi is None:
        return None
    h1_rows = _bars_asof(engine.bars["1h"], symbol, timestamp)
    raid = detect_h1_raid_signal(h1_rows, side, timestamp)
    raid_route = (
        RouteSignalV3("fresh_h1_raid", raid.raid_bar.close_time, raid, None, None)
        if raid is not None and _bar_touches_level(raid.raid_bar, poi)
        else None
    )

    vc = detect_h1_volume_confirmation(h1_rows, poi, side, timestamp)
    vc_test = detect_15m_vc_zone_test(engine.bars["15m"], vc, side, timestamp)
    vc_route = (
        RouteSignalV3("h1_vc_with_15m_test", vc_test.test_bar.close_time, None, vc, vc_test)
        if vc is not None and vc_test is not None
        else None
    )

    candidates = [item for item in (raid_route, vc_route) if item is not None]
    if not candidates:
        return None
    # The first causal route arms the structure. A same-time tie is resolved in
    # favour of the explicit liquidity raid, never by future outcome.
    return min(candidates, key=lambda item: (item.confirmation_time, 0 if item.name == "fresh_h1_raid" else 1))


def find_recent_bos_v3(
    engine: MtfDealingRangeEngine,
    symbol: str,
    timestamp: datetime,
    side: str,
    route: RouteSignalV3 | None,
    config: FtaFirstConfig,
) -> BosSignal | None:
    if route is None:
        return None
    window_start = max(
        route.confirmation_time,
        timestamp - timedelta(minutes=config.max_pullback_bars * 15 + config.max_bos_age_minutes),
    )
    candidates = [
        bar
        for bar in engine.bars["5m"]
        if bar.symbol == symbol.upper() and window_start <= bar.close_time <= timestamp
    ]
    found: list[BosSignal] = []
    v2_config = config.v2_entry_config()
    for bar in candidates:
        bos = detect_5m_bos(
            engine.bars["5m"],
            side,
            bar.close_time,
            v2_config,
            raid=route.raid,
            confirmation_time=route.confirmation_time,
        )
        if bos is not None and bos.signal_bar.close_time == bar.close_time:
            found.append(bos)
    if not found:
        return None
    return max(found, key=lambda item: item.signal_bar.close_time)


def find_closed_m15_pullback_v3(
    bars: Sequence[ClosedBar],
    *,
    symbol: str,
    side: str,
    timestamp: datetime,
    bos: BosSignal | None,
    h1_atr: float,
    config: FtaFirstConfig,
) -> PullbackSignalV3 | None:
    if bos is None:
        return None
    tolerance = h1_atr * config.pullback_tolerance_h1_atr
    rows = [
        bar
        for bar in bars
        if bar.symbol == symbol.upper()
        and bos.signal_bar.close_time < bar.close_time <= timestamp
    ]
    rows = rows[: config.max_pullback_bars]
    for bar in rows:
        touches = bar.low <= bos.pivot.price + tolerance and bar.high >= bos.pivot.price - tolerance
        directional_close = (
            bar.close > bar.open and bar.close >= bos.pivot.price
            if side == "long"
            else bar.close < bar.open and bar.close <= bos.pivot.price
        )
        if touches and directional_close:
            return PullbackSignalV3(bar=bar, reference_price=bos.pivot.price, tolerance=tolerance)
    return None


def find_next_entry_bar_v3(
    bars: Sequence[ClosedBar],
    *,
    symbol: str,
    timestamp: datetime,
    pullback: PullbackSignalV3 | None,
) -> ClosedBar | None:
    if pullback is None or pullback.bar.close_time != timestamp:
        return None
    if timestamp.second != 0 or timestamp.microsecond != 0 or timestamp.minute % 15 != 0:
        return None
    return next(
        (
            bar
            for bar in bars
            if bar.symbol == symbol.upper() and bar.open_time == timestamp
        ),
        None,
    )


def select_post_bos_stop_v3(
    engine: MtfDealingRangeEngine,
    *,
    symbol: str,
    side: str,
    entry: float,
    bos: BosSignal | None,
    pullback: PullbackSignalV3 | None,
    h1_atr: float,
    config: FtaFirstConfig,
) -> StopSelectionV3 | None:
    if bos is None or pullback is None:
        return None
    desired_kind = "low" if side == "long" else "high"
    buffer = h1_atr * config.stop_buffer_h1_atr
    for timeframe in ("5m", "15m"):
        rows = _bars_asof(engine.bars[timeframe], symbol, pullback.bar.close_time)
        pivots = [
            pivot
            for pivot in confirmed_pivots(rows, 2, 2)
            if pivot.kind == desired_kind
            and pivot.bar_open_time > bos.signal_bar.open_time
            and pivot.confirmed_at <= pullback.bar.close_time
            and (
                (side == "long" and pivot.price < entry)
                or (side == "short" and pivot.price > entry)
            )
        ]
        if pivots:
            pivot = max(pivots, key=lambda item: (item.confirmed_at, item.bar_open_time))
            price = pivot.price - buffer if side == "long" else pivot.price + buffer
            return StopSelectionV3(
                price=price,
                anchor_price=pivot.price,
                anchor_time=pivot.confirmed_at,
                source="post_bos_protected_swing",
                timeframe=timeframe,
            )

    anchor = pullback.bar.low if side == "long" else pullback.bar.high
    if (side == "long" and anchor >= entry) or (side == "short" and anchor <= entry):
        return None
    price = anchor - buffer if side == "long" else anchor + buffer
    return StopSelectionV3(
        price=price,
        anchor_price=anchor,
        anchor_time=pullback.bar.close_time,
        source="pullback_wick_fallback",
        timeframe="15m",
    )


def _structural_rr(side: str, entry: float, stop: float, target: float) -> float | None:
    risk = entry - stop if side == "long" else stop - entry
    reward = target - entry if side == "long" else entry - target
    if risk <= 0 or reward <= 0:
        return None
    return reward / risk


def _quality_score(
    context: MtfContextSnapshot,
    poi: Level | None,
    route: RouteSignalV3 | None,
    bos: BosSignal | None,
    pullback: PullbackSignalV3 | None,
    rr: float | None,
    event_multiplier: float,
) -> float:
    return min(
        100.0,
        context.scenario_strength * 0.30
        + (poi.strength if poi else 0.0) * 0.20
        + (15.0 if route else 0.0)
        + (bos.strength if bos else 0.0) * 0.20
        + (10.0 if pullback else 0.0)
        + (10.0 if rr is not None and rr >= 1.70 else 0.0)
        + 5.0 * max(0.0, min(1.0, event_multiplier)),
    )


class MtfFtaFirstEntryModelV3:
    def __init__(self, engine: MtfDealingRangeEngine, config: FtaFirstConfig | None = None):
        self.engine = engine
        self.config = config or FtaFirstConfig()

    def evaluate(
        self,
        symbol: str,
        timestamp: datetime,
        side: str,
        event_decision: EventRiskDecision | None = None,
    ) -> FtaFirstPlan:
        symbol = symbol.upper()
        side = side.lower()
        if side not in {"long", "short"}:
            raise ValueError("side must be long or short")

        context = self.engine.snapshot(symbol, timestamp)
        reasons: list[str] = []
        direction_allowed = context.long_allowed if side == "long" else context.short_allowed
        state = FtaFirstState.NO_CONTEXT
        if not direction_allowed:
            reasons.append(f"context_blocks_{side}:{context.scenario.value}")

        event_blocked = bool(event_decision and event_decision.block_new_entry)
        event_multiplier = event_decision.risk_multiplier if event_decision else 1.0
        if event_blocked:
            reasons.append("high_impact_event_blackout")

        external_fta = select_external_fta(self.engine, symbol, timestamp, side, self.config)
        if direction_allowed:
            state = FtaFirstState.WAIT_EXTERNAL_FTA
        if external_fta is None:
            reasons.append("no_active_external_fta")

        poi = find_active_poi(self.engine, symbol, timestamp, side, self.config.v2_entry_config())
        if external_fta is not None:
            state = FtaFirstState.WAIT_HTF_POI
        if poi is None:
            reasons.append("no_active_htf_poi")

        route = detect_route_v3(self.engine, symbol, timestamp, side, poi)
        if poi is not None:
            state = FtaFirstState.WAIT_H1_ROUTE
        if route is None:
            reasons.append("no_h1_raid_or_vc_test_route")

        # The target and POI must already have existed before the route armed.
        if route is not None and external_fta is not None and external_fta.confirmed_at > route.confirmation_time:
            reasons.append("external_fta_not_confirmed_before_route")
            external_fta = None
        if route is not None and poi is not None and poi.confirmed_at > route.confirmation_time:
            reasons.append("poi_not_confirmed_before_route")
            poi = None

        bos = find_recent_bos_v3(self.engine, symbol, timestamp, side, route, self.config)
        if route is not None:
            state = FtaFirstState.WAIT_5M_BOS
        if bos is None:
            reasons.append("no_confirmed_5m_bos_after_route")

        h1_rows = _bars_asof(self.engine.bars["1h"], symbol, timestamp)
        h1_atr = _atr(h1_rows) or ((_reference_price(self.engine, symbol, timestamp) or 0.0) * 0.005)
        pullback = find_closed_m15_pullback_v3(
            self.engine.bars["15m"],
            symbol=symbol,
            side=side,
            timestamp=timestamp,
            bos=bos,
            h1_atr=h1_atr,
            config=self.config,
        )
        if bos is not None:
            state = FtaFirstState.WAIT_15M_PULLBACK
        if pullback is None:
            reasons.append("no_closed_15m_pullback_to_bos_pivot")

        entry_bar = find_next_entry_bar_v3(
            self.engine.bars["15m"],
            symbol=symbol,
            timestamp=timestamp,
            pullback=pullback,
        )
        if pullback is not None:
            state = FtaFirstState.WAIT_NEXT_15M_OPEN
        entry = entry_bar.open if entry_bar is not None else None
        if pullback is not None and entry_bar is None:
            reasons.append("next_aligned_15m_open_not_available")

        stop_selection = (
            select_post_bos_stop_v3(
                self.engine,
                symbol=symbol,
                side=side,
                entry=entry,
                bos=bos,
                pullback=pullback,
                h1_atr=h1_atr,
                config=self.config,
            )
            if entry is not None
            else None
        )
        if entry is not None:
            state = FtaFirstState.WAIT_POST_BOS_STOP
        if entry is not None and stop_selection is None:
            reasons.append("no_valid_post_bos_structural_stop")

        target = external_fta.price if external_fta is not None else None
        stop = stop_selection.price if stop_selection is not None else None
        rr = (
            _structural_rr(side, entry, stop, target)
            if None not in (entry, stop, target)
            else None
        )
        rr_ok = rr is not None and rr >= self.config.min_rr
        if rr is not None and not rr_ok:
            reasons.append(f"rr_below_min:{rr:.4f}<{self.config.min_rr:.4f}")
            state = FtaFirstState.RR_BLOCKED
        elif entry is not None and rr is None:
            reasons.append("invalid_entry_stop_or_external_fta_geometry")
            state = FtaFirstState.RR_BLOCKED

        quality = _quality_score(context, poi, route, bos, pullback, rr, event_multiplier)
        quality_ok = quality >= self.config.min_quality_score
        if not quality_ok:
            reasons.append(f"quality_below_min:{quality:.4f}")
            if rr_ok:
                state = FtaFirstState.QUALITY_BLOCKED

        allowed = all(
            (
                direction_allowed,
                not event_blocked,
                external_fta is not None,
                poi is not None,
                route is not None,
                bos is not None,
                pullback is not None,
                entry is not None,
                stop_selection is not None,
                rr_ok,
                quality_ok,
            )
        )
        if allowed:
            state = FtaFirstState.ENTRY_READY
            reasons.append("fta_first_entry_ready_next_15m_open")

        return FtaFirstPlan(
            symbol=symbol,
            side=side,
            evaluated_at=timestamp,
            state=state,
            allowed=allowed,
            context=context,
            external_fta=external_fta,
            poi=poi,
            route=route,
            bos=bos,
            pullback=pullback,
            stop_selection=stop_selection,
            entry_time=timestamp if entry is not None else None,
            entry=round(entry, 8) if entry is not None else None,
            stop=round(stop, 8) if stop is not None else None,
            target=round(target, 8) if target is not None else None,
            rr=round(rr, 8) if rr is not None else None,
            quality_score=round(quality, 6),
            event_blocked=event_blocked,
            event_risk_multiplier=round(event_multiplier, 6),
            reasons=tuple(reasons),
        )


def independent_fingerprint(plan: FtaFirstPlan) -> str | None:
    if not plan.allowed:
        return None
    assert plan.external_fta and plan.route and plan.bos and plan.pullback and plan.stop_selection
    payload = {
        "symbol": plan.symbol,
        "side": plan.side,
        "external_fta": {
            "timeframe": plan.external_fta.timeframe,
            "source": plan.external_fta.source,
            "price": round(plan.external_fta.price, 8),
            "confirmed_at": plan.external_fta.confirmed_at.isoformat(),
        },
        "route": plan.route.name,
        "route_time": plan.route.confirmation_time.isoformat(),
        "bos_pivot_time": plan.bos.pivot.confirmed_at.isoformat(),
        "bos_signal_time": plan.bos.signal_bar.close_time.isoformat(),
        "pullback_time": plan.pullback.bar.close_time.isoformat(),
        "stop_anchor_time": plan.stop_selection.anchor_time.isoformat(),
        "stop_anchor_price": round(plan.stop_selection.anchor_price, 8),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def plan_to_no_pnl_dict(plan: FtaFirstPlan) -> dict[str, Any]:
    payload = asdict(plan)
    payload["state"] = plan.state.value
    payload["evaluated_at"] = plan.evaluated_at.isoformat()
    payload["context"] = {
        "scenario": plan.context.scenario.value,
        "scenario_strength": plan.context.scenario_strength,
        "long_allowed": plan.context.long_allowed,
        "short_allowed": plan.context.short_allowed,
        "reasons": list(plan.context.reasons),
    }
    for key in ("external_fta", "poi", "route", "bos", "pullback", "stop_selection"):
        value = payload.get(key)
        if value is not None:
            payload[key] = json.loads(json.dumps(value, default=lambda item: item.isoformat() if isinstance(item, datetime) else str(item)))
    payload["reasons"] = list(plan.reasons)
    payload["independent_fingerprint"] = independent_fingerprint(plan)
    return payload
