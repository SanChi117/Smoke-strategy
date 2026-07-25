#!/usr/bin/env python3
"""SMOKE CORE 1.0 P1: causal POI / imbalance engine.

Recognition-only module. It uses closed bars, preserves evidence provenance,
prevents derived features from being counted as independent confirmations,
merges overlapping zones into deterministic composite POIs, and evaluates the
POI lifecycle without future trade outcomes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping, Sequence

from strategy_lab.mtf_dealing_range_v2 import ClosedBar, Pivot, confirmed_pivots


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class EvidenceRelation(str, Enum):
    PRIMARY = "PRIMARY"
    DERIVED = "DERIVED"
    INDEPENDENT = "INDEPENDENT"
    CONFLICTING = "CONFLICTING"


class POISourceType(str, Enum):
    ORIGIN_OF_DISPLACEMENT = "ORIGIN_OF_DISPLACEMENT"
    FVG_IMBALANCE = "FVG_IMBALANCE"
    MITIGATION_BREAKER = "MITIGATION_BREAKER"
    SR_FLIP = "SR_FLIP"
    COMPOSITE = "COMPOSITE"


class POIState(str, Enum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    TESTED = "TESTED"
    PARTIALLY_MITIGATED = "PARTIALLY_MITIGATED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    cluster_id: str
    parent_event_id: str | None
    symbol: str
    timeframe: str
    event_type: str
    relation: EvidenceRelation
    anchor_time: datetime
    confirmed_at: datetime
    low: float
    high: float
    direction: Direction
    strength_0_100: float
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class EvidenceCluster:
    cluster_id: str
    primary_evidence_id: str
    evidence_ids: tuple[str, ...]
    raw_primary_score: float
    raw_secondary_sum: float
    cluster_score_0_100: float


@dataclass(frozen=True)
class POIScoreComponents:
    displacement_strength: float
    structural_consequence: float
    imbalance_quality: float
    freshness: float
    location: float
    liquidity_relation: float
    age: float

    @property
    def total(self) -> float:
        weighted = (
            self.displacement_strength * 0.25
            + self.structural_consequence * 0.20
            + self.imbalance_quality * 0.15
            + self.freshness * 0.15
            + self.location * 0.10
            + self.liquidity_relation * 0.10
            + self.age * 0.05
        )
        return round(max(0.0, min(100.0, weighted)), 4)


@dataclass(frozen=True)
class POIZone:
    poi_id: str
    symbol: str
    timeframe: str
    source_type: POISourceType
    low: float
    high: float
    core_low: float
    core_high: float
    direction: Direction
    state: POIState
    formed_at: datetime
    confirmed_at: datetime
    last_test_at: datetime | None
    mitigation_fraction: float
    test_count: int
    quality_0_100: float
    score_components: POIScoreComponents
    evidence_ids: tuple[str, ...]
    evidence_cluster_ids: tuple[str, ...]
    component_poi_ids: tuple[str, ...]
    origin_event_id: str
    atr_at_formation: float
    invalidation_rule: str

    @property
    def width(self) -> float:
        return max(0.0, self.high - self.low)


@dataclass(frozen=True)
class POISnapshot:
    symbol: str
    timeframe: str
    evaluated_at: datetime
    zones: tuple[POIZone, ...]
    evidence: tuple[EvidenceRecord, ...]
    clusters: tuple[EvidenceCluster, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class POIConfig:
    atr_length: int = 14
    origin_lookback: int = 4
    min_body_atr: float = 0.55
    min_range_atr: float = 0.85
    min_close_location: float = 0.67
    min_gap_atr: float = 0.08
    volume_lookback: int = 20
    volume_expansion_ratio: float = 1.35
    origin_wick_fraction: float = 0.25
    merge_overlap_ratio: float = 0.20
    partial_mitigation_threshold: float = 0.50
    invalidation_closes: int = 2
    invalidation_buffer_atr: float = 0.05
    touch_freshness_penalty: float = 15.0
    mitigation_freshness_penalty: float = 50.0
    age_penalty_per_30_bars: float = 4.0
    composite_bonus_per_source: float = 4.0
    cluster_total_cap: float = 30.0

    def __post_init__(self) -> None:
        if self.atr_length < 2:
            raise ValueError("atr_length must be >= 2")
        if self.origin_lookback < 1:
            raise ValueError("origin_lookback must be >= 1")
        if not 0.0 <= self.min_close_location <= 1.0:
            raise ValueError("min_close_location must be in [0, 1]")
        if self.invalidation_closes < 1:
            raise ValueError("invalidation_closes must be >= 1")


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}_{sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _true_range(rows: Sequence[ClosedBar], index: int) -> float:
    bar = rows[index]
    if index == 0:
        return max(0.0, bar.high - bar.low)
    previous = rows[index - 1]
    return max(
        bar.high - bar.low,
        abs(bar.high - previous.close),
        abs(bar.low - previous.close),
    )


def _atr_series(rows: Sequence[ClosedBar], length: int) -> list[float | None]:
    output: list[float | None] = []
    tr_values: list[float] = []
    for index in range(len(rows)):
        tr_values.append(_true_range(rows, index))
        if len(tr_values) < length:
            output.append(None)
        else:
            output.append(sum(tr_values[-length:]) / length)
    return output


def _volume_ratio(rows: Sequence[ClosedBar], index: int, length: int) -> float:
    start = max(0, index - length)
    history = [row.volume for row in rows[start:index] if row.volume >= 0]
    if not history:
        return 1.0
    baseline = sum(history) / len(history)
    return rows[index].volume / max(1e-12, baseline)


def _close_location(bar: ClosedBar, direction: Direction) -> float:
    span = max(1e-12, bar.high - bar.low)
    if direction == Direction.LONG:
        return (bar.close - bar.low) / span
    if direction == Direction.SHORT:
        return (bar.high - bar.close) / span
    return 0.5


def _bar_direction(bar: ClosedBar) -> Direction:
    if bar.close > bar.open:
        return Direction.LONG
    if bar.close < bar.open:
        return Direction.SHORT
    return Direction.NEUTRAL


def _opposite(bar: ClosedBar, direction: Direction) -> bool:
    current = _bar_direction(bar)
    if direction == Direction.LONG:
        return current in (Direction.SHORT, Direction.NEUTRAL)
    if direction == Direction.SHORT:
        return current in (Direction.LONG, Direction.NEUTRAL)
    return False


def _overlap_ratio(left: POIZone, right: POIZone) -> float:
    overlap = max(0.0, min(left.high, right.high) - max(left.low, right.low))
    smaller = min(left.width, right.width)
    return 0.0 if smaller <= 0 else overlap / smaller


def _structural_consequence(
    pivots: Sequence[Pivot],
    impulse: ClosedBar,
    direction: Direction,
) -> tuple[bool, Pivot | None]:
    available = [pivot for pivot in pivots if pivot.confirmed_at <= impulse.open_time]
    if direction == Direction.LONG:
        pivots_for_side = [pivot for pivot in available if pivot.kind == "high"]
        pivot = max(pivots_for_side, key=lambda item: item.confirmed_at, default=None)
        return (pivot is not None and impulse.close > pivot.price), pivot
    pivots_for_side = [pivot for pivot in available if pivot.kind == "low"]
    pivot = max(pivots_for_side, key=lambda item: item.confirmed_at, default=None)
    return (pivot is not None and impulse.close < pivot.price), pivot


def _origin_cluster(
    rows: Sequence[ClosedBar],
    impulse_index: int,
    direction: Direction,
    lookback: int,
) -> list[ClosedBar]:
    output: list[ClosedBar] = []
    for index in range(impulse_index - 1, max(-1, impulse_index - lookback - 1), -1):
        current = rows[index]
        if not _opposite(current, direction):
            if output:
                break
            continue
        output.append(current)
    return sorted(output, key=lambda item: item.open_time)


def _origin_bounds(cluster: Sequence[ClosedBar], wick_fraction: float) -> tuple[float, float]:
    body_low = min(min(bar.open, bar.close) for bar in cluster)
    body_high = max(max(bar.open, bar.close) for bar in cluster)
    full_low = min(bar.low for bar in cluster)
    full_high = max(bar.high for bar in cluster)
    low = body_low - max(0.0, body_low - full_low) * wick_fraction
    high = body_high + max(0.0, full_high - body_high) * wick_fraction
    return low, high


def _make_evidence(
    *,
    cluster_id: str,
    parent_event_id: str | None,
    symbol: str,
    timeframe: str,
    event_type: str,
    relation: EvidenceRelation,
    anchor_time: datetime,
    confirmed_at: datetime,
    low: float,
    high: float,
    direction: Direction,
    strength: float,
    metadata: Mapping[str, Any],
) -> EvidenceRecord:
    evidence_id = _stable_id(
        "ev",
        symbol,
        timeframe,
        event_type,
        relation.value,
        anchor_time.isoformat(),
        confirmed_at.isoformat(),
        round(low, 12),
        round(high, 12),
        direction.value,
        parent_event_id,
    )
    return EvidenceRecord(
        evidence_id=evidence_id,
        cluster_id=cluster_id,
        parent_event_id=parent_event_id,
        symbol=symbol,
        timeframe=timeframe,
        event_type=event_type,
        relation=relation,
        anchor_time=anchor_time,
        confirmed_at=confirmed_at,
        low=low,
        high=high,
        direction=direction,
        strength_0_100=round(_clamp(strength), 4),
        metadata=dict(metadata),
    )


def cluster_evidence(
    evidence: Iterable[EvidenceRecord],
    config: POIConfig | None = None,
) -> tuple[EvidenceCluster, ...]:
    cfg = config or POIConfig()
    grouped: dict[str, list[EvidenceRecord]] = {}
    for item in evidence:
        grouped.setdefault(item.cluster_id, []).append(item)
    output: list[EvidenceCluster] = []
    for cluster_id, records in sorted(grouped.items()):
        ordered = sorted(records, key=lambda item: (item.relation.value, item.evidence_id))
        primaries = [item for item in ordered if item.relation == EvidenceRelation.PRIMARY]
        primary = max(primaries or ordered, key=lambda item: item.strength_0_100)
        secondary = [item for item in ordered if item.evidence_id != primary.evidence_id]
        secondary_sum = sum(item.strength_0_100 for item in secondary)
        score = min(cfg.cluster_total_cap, primary.strength_0_100 + 0.35 * secondary_sum)
        output.append(
            EvidenceCluster(
                cluster_id=cluster_id,
                primary_evidence_id=primary.evidence_id,
                evidence_ids=tuple(item.evidence_id for item in ordered),
                raw_primary_score=round(primary.strength_0_100, 4),
                raw_secondary_sum=round(secondary_sum, 4),
                cluster_score_0_100=round(score, 4),
            )
        )
    return tuple(output)


def _score_components(
    *,
    body_atr: float,
    range_atr: float,
    structure_broken: bool,
    gap_atr: float,
    volume_ratio: float,
    source: POISourceType,
    location_score: float = 50.0,
    liquidity_relation_score: float = 50.0,
) -> POIScoreComponents:
    displacement = _clamp(body_atr * 45.0 + range_atr * 20.0 + max(0.0, volume_ratio - 1.0) * 15.0)
    structural = 90.0 if structure_broken else 45.0
    imbalance = (
        _clamp(gap_atr * 180.0 + body_atr * 20.0)
        if source == POISourceType.FVG_IMBALANCE
        else _clamp(gap_atr * 70.0 + body_atr * 10.0)
    )
    return POIScoreComponents(
        displacement_strength=round(displacement, 4),
        structural_consequence=round(structural, 4),
        imbalance_quality=round(imbalance, 4),
        freshness=100.0,
        location=round(_clamp(location_score), 4),
        liquidity_relation=round(_clamp(liquidity_relation_score), 4),
        age=100.0,
    )


def _zone(
    *,
    symbol: str,
    timeframe: str,
    source_type: POISourceType,
    low: float,
    high: float,
    direction: Direction,
    formed_at: datetime,
    confirmed_at: datetime,
    evidence_ids: Sequence[str],
    cluster_ids: Sequence[str],
    origin_event_id: str,
    atr_at_formation: float,
    components: POIScoreComponents,
) -> POIZone:
    if high <= low:
        raise ValueError("POI high must be greater than low")
    poi_id = _stable_id(
        "poi",
        symbol,
        timeframe,
        source_type.value,
        direction.value,
        formed_at.isoformat(),
        confirmed_at.isoformat(),
        round(low, 12),
        round(high, 12),
        origin_event_id,
    )
    return POIZone(
        poi_id=poi_id,
        symbol=symbol,
        timeframe=timeframe,
        source_type=source_type,
        low=low,
        high=high,
        core_low=low,
        core_high=high,
        direction=direction,
        state=POIState.CANDIDATE,
        formed_at=formed_at,
        confirmed_at=confirmed_at,
        last_test_at=None,
        mitigation_fraction=0.0,
        test_count=0,
        quality_0_100=components.total,
        score_components=components,
        evidence_ids=tuple(sorted(set(evidence_ids))),
        evidence_cluster_ids=tuple(sorted(set(cluster_ids))),
        component_poi_ids=(),
        origin_event_id=origin_event_id,
        atr_at_formation=atr_at_formation,
        invalidation_rule="two_closed_bars_outside_zone_with_atr_buffer",
    )


def merge_composite_zones(
    zones: Sequence[POIZone],
    config: POIConfig | None = None,
) -> tuple[POIZone, ...]:
    cfg = config or POIConfig()
    pending = sorted(zones, key=lambda item: (item.symbol, item.timeframe, item.direction.value, item.low, item.high, item.poi_id))
    output: list[POIZone] = []
    used: set[str] = set()
    for zone in pending:
        if zone.poi_id in used:
            continue
        group = [zone]
        used.add(zone.poi_id)
        changed = True
        while changed:
            changed = False
            for candidate in pending:
                if candidate.poi_id in used:
                    continue
                if candidate.symbol != zone.symbol or candidate.timeframe != zone.timeframe or candidate.direction != zone.direction:
                    continue
                related_origin = any(item.origin_event_id == candidate.origin_event_id for item in group)
                overlaps = any(_overlap_ratio(item, candidate) >= cfg.merge_overlap_ratio for item in group)
                if related_origin and overlaps:
                    group.append(candidate)
                    used.add(candidate.poi_id)
                    changed = True
        if len(group) == 1:
            output.append(zone)
            continue
        low = min(item.low for item in group)
        high = max(item.high for item in group)
        core_low = max(item.low for item in group)
        core_high = min(item.high for item in group)
        if core_high <= core_low:
            core_low, core_high = low, high
        strongest = max(group, key=lambda item: item.quality_0_100)
        components = POIScoreComponents(
            displacement_strength=max(item.score_components.displacement_strength for item in group),
            structural_consequence=max(item.score_components.structural_consequence for item in group),
            imbalance_quality=max(item.score_components.imbalance_quality for item in group),
            freshness=min(item.score_components.freshness for item in group),
            location=max(item.score_components.location for item in group),
            liquidity_relation=max(item.score_components.liquidity_relation for item in group),
            age=min(item.score_components.age for item in group),
        )
        quality = min(100.0, max(item.quality_0_100 for item in group) + cfg.composite_bonus_per_source * (len(group) - 1))
        origin_ids = sorted({item.origin_event_id for item in group})
        output.append(
            POIZone(
                poi_id=_stable_id("poi", zone.symbol, zone.timeframe, POISourceType.COMPOSITE.value, zone.direction.value, *(sorted(item.poi_id for item in group))),
                symbol=zone.symbol,
                timeframe=zone.timeframe,
                source_type=POISourceType.COMPOSITE,
                low=low,
                high=high,
                core_low=core_low,
                core_high=core_high,
                direction=zone.direction,
                state=POIState.CANDIDATE,
                formed_at=min(item.formed_at for item in group),
                confirmed_at=max(item.confirmed_at for item in group),
                last_test_at=None,
                mitigation_fraction=0.0,
                test_count=0,
                quality_0_100=round(max(quality, components.total), 4),
                score_components=components,
                evidence_ids=tuple(sorted({eid for item in group for eid in item.evidence_ids})),
                evidence_cluster_ids=tuple(sorted({cid for item in group for cid in item.evidence_cluster_ids})),
                component_poi_ids=tuple(sorted(item.poi_id for item in group)),
                origin_event_id=_stable_id("origin_group", *origin_ids),
                atr_at_formation=strongest.atr_at_formation,
                invalidation_rule="two_closed_bars_outside_composite_envelope_with_atr_buffer",
            )
        )
    return tuple(sorted(output, key=lambda item: (item.confirmed_at, item.low, item.poi_id)))


def _mitigation_fraction(zone: POIZone, bar: ClosedBar) -> float:
    width = max(1e-12, zone.width)
    if bar.low > zone.high or bar.high < zone.low:
        return 0.0
    if zone.direction == Direction.LONG:
        deepest = max(zone.low, min(zone.high, bar.low))
        return _clamp((zone.high - deepest) / width, 0.0, 1.0)
    deepest = min(zone.high, max(zone.low, bar.high))
    return _clamp((deepest - zone.low) / width, 0.0, 1.0)


def evaluate_zone_lifecycle(
    zone: POIZone,
    bars: Sequence[ClosedBar],
    asof: datetime,
    config: POIConfig | None = None,
) -> POIZone:
    cfg = config or POIConfig()
    if asof < zone.confirmed_at:
        return replace(zone, state=POIState.CANDIDATE)
    rows = sorted(
        (
            bar
            for bar in bars
            if bar.symbol == zone.symbol
            and bar.timeframe == zone.timeframe
            and zone.confirmed_at < bar.close_time <= asof
        ),
        key=lambda item: item.close_time,
    )
    touches = 0
    max_mitigation = 0.0
    last_test: datetime | None = None
    outside_run = 0
    invalidated = False
    buffer = zone.atr_at_formation * cfg.invalidation_buffer_atr
    for current in rows:
        fraction = _mitigation_fraction(zone, current)
        if fraction > 0.0:
            touches += 1
            max_mitigation = max(max_mitigation, fraction)
            last_test = current.close_time
        outside = (
            current.close < zone.low - buffer
            if zone.direction == Direction.LONG
            else current.close > zone.high + buffer
        )
        outside_run = outside_run + 1 if outside else 0
        if outside_run >= cfg.invalidation_closes:
            invalidated = True
            break
    if invalidated:
        state = POIState.INVALIDATED
    elif touches == 0:
        state = POIState.ACTIVE
    elif max_mitigation >= cfg.partial_mitigation_threshold:
        state = POIState.PARTIALLY_MITIGATED
    else:
        state = POIState.TESTED
    freshness = _clamp(100.0 - touches * cfg.touch_freshness_penalty - max_mitigation * cfg.mitigation_freshness_penalty)
    age_score = _clamp(100.0 - (len(rows) / 30.0) * cfg.age_penalty_per_30_bars)
    components = replace(zone.score_components, freshness=round(freshness, 4), age=round(age_score, 4))
    return replace(
        zone,
        state=state,
        last_test_at=last_test,
        mitigation_fraction=round(max_mitigation, 6),
        test_count=touches,
        quality_0_100=0.0 if invalidated else components.total,
        score_components=components,
    )


def enrich_zone(
    zone: POIZone,
    *,
    location_score: float | None = None,
    liquidity_relation_score: float | None = None,
) -> POIZone:
    components = replace(
        zone.score_components,
        location=zone.score_components.location if location_score is None else round(_clamp(location_score), 4),
        liquidity_relation=(
            zone.score_components.liquidity_relation
            if liquidity_relation_score is None
            else round(_clamp(liquidity_relation_score), 4)
        ),
    )
    return replace(zone, score_components=components, quality_0_100=components.total)


class POIImbalanceEngine:
    """Detect and maintain causal POI/imbalance zones for one timeframe."""

    def __init__(self, config: POIConfig | None = None):
        self.config = config or POIConfig()

    def detect(self, bars: Sequence[ClosedBar], asof: datetime) -> POISnapshot:
        rows = sorted((bar for bar in bars if bar.close_time <= asof), key=lambda item: item.close_time)
        if not rows:
            return POISnapshot("", "", asof, (), (), (), ("NO_CLOSED_BARS",))
        symbols = {bar.symbol for bar in rows}
        timeframes = {bar.timeframe for bar in rows}
        if len(symbols) != 1 or len(timeframes) != 1:
            raise ValueError("POIImbalanceEngine.detect requires one symbol and one timeframe")
        symbol = rows[0].symbol
        timeframe = rows[0].timeframe
        atr_values = _atr_series(rows, self.config.atr_length)
        pivots = confirmed_pivots(rows, 2, 2)
        evidence: list[EvidenceRecord] = []
        raw_zones: list[POIZone] = []
        reasons: list[str] = []

        for index in range(2, len(rows)):
            impulse = rows[index - 1]
            right = rows[index]
            atr = atr_values[index - 1]
            if atr is None or atr <= 0.0:
                continue
            direction = _bar_direction(impulse)
            if direction == Direction.NEUTRAL:
                continue
            body = abs(impulse.close - impulse.open)
            span = impulse.high - impulse.low
            body_atr = body / atr
            range_atr = span / atr
            close_location = _close_location(impulse, direction)
            if body_atr < self.config.min_body_atr or range_atr < self.config.min_range_atr or close_location < self.config.min_close_location:
                continue
            left = rows[index - 2]
            gap_low: float | None = None
            gap_high: float | None = None
            if direction == Direction.LONG and right.low > left.high:
                gap_low, gap_high = left.high, right.low
            elif direction == Direction.SHORT and right.high < left.low:
                gap_low, gap_high = right.high, left.low
            gap_atr = 0.0 if gap_low is None else (gap_high - gap_low) / atr
            structure_broken, broken_pivot = _structural_consequence(pivots, impulse, direction)
            volume_ratio = _volume_ratio(rows, index - 1, self.config.volume_lookback)
            origin = _origin_cluster(rows, index - 1, direction, self.config.origin_lookback)
            if not origin:
                reasons.append(f"NO_ORIGIN:{impulse.close_time.isoformat()}")
                continue

            origin_event_id = _stable_id("origin", symbol, timeframe, direction.value, origin[0].open_time.isoformat(), impulse.close_time.isoformat())
            cluster_id = _stable_id("cluster", origin_event_id)
            origin_low, origin_high = _origin_bounds(origin, self.config.origin_wick_fraction)
            impulse_strength = _clamp(body_atr * 45.0 + range_atr * 20.0 + close_location * 20.0)
            primary = _make_evidence(
                cluster_id=cluster_id,
                parent_event_id=None,
                symbol=symbol,
                timeframe=timeframe,
                event_type="DISPLACEMENT_IMPULSE",
                relation=EvidenceRelation.PRIMARY,
                anchor_time=impulse.open_time,
                confirmed_at=right.close_time,
                low=impulse.low,
                high=impulse.high,
                direction=direction,
                strength=impulse_strength,
                metadata={"body_atr": round(body_atr, 6), "range_atr": round(range_atr, 6), "close_location": round(close_location, 6), "volume_ratio": round(volume_ratio, 6)},
            )
            origin_ev = _make_evidence(
                cluster_id=cluster_id,
                parent_event_id=primary.evidence_id,
                symbol=symbol,
                timeframe=timeframe,
                event_type="ORIGIN_CLUSTER",
                relation=EvidenceRelation.DERIVED,
                anchor_time=origin[0].open_time,
                confirmed_at=right.close_time,
                low=origin_low,
                high=origin_high,
                direction=direction,
                strength=_clamp(45.0 + len(origin) * 8.0),
                metadata={"bar_count": len(origin)},
            )
            event_evidence = [primary, origin_ev]
            if structure_broken and broken_pivot is not None:
                event_evidence.append(
                    _make_evidence(
                        cluster_id=cluster_id,
                        parent_event_id=primary.evidence_id,
                        symbol=symbol,
                        timeframe=timeframe,
                        event_type="STRUCTURAL_CONSEQUENCE",
                        relation=EvidenceRelation.DERIVED,
                        anchor_time=broken_pivot.bar_open_time,
                        confirmed_at=right.close_time,
                        low=broken_pivot.price,
                        high=broken_pivot.price,
                        direction=direction,
                        strength=85.0,
                        metadata={"pivot_id": _stable_id("pivot", broken_pivot.confirmed_at, broken_pivot.price)},
                    )
                )
            if volume_ratio >= self.config.volume_expansion_ratio:
                event_evidence.append(
                    _make_evidence(
                        cluster_id=cluster_id,
                        parent_event_id=primary.evidence_id,
                        symbol=symbol,
                        timeframe=timeframe,
                        event_type="VOLUME_EXPANSION",
                        relation=EvidenceRelation.DERIVED,
                        anchor_time=impulse.open_time,
                        confirmed_at=right.close_time,
                        low=impulse.low,
                        high=impulse.high,
                        direction=direction,
                        strength=_clamp(50.0 + (volume_ratio - 1.0) * 25.0),
                        metadata={"volume_ratio": round(volume_ratio, 6)},
                    )
                )
            evidence.extend(event_evidence)
            origin_components = _score_components(
                body_atr=body_atr,
                range_atr=range_atr,
                structure_broken=structure_broken,
                gap_atr=gap_atr,
                volume_ratio=volume_ratio,
                source=POISourceType.ORIGIN_OF_DISPLACEMENT,
            )
            raw_zones.append(
                _zone(
                    symbol=symbol,
                    timeframe=timeframe,
                    source_type=POISourceType.ORIGIN_OF_DISPLACEMENT,
                    low=origin_low,
                    high=origin_high,
                    direction=direction,
                    formed_at=origin[0].open_time,
                    confirmed_at=right.close_time,
                    evidence_ids=[item.evidence_id for item in event_evidence],
                    cluster_ids=[cluster_id],
                    origin_event_id=origin_event_id,
                    atr_at_formation=atr,
                    components=origin_components,
                )
            )
            if gap_low is not None and gap_atr >= self.config.min_gap_atr:
                fvg_ev = _make_evidence(
                    cluster_id=cluster_id,
                    parent_event_id=primary.evidence_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    event_type="FVG_IMBALANCE",
                    relation=EvidenceRelation.DERIVED,
                    anchor_time=impulse.open_time,
                    confirmed_at=right.close_time,
                    low=gap_low,
                    high=gap_high,
                    direction=direction,
                    strength=_clamp(gap_atr * 180.0 + body_atr * 20.0),
                    metadata={"gap_atr": round(gap_atr, 6)},
                )
                evidence.append(fvg_ev)
                raw_zones.append(
                    _zone(
                        symbol=symbol,
                        timeframe=timeframe,
                        source_type=POISourceType.FVG_IMBALANCE,
                        low=gap_low,
                        high=gap_high,
                        direction=direction,
                        formed_at=impulse.open_time,
                        confirmed_at=right.close_time,
                        evidence_ids=[primary.evidence_id, fvg_ev.evidence_id],
                        cluster_ids=[cluster_id],
                        origin_event_id=origin_event_id,
                        atr_at_formation=atr,
                        components=_score_components(
                            body_atr=body_atr,
                            range_atr=range_atr,
                            structure_broken=structure_broken,
                            gap_atr=gap_atr,
                            volume_ratio=volume_ratio,
                            source=POISourceType.FVG_IMBALANCE,
                        ),
                    )
                )

        composites = merge_composite_zones(raw_zones, self.config)
        lifecycle = tuple(evaluate_zone_lifecycle(zone, rows, asof, self.config) for zone in composites)
        return POISnapshot(
            symbol=symbol,
            timeframe=timeframe,
            evaluated_at=asof,
            zones=tuple(sorted(lifecycle, key=lambda item: (item.confirmed_at, item.poi_id))),
            evidence=tuple(sorted(evidence, key=lambda item: (item.confirmed_at, item.evidence_id))),
            clusters=cluster_evidence(evidence, self.config),
            reasons=tuple(sorted(set(reasons))),
        )


def snapshot_to_no_pnl_dict(snapshot: POISnapshot) -> dict[str, Any]:
    def convert(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Mapping):
            return {str(key): convert(child) for key, child in value.items()}
        if isinstance(value, (tuple, list)):
            return [convert(child) for child in value]
        if hasattr(value, "__dataclass_fields__"):
            return convert(asdict(value))
        return value

    payload = convert(snapshot)
    forbidden = ("pnl", "future_return", "trade_outcome", "tp_result", "sl_result", "mfe", "mae", "profit_factor", "net_return", "drawdown", "exit_price")
    raw = json.dumps(payload, sort_keys=True).lower()
    for fragment in forbidden:
        if f'"{fragment}"' in raw:
            raise AssertionError(f"forbidden outcome field in POI snapshot: {fragment}")
    return payload


__all__ = [
    "Direction",
    "EvidenceCluster",
    "EvidenceRecord",
    "EvidenceRelation",
    "POIConfig",
    "POIImbalanceEngine",
    "POIScoreComponents",
    "POISnapshot",
    "POISourceType",
    "POIState",
    "POIZone",
    "cluster_evidence",
    "enrich_zone",
    "evaluate_zone_lifecycle",
    "merge_composite_zones",
    "snapshot_to_no_pnl_dict",
]
