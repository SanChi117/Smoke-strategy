#!/usr/bin/env python3
"""SMOKE CORE 1.0 P3: causal price-interaction and anchor engine.

Recognition-only module. It links closed-candle interaction events to exact P1
POI ids and P2 liquidity level ids. It does not infer a relationship merely
because two events are temporally close, and it never reads trade outcomes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
from typing import Any, Iterable, Mapping, Sequence

from strategy_lab.context_liquidity_engine_v1 import (
    LiquidityLevelV1,
    LiquiditySide,
    LiquidityState,
)
from strategy_lab.mtf_dealing_range_v2 import ClosedBar
from strategy_lab.poi_imbalance_engine_v1 import Direction, POIState, POIZone


class InteractionKind(str, Enum):
    MITIGATION = "MITIGATION"
    SWEEP = "SWEEP"
    REJECTION = "REJECTION"
    ACCEPTANCE = "ACCEPTANCE"


class InteractionState(str, Enum):
    DISCOVERED = "DISCOVERED"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class AnchorKind(str, Enum):
    LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"
    POI_REJECTION = "POI_REJECTION"
    LEVEL_ACCEPTANCE = "LEVEL_ACCEPTANCE"


class RelationKind(str, Enum):
    INDUCEMENT_TO_REACTION = "INDUCEMENT_TO_REACTION"
    VICTIM_CANDLE_TO_REACTION = "VICTIM_CANDLE_TO_REACTION"


@dataclass(frozen=True)
class InteractionConfig:
    atr_length: int = 14
    zone_touch_buffer_atr: float = 0.03
    raid_min_excursion_atr: float = 0.03
    return_close_buffer_atr: float = 0.02
    acceptance_buffer_atr: float = 0.05
    acceptance_closes: int = 2
    rejection_wick_body_ratio: float = 1.50
    rejection_close_location: float = 0.60
    invalidation_buffer_atr: float = 0.05
    invalidation_closes: int = 2
    anchor_expiry_bars: int = 6
    inducement_max_age_bars: int = 12
    inducement_spatial_atr: float = 1.00

    def __post_init__(self) -> None:
        if self.atr_length < 2:
            raise ValueError("atr_length must be >= 2")
        if self.acceptance_closes < 2:
            raise ValueError("acceptance_closes must be >= 2")
        if self.invalidation_closes < 2:
            raise ValueError("invalidation_closes must be >= 2")
        if self.anchor_expiry_bars < 1:
            raise ValueError("anchor_expiry_bars must be >= 1")


@dataclass(frozen=True)
class InteractionEventV1:
    event_id: str
    symbol: str
    timeframe: str
    kind: InteractionKind
    direction: Direction
    state: InteractionState
    anchor_time: datetime
    confirmed_at: datetime
    valid_until: datetime
    low: float
    high: float
    source_poi_id: str | None
    source_liquidity_id: str | None
    source_evidence_ids: tuple[str, ...]
    evidence_cluster_ids: tuple[str, ...]
    strength_0_100: float
    atr_at_event: float
    victim_candle_time: datetime | None
    reason: str


@dataclass(frozen=True)
class InteractionRelationV1:
    relation_id: str
    symbol: str
    relation: RelationKind
    source_id: str
    target_event_id: str
    source_liquidity_id: str | None
    target_poi_id: str | None
    confirmed_at: datetime
    evidence_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class AnchorEventV1:
    anchor_id: str
    event_id: str
    symbol: str
    timeframe: str
    direction: Direction
    kind: AnchorKind
    state: InteractionState
    confirmed_at: datetime
    valid_until: datetime
    source_poi_id: str | None
    source_liquidity_id: str | None
    evidence_ids: tuple[str, ...]
    dependencies: tuple[str, ...]
    conflicts: tuple[str, ...]


@dataclass(frozen=True)
class InteractionSnapshotV1:
    symbol: str
    timeframe: str
    evaluated_at: datetime
    events: tuple[InteractionEventV1, ...]
    relations: tuple[InteractionRelationV1, ...]
    anchors: tuple[AnchorEventV1, ...]
    dependencies: tuple[str, ...]
    conflicts: tuple[str, ...]
    hard_block: bool
    hard_block_reason: str | None
    reasons: tuple[str, ...]


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


def _timeframe_delta(timeframe: str) -> timedelta:
    values = {
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1),
        "1w": timedelta(days=7),
    }
    return values.get(timeframe, timedelta(minutes=5))


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
    output: list[float | None] = []
    tr: list[float] = []
    for index in range(len(rows)):
        tr.append(_true_range(rows, index))
        output.append(sum(tr[-length:]) / length if len(tr) >= length else None)
    return output


def _bar_direction(bar: ClosedBar) -> Direction:
    if bar.close > bar.open:
        return Direction.LONG
    if bar.close < bar.open:
        return Direction.SHORT
    return Direction.NEUTRAL


def _touches(low: float, high: float, bar: ClosedBar, buffer_: float) -> bool:
    return bar.high >= low - buffer_ and bar.low <= high + buffer_


def _event(
    *,
    symbol: str,
    timeframe: str,
    kind: InteractionKind,
    direction: Direction,
    bar: ClosedBar,
    valid_until: datetime,
    source_poi_id: str | None,
    source_liquidity_id: str | None,
    source_evidence_ids: Iterable[str],
    evidence_cluster_ids: Iterable[str],
    strength: float,
    atr: float,
    victim_candle_time: datetime | None,
    reason: str,
) -> InteractionEventV1:
    event_id = _stable_id(
        "interaction",
        symbol,
        timeframe,
        kind.value,
        direction.value,
        bar.close_time.isoformat(),
        source_poi_id or "",
        source_liquidity_id or "",
    )
    return InteractionEventV1(
        event_id=event_id,
        symbol=symbol,
        timeframe=timeframe,
        kind=kind,
        direction=direction,
        state=InteractionState.CONFIRMED,
        anchor_time=bar.open_time,
        confirmed_at=bar.close_time,
        valid_until=valid_until,
        low=bar.low,
        high=bar.high,
        source_poi_id=source_poi_id,
        source_liquidity_id=source_liquidity_id,
        source_evidence_ids=tuple(sorted(set(source_evidence_ids))),
        evidence_cluster_ids=tuple(sorted(set(evidence_cluster_ids))),
        strength_0_100=round(_clamp(strength), 4),
        atr_at_event=max(1e-12, atr),
        victim_candle_time=victim_candle_time,
        reason=reason,
    )


def detect_liquidity_interactions(
    bars: Sequence[ClosedBar],
    levels: Sequence[LiquidityLevelV1],
    evaluated_at: datetime,
    config: InteractionConfig | None = None,
) -> tuple[InteractionEventV1, ...]:
    cfg = config or InteractionConfig()
    rows = sorted(
        [bar for bar in bars if bar.close_time <= evaluated_at],
        key=lambda item: item.close_time,
    )
    if not rows:
        return ()
    atrs = _atr_values(rows, cfg.atr_length)
    events: list[InteractionEventV1] = []
    for level in levels:
        if level.state == LiquidityState.INVALIDATED or level.confirmed_at > evaluated_at:
            continue
        acceptance_run = 0
        mitigation_emitted = False
        sweep_emitted = False
        acceptance_emitted = False
        for index, bar in enumerate(rows):
            if bar.close_time <= level.confirmed_at:
                continue
            atr = atrs[index] or max(level.price * 0.001, bar.high - bar.low, 1e-12)
            touch_buffer = atr * cfg.zone_touch_buffer_atr
            crossed = _touches(level.low, level.high, bar, touch_buffer)
            if crossed and not mitigation_emitted:
                direction = Direction.SHORT if level.side == LiquiditySide.BUY_SIDE else Direction.LONG
                events.append(
                    _event(
                        symbol=level.symbol,
                        timeframe=bar.timeframe,
                        kind=InteractionKind.MITIGATION,
                        direction=direction,
                        bar=bar,
                        valid_until=bar.close_time + _timeframe_delta(bar.timeframe) * cfg.anchor_expiry_bars,
                        source_poi_id=None,
                        source_liquidity_id=level.level_id,
                        source_evidence_ids=level.source_event_ids,
                        evidence_cluster_ids=(f"liq:{level.level_id}",),
                        strength=45.0 + min(20.0, level.strength_0_100 * 0.20),
                        atr=atr,
                        victim_candle_time=None,
                        reason="exact_liquidity_zone_touch",
                    )
                )
                mitigation_emitted = True

            if level.side == LiquiditySide.BUY_SIDE:
                sweep = (
                    bar.high >= level.high + atr * cfg.raid_min_excursion_atr
                    and bar.close <= level.high - atr * cfg.return_close_buffer_atr
                )
                accepted = bar.close >= level.high + atr * cfg.acceptance_buffer_atr
                event_direction = Direction.SHORT
                acceptance_direction = Direction.LONG
            else:
                sweep = (
                    bar.low <= level.low - atr * cfg.raid_min_excursion_atr
                    and bar.close >= level.low + atr * cfg.return_close_buffer_atr
                )
                accepted = bar.close <= level.low - atr * cfg.acceptance_buffer_atr
                event_direction = Direction.LONG
                acceptance_direction = Direction.SHORT

            if sweep and not sweep_emitted:
                excursion = (
                    (bar.high - level.high) / atr
                    if level.side == LiquiditySide.BUY_SIDE
                    else (level.low - bar.low) / atr
                )
                events.append(
                    _event(
                        symbol=level.symbol,
                        timeframe=bar.timeframe,
                        kind=InteractionKind.SWEEP,
                        direction=event_direction,
                        bar=bar,
                        valid_until=bar.close_time + _timeframe_delta(bar.timeframe) * cfg.anchor_expiry_bars,
                        source_poi_id=None,
                        source_liquidity_id=level.level_id,
                        source_evidence_ids=level.source_event_ids,
                        evidence_cluster_ids=(f"liq:{level.level_id}",),
                        strength=65.0 + min(25.0, excursion * 12.0),
                        atr=atr,
                        victim_candle_time=None,
                        reason="wick_beyond_exact_level_and_close_back",
                    )
                )
                sweep_emitted = True

            acceptance_run = acceptance_run + 1 if accepted else 0
            if acceptance_run >= cfg.acceptance_closes and not acceptance_emitted:
                events.append(
                    _event(
                        symbol=level.symbol,
                        timeframe=bar.timeframe,
                        kind=InteractionKind.ACCEPTANCE,
                        direction=acceptance_direction,
                        bar=bar,
                        valid_until=bar.close_time + _timeframe_delta(bar.timeframe) * cfg.anchor_expiry_bars,
                        source_poi_id=None,
                        source_liquidity_id=level.level_id,
                        source_evidence_ids=level.source_event_ids,
                        evidence_cluster_ids=(f"liq:{level.level_id}",),
                        strength=72.0 + min(18.0, level.strength_0_100 * 0.18),
                        atr=atr,
                        victim_candle_time=None,
                        reason=f"{cfg.acceptance_closes}_closed_candles_accepted_beyond_exact_level",
                    )
                )
                acceptance_emitted = True
    return tuple(sorted(events, key=lambda item: (item.confirmed_at, item.event_id)))


def _rejection_metrics(bar: ClosedBar, direction: Direction) -> tuple[float, float]:
    body = max(abs(bar.close - bar.open), 1e-12)
    span = max(bar.high - bar.low, 1e-12)
    if direction == Direction.LONG:
        wick = min(bar.open, bar.close) - bar.low
        close_location = (bar.close - bar.low) / span
    else:
        wick = bar.high - max(bar.open, bar.close)
        close_location = (bar.high - bar.close) / span
    return wick / body, close_location


def detect_poi_interactions(
    bars: Sequence[ClosedBar],
    pois: Sequence[POIZone],
    evaluated_at: datetime,
    config: InteractionConfig | None = None,
) -> tuple[InteractionEventV1, ...]:
    cfg = config or InteractionConfig()
    rows = sorted(
        [bar for bar in bars if bar.close_time <= evaluated_at],
        key=lambda item: item.close_time,
    )
    if not rows:
        return ()
    atrs = _atr_values(rows, cfg.atr_length)
    events: list[InteractionEventV1] = []
    for poi in pois:
        if poi.state == POIState.INVALIDATED or poi.confirmed_at > evaluated_at:
            continue
        mitigation_emitted = False
        rejection_emitted = False
        for index, bar in enumerate(rows):
            if bar.close_time <= poi.confirmed_at:
                continue
            atr = atrs[index] or max(poi.atr_at_formation, bar.high - bar.low, 1e-12)
            touch = _touches(poi.low, poi.high, bar, atr * cfg.zone_touch_buffer_atr)
            if not touch:
                continue
            if not mitigation_emitted:
                events.append(
                    _event(
                        symbol=poi.symbol,
                        timeframe=bar.timeframe,
                        kind=InteractionKind.MITIGATION,
                        direction=poi.direction,
                        bar=bar,
                        valid_until=bar.close_time + _timeframe_delta(bar.timeframe) * cfg.anchor_expiry_bars,
                        source_poi_id=poi.poi_id,
                        source_liquidity_id=None,
                        source_evidence_ids=poi.evidence_ids,
                        evidence_cluster_ids=poi.evidence_cluster_ids,
                        strength=45.0 + min(25.0, poi.quality_0_100 * 0.25),
                        atr=atr,
                        victim_candle_time=None,
                        reason="exact_poi_zone_touch",
                    )
                )
                mitigation_emitted = True

            wick_ratio, close_location = _rejection_metrics(bar, poi.direction)
            direction_close = (
                bar.close > bar.open
                if poi.direction == Direction.LONG
                else bar.close < bar.open
            )
            if (
                not rejection_emitted
                and direction_close
                and wick_ratio >= cfg.rejection_wick_body_ratio
                and close_location >= cfg.rejection_close_location
            ):
                victim_time: datetime | None = None
                if index > 0:
                    previous = rows[index - 1]
                    previous_touch = _touches(
                        poi.low,
                        poi.high,
                        previous,
                        atr * cfg.zone_touch_buffer_atr,
                    )
                    opposite = (
                        _bar_direction(previous) == Direction.SHORT
                        if poi.direction == Direction.LONG
                        else _bar_direction(previous) == Direction.LONG
                    )
                    if previous_touch and opposite:
                        victim_time = previous.close_time
                strength = 65.0 + min(15.0, wick_ratio * 4.0) + min(15.0, poi.quality_0_100 * 0.15)
                events.append(
                    _event(
                        symbol=poi.symbol,
                        timeframe=bar.timeframe,
                        kind=InteractionKind.REJECTION,
                        direction=poi.direction,
                        bar=bar,
                        valid_until=bar.close_time + _timeframe_delta(bar.timeframe) * cfg.anchor_expiry_bars,
                        source_poi_id=poi.poi_id,
                        source_liquidity_id=None,
                        source_evidence_ids=poi.evidence_ids,
                        evidence_cluster_ids=poi.evidence_cluster_ids,
                        strength=strength,
                        atr=atr,
                        victim_candle_time=victim_time,
                        reason="exact_poi_touch_with_directional_rejection",
                    )
                )
                rejection_emitted = True
    return tuple(sorted(events, key=lambda item: (item.confirmed_at, item.event_id)))


def _source_bounds(
    event: InteractionEventV1,
    pois: Mapping[str, POIZone],
    levels: Mapping[str, LiquidityLevelV1],
) -> tuple[float, float] | None:
    if event.source_poi_id and event.source_poi_id in pois:
        poi = pois[event.source_poi_id]
        return poi.low, poi.high
    if event.source_liquidity_id and event.source_liquidity_id in levels:
        level = levels[event.source_liquidity_id]
        return level.low, level.high
    return None


def apply_interaction_lifecycle(
    events: Sequence[InteractionEventV1],
    bars: Sequence[ClosedBar],
    pois: Sequence[POIZone],
    levels: Sequence[LiquidityLevelV1],
    evaluated_at: datetime,
    config: InteractionConfig | None = None,
) -> tuple[InteractionEventV1, ...]:
    cfg = config or InteractionConfig()
    rows = sorted(
        [bar for bar in bars if bar.close_time <= evaluated_at],
        key=lambda item: item.close_time,
    )
    poi_map = {item.poi_id: item for item in pois}
    level_map = {item.level_id: item for item in levels}
    output: list[InteractionEventV1] = []
    for event in events:
        state = event.state
        if evaluated_at > event.valid_until:
            state = InteractionState.EXPIRED
        bounds = _source_bounds(event, poi_map, level_map)
        after = [bar for bar in rows if bar.close_time > event.confirmed_at]
        if bounds and len(after) >= cfg.invalidation_closes:
            low, high = bounds
            buffer_ = event.atr_at_event * cfg.invalidation_buffer_atr
            tail = after[-cfg.invalidation_closes :]
            if event.direction == Direction.LONG:
                invalid = all(bar.close < low - buffer_ for bar in tail)
            else:
                invalid = all(bar.close > high + buffer_ for bar in tail)
            if invalid:
                state = InteractionState.INVALIDATED
        output.append(replace(event, state=state))
    return tuple(sorted(output, key=lambda item: (item.confirmed_at, item.event_id)))


def build_interaction_relations(
    events: Sequence[InteractionEventV1],
    pois: Sequence[POIZone],
    levels: Sequence[LiquidityLevelV1],
    config: InteractionConfig | None = None,
) -> tuple[InteractionRelationV1, ...]:
    cfg = config or InteractionConfig()
    poi_map = {item.poi_id: item for item in pois}
    level_map = {item.level_id: item for item in levels}
    output: list[InteractionRelationV1] = []
    reactions = [
        event
        for event in events
        if event.kind == InteractionKind.REJECTION and event.source_poi_id
    ]
    sweeps = [
        event
        for event in events
        if event.kind == InteractionKind.SWEEP and event.source_liquidity_id
    ]
    for reaction in reactions:
        poi = poi_map.get(reaction.source_poi_id or "")
        if poi is None:
            continue
        if reaction.victim_candle_time is not None:
            source_id = f"bar:{reaction.victim_candle_time.isoformat()}"
            output.append(
                InteractionRelationV1(
                    relation_id=_stable_id("relation", RelationKind.VICTIM_CANDLE_TO_REACTION.value, source_id, reaction.event_id),
                    symbol=reaction.symbol,
                    relation=RelationKind.VICTIM_CANDLE_TO_REACTION,
                    source_id=source_id,
                    target_event_id=reaction.event_id,
                    source_liquidity_id=None,
                    target_poi_id=poi.poi_id,
                    confirmed_at=reaction.confirmed_at,
                    evidence_ids=reaction.source_evidence_ids,
                    reason="opposite_closed_candle_touched_same_poi_immediately_before_rejection",
                )
            )

        candidates: list[tuple[datetime, InteractionEventV1]] = []
        for sweep in sweeps:
            if sweep.direction != reaction.direction or sweep.confirmed_at >= reaction.confirmed_at:
                continue
            level = level_map.get(sweep.source_liquidity_id or "")
            if level is None:
                continue
            max_age = _timeframe_delta(reaction.timeframe) * cfg.inducement_max_age_bars
            if reaction.confirmed_at - sweep.confirmed_at > max_age:
                continue
            distance = 0.0
            if level.price < poi.low:
                distance = poi.low - level.price
            elif level.price > poi.high:
                distance = level.price - poi.high
            if distance > reaction.atr_at_event * cfg.inducement_spatial_atr:
                continue
            candidates.append((sweep.confirmed_at, sweep))
        if candidates:
            _, sweep = max(candidates, key=lambda item: item[0])
            output.append(
                InteractionRelationV1(
                    relation_id=_stable_id(
                        "relation",
                        RelationKind.INDUCEMENT_TO_REACTION.value,
                        sweep.event_id,
                        reaction.event_id,
                    ),
                    symbol=reaction.symbol,
                    relation=RelationKind.INDUCEMENT_TO_REACTION,
                    source_id=sweep.event_id,
                    target_event_id=reaction.event_id,
                    source_liquidity_id=sweep.source_liquidity_id,
                    target_poi_id=poi.poi_id,
                    confirmed_at=reaction.confirmed_at,
                    evidence_ids=tuple(sorted(set(sweep.source_evidence_ids + reaction.source_evidence_ids))),
                    reason="prior_exact_liquidity_sweep_is_spatially_and_temporally_linked_to_poi_reaction",
                )
            )
    return tuple(sorted(output, key=lambda item: (item.confirmed_at, item.relation_id)))


def build_anchor_events(
    events: Sequence[InteractionEventV1],
) -> tuple[AnchorEventV1, ...]:
    output: list[AnchorEventV1] = []
    for event in events:
        if event.kind == InteractionKind.SWEEP:
            kind = AnchorKind.LIQUIDITY_SWEEP
        elif event.kind == InteractionKind.REJECTION:
            kind = AnchorKind.POI_REJECTION
        elif event.kind == InteractionKind.ACCEPTANCE:
            kind = AnchorKind.LEVEL_ACCEPTANCE
        else:
            continue
        dependencies = []
        if event.source_poi_id:
            dependencies.append(f"POI:{event.source_poi_id}")
        if event.source_liquidity_id:
            dependencies.append(f"LIQUIDITY:{event.source_liquidity_id}")
        output.append(
            AnchorEventV1(
                anchor_id=_stable_id("anchor", event.event_id, kind.value),
                event_id=event.event_id,
                symbol=event.symbol,
                timeframe=event.timeframe,
                direction=event.direction,
                kind=kind,
                state=event.state,
                confirmed_at=event.confirmed_at,
                valid_until=event.valid_until,
                source_poi_id=event.source_poi_id,
                source_liquidity_id=event.source_liquidity_id,
                evidence_ids=event.source_evidence_ids,
                dependencies=tuple(dependencies),
                conflicts=(),
            )
        )
    return tuple(sorted(output, key=lambda item: (item.confirmed_at, item.anchor_id)))


class InteractionEngineV1:
    """Build a deterministic outcome-blind P3 interaction snapshot."""

    def __init__(self, config: InteractionConfig | None = None):
        self.config = config or InteractionConfig()

    def snapshot(
        self,
        *,
        symbol: str,
        timeframe: str,
        bars: Sequence[ClosedBar],
        pois: Sequence[POIZone],
        levels: Sequence[LiquidityLevelV1],
        evaluated_at: datetime,
    ) -> InteractionSnapshotV1:
        symbol = symbol.upper()
        closed = tuple(
            sorted(
                [
                    bar
                    for bar in bars
                    if bar.symbol.upper() == symbol
                    and bar.timeframe == timeframe
                    and bar.close_time <= evaluated_at
                ],
                key=lambda item: item.close_time,
            )
        )
        source_pois = tuple(
            item
            for item in pois
            if item.symbol.upper() == symbol
            and item.confirmed_at <= evaluated_at
        )
        source_levels = tuple(
            item
            for item in levels
            if item.symbol.upper() == symbol
            and item.confirmed_at <= evaluated_at
        )
        if not closed:
            return InteractionSnapshotV1(
                symbol=symbol,
                timeframe=timeframe,
                evaluated_at=evaluated_at,
                events=(),
                relations=(),
                anchors=(),
                dependencies=("P1_POI", "P2_LIQUIDITY"),
                conflicts=(),
                hard_block=True,
                hard_block_reason="insufficient_closed_candles",
                reasons=("no_closed_candles_at_or_before_evaluated_at",),
            )
        if not source_pois and not source_levels:
            return InteractionSnapshotV1(
                symbol=symbol,
                timeframe=timeframe,
                evaluated_at=evaluated_at,
                events=(),
                relations=(),
                anchors=(),
                dependencies=("P1_POI", "P2_LIQUIDITY"),
                conflicts=(),
                hard_block=True,
                hard_block_reason="no_causal_interaction_sources",
                reasons=("no_confirmed_poi_or_liquidity_source",),
            )
        raw_events = (
            detect_liquidity_interactions(closed, source_levels, evaluated_at, self.config)
            + detect_poi_interactions(closed, source_pois, evaluated_at, self.config)
        )
        unique = {event.event_id: event for event in raw_events}
        events = apply_interaction_lifecycle(
            tuple(unique.values()),
            closed,
            source_pois,
            source_levels,
            evaluated_at,
            self.config,
        )
        relations = build_interaction_relations(events, source_pois, source_levels, self.config)
        anchors = build_anchor_events(events)
        reasons = (
            f"events={len(events)}",
            f"anchors={len(anchors)}",
            f"relations={len(relations)}",
        )
        return InteractionSnapshotV1(
            symbol=symbol,
            timeframe=timeframe,
            evaluated_at=evaluated_at,
            events=events,
            relations=relations,
            anchors=anchors,
            dependencies=("P1_POI", "P2_LIQUIDITY"),
            conflicts=(),
            hard_block=False,
            hard_block_reason=None,
            reasons=reasons,
        )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def snapshot_to_no_pnl_dict(snapshot: InteractionSnapshotV1) -> dict[str, Any]:
    payload = _jsonable(asdict(snapshot))
    raw_keys: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                raw_keys.append(str(key).lower())
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(payload)
    for key in raw_keys:
        if any(fragment in key for fragment in FORBIDDEN_KEY_FRAGMENTS):
            raise ValueError(f"forbidden outcome field in P3 export: {key}")
    return payload


__all__ = [
    "AnchorEventV1",
    "AnchorKind",
    "InteractionConfig",
    "InteractionEngineV1",
    "InteractionEventV1",
    "InteractionKind",
    "InteractionRelationV1",
    "InteractionSnapshotV1",
    "InteractionState",
    "RelationKind",
    "apply_interaction_lifecycle",
    "build_anchor_events",
    "build_interaction_relations",
    "detect_liquidity_interactions",
    "detect_poi_interactions",
    "snapshot_to_no_pnl_dict",
]
