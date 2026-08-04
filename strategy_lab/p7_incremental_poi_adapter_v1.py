#!/usr/bin/env python3
"""Exact causal incremental POI adapter for the frozen P7 recognition scan.

The frozen P1 engine is intentionally left unchanged. This adapter reproduces
the same P1 zones and evidence at every closed native timeframe bar, but updates
them incrementally instead of re-running the complete historical detector for
every hourly P7 decision boundary.

Only execution topology changes. POI definitions, evidence, scores, lifecycle,
causal confirmation times and outcome-blind constraints remain unchanged.
"""
from __future__ import annotations

from collections import ChainMap
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Mapping, Sequence

import strategy_lab.poi_imbalance_engine_v1 as p1
from strategy_lab.mtf_dealing_range_v2 import ClosedBar, confirmed_pivots


@dataclass(frozen=True)
class _ImpulseSeed:
    index: int
    direction: p1.Direction
    body_atr: float
    range_atr: float
    structure_broken: bool
    volume_ratio: float
    origin: tuple[ClosedBar, ...]
    origin_low: float
    origin_high: float
    origin_event_id: str
    cluster_id: str
    atr: float
    event_evidence: tuple[p1.EvidenceRecord, ...]


@dataclass
class _ZoneRuntime:
    zone: p1.POIZone
    touches: int = 0
    max_mitigation: float = 0.0
    last_test_at: datetime | None = None
    outside_run: int = 0
    age_bars: int = 0
    invalidated: bool = False

    def advance(self, bar: ClosedBar, config: p1.POIConfig) -> None:
        if self.invalidated or bar.close_time <= self.zone.confirmed_at:
            return

        self.age_bars += 1
        fraction = p1._mitigation_fraction(self.zone, bar)
        if fraction > 0.0:
            self.touches += 1
            self.max_mitigation = max(self.max_mitigation, fraction)
            self.last_test_at = bar.close_time

        buffer = self.zone.atr_at_formation * config.invalidation_buffer_atr
        outside = (
            bar.close < self.zone.low - buffer
            if self.zone.direction == p1.Direction.LONG
            else bar.close > self.zone.high + buffer
        )
        self.outside_run = self.outside_run + 1 if outside else 0
        if self.outside_run >= config.invalidation_closes:
            self.invalidated = True

    def materialize(self, config: p1.POIConfig) -> p1.POIZone:
        if self.invalidated:
            return replace(
                self.zone,
                state=p1.POIState.INVALIDATED,
                last_test_at=self.last_test_at,
                mitigation_fraction=round(self.max_mitigation, 6),
                test_count=self.touches,
                quality_0_100=0.0,
            )

        if self.touches == 0:
            state = p1.POIState.ACTIVE
        elif self.max_mitigation >= config.partial_mitigation_threshold:
            state = p1.POIState.PARTIALLY_MITIGATED
        else:
            state = p1.POIState.TESTED

        freshness = p1._clamp(
            100.0
            - self.touches * config.touch_freshness_penalty
            - self.max_mitigation * config.mitigation_freshness_penalty
        )
        age_score = p1._clamp(
            100.0 - (self.age_bars / 30.0) * config.age_penalty_per_30_bars
        )
        components = replace(
            self.zone.score_components,
            freshness=round(freshness, 4),
            age=round(age_score, 4),
        )
        return replace(
            self.zone,
            state=state,
            last_test_at=self.last_test_at,
            mitigation_fraction=round(self.max_mitigation, 6),
            test_count=self.touches,
            quality_0_100=round(components.total, 4),
            score_components=components,
        )


class IncrementalPOITimeframeStream:
    """Causally advance one native timeframe and expose exact active P1 state."""

    def __init__(
        self,
        bars: Sequence[ClosedBar],
        config: p1.POIConfig | None = None,
    ):
        self.config = config or p1.POIConfig()
        self.rows = tuple(sorted(bars, key=lambda item: item.close_time))
        if self.rows:
            symbols = {bar.symbol for bar in self.rows}
            timeframes = {bar.timeframe for bar in self.rows}
            if len(symbols) != 1 or len(timeframes) != 1:
                raise ValueError("incremental POI stream requires one symbol/timeframe")
        self.atr_values = p1._atr_series(self.rows, self.config.atr_length)
        self.pivots = tuple(confirmed_pivots(self.rows, 2, 2))
        self.cursor = 0
        self.last_asof: datetime | None = None
        self.seeds: dict[int, _ImpulseSeed] = {}
        self.raw_by_origin: dict[str, list[p1.POIZone]] = {}
        self.runtime_by_origin: dict[str, dict[str, _ZoneRuntime]] = {}
        self.evidence_by_id: dict[str, p1.EvidenceRecord] = {}

    def _build_seed(self, index: int) -> tuple[_ImpulseSeed, p1.POIZone] | None:
        if index < 1:
            return None
        impulse = self.rows[index]
        atr = self.atr_values[index]
        if atr is None or atr <= 0.0:
            return None

        direction = p1._bar_direction(impulse)
        if direction == p1.Direction.NEUTRAL:
            return None

        body = abs(impulse.close - impulse.open)
        span = impulse.high - impulse.low
        body_atr = body / atr
        range_atr = span / atr
        close_location = p1._close_location(impulse, direction)
        if (
            body_atr < self.config.min_body_atr
            or range_atr < self.config.min_range_atr
            or close_location < self.config.min_close_location
        ):
            return None

        structure_broken, broken_pivot = p1._structural_consequence(
            self.pivots, impulse, direction
        )
        volume_ratio = p1._volume_ratio(
            self.rows, index, self.config.volume_lookback
        )
        origin = tuple(
            p1._origin_cluster(
                self.rows, index, direction, self.config.origin_lookback
            )
        )
        if not origin:
            return None

        origin_event_id = p1._stable_id(
            "origin",
            impulse.symbol,
            impulse.timeframe,
            direction.value,
            origin[0].open_time.isoformat(),
            impulse.close_time.isoformat(),
        )
        cluster_id = p1._stable_id("cluster", origin_event_id)
        origin_low, origin_high = p1._origin_bounds(
            origin, self.config.origin_wick_fraction
        )
        impulse_strength = p1._clamp(
            body_atr * 45.0 + range_atr * 20.0 + close_location * 20.0
        )
        primary = p1._make_evidence(
            cluster_id=cluster_id,
            parent_event_id=None,
            symbol=impulse.symbol,
            timeframe=impulse.timeframe,
            event_type="DISPLACEMENT_IMPULSE",
            relation=p1.EvidenceRelation.PRIMARY,
            anchor_time=impulse.open_time,
            confirmed_at=impulse.close_time,
            low=impulse.low,
            high=impulse.high,
            direction=direction,
            strength=impulse_strength,
            metadata={
                "body_atr": round(body_atr, 6),
                "range_atr": round(range_atr, 6),
                "close_location": round(close_location, 6),
                "volume_ratio": round(volume_ratio, 6),
            },
        )
        origin_evidence = p1._make_evidence(
            cluster_id=cluster_id,
            parent_event_id=primary.evidence_id,
            symbol=impulse.symbol,
            timeframe=impulse.timeframe,
            event_type="ORIGIN_CLUSTER",
            relation=p1.EvidenceRelation.DERIVED,
            anchor_time=origin[0].open_time,
            confirmed_at=impulse.close_time,
            low=origin_low,
            high=origin_high,
            direction=direction,
            strength=p1._clamp(45.0 + len(origin) * 8.0),
            metadata={"bar_count": len(origin)},
        )
        event_evidence = [primary, origin_evidence]

        if structure_broken and broken_pivot is not None:
            event_evidence.append(
                p1._make_evidence(
                    cluster_id=cluster_id,
                    parent_event_id=primary.evidence_id,
                    symbol=impulse.symbol,
                    timeframe=impulse.timeframe,
                    event_type="STRUCTURAL_CONSEQUENCE",
                    relation=p1.EvidenceRelation.DERIVED,
                    anchor_time=broken_pivot.bar_open_time,
                    confirmed_at=impulse.close_time,
                    low=broken_pivot.price,
                    high=broken_pivot.price,
                    direction=direction,
                    strength=85.0,
                    metadata={
                        "pivot_id": p1._stable_id(
                            "pivot",
                            broken_pivot.confirmed_at,
                            broken_pivot.price,
                        )
                    },
                )
            )
        if volume_ratio >= self.config.volume_expansion_ratio:
            event_evidence.append(
                p1._make_evidence(
                    cluster_id=cluster_id,
                    parent_event_id=primary.evidence_id,
                    symbol=impulse.symbol,
                    timeframe=impulse.timeframe,
                    event_type="VOLUME_EXPANSION",
                    relation=p1.EvidenceRelation.DERIVED,
                    anchor_time=impulse.open_time,
                    confirmed_at=impulse.close_time,
                    low=impulse.low,
                    high=impulse.high,
                    direction=direction,
                    strength=p1._clamp(
                        50.0 + (volume_ratio - 1.0) * 25.0
                    ),
                    metadata={"volume_ratio": round(volume_ratio, 6)},
                )
            )

        seed = _ImpulseSeed(
            index=index,
            direction=direction,
            body_atr=body_atr,
            range_atr=range_atr,
            structure_broken=structure_broken,
            volume_ratio=volume_ratio,
            origin=origin,
            origin_low=origin_low,
            origin_high=origin_high,
            origin_event_id=origin_event_id,
            cluster_id=cluster_id,
            atr=atr,
            event_evidence=tuple(event_evidence),
        )
        origin_zone = self._origin_zone(seed, gap_atr=0.0)
        return seed, origin_zone

    def _origin_zone(
        self,
        seed: _ImpulseSeed,
        *,
        gap_atr: float,
    ) -> p1.POIZone:
        impulse = self.rows[seed.index]
        return p1._zone(
            symbol=impulse.symbol,
            timeframe=impulse.timeframe,
            source_type=p1.POISourceType.ORIGIN_OF_DISPLACEMENT,
            low=seed.origin_low,
            high=seed.origin_high,
            direction=seed.direction,
            formed_at=seed.origin[0].open_time,
            confirmed_at=impulse.close_time,
            evidence_ids=[
                item.evidence_id for item in seed.event_evidence
            ],
            cluster_ids=[seed.cluster_id],
            origin_event_id=seed.origin_event_id,
            atr_at_formation=seed.atr,
            components=p1._score_components(
                body_atr=seed.body_atr,
                range_atr=seed.range_atr,
                structure_broken=seed.structure_broken,
                gap_atr=gap_atr,
                volume_ratio=seed.volume_ratio,
                source=p1.POISourceType.ORIGIN_OF_DISPLACEMENT,
            ),
        )

    def _finalize_right_bar(
        self,
        seed: _ImpulseSeed,
        right_index: int,
    ) -> tuple[p1.POIZone, p1.POIZone | None, p1.EvidenceRecord | None]:
        impulse_index = seed.index
        if right_index != impulse_index + 1:
            raise AssertionError("right-bar finalization is not adjacent")
        left = self.rows[impulse_index - 1]
        impulse = self.rows[impulse_index]
        right = self.rows[right_index]

        gap_low: float | None = None
        gap_high: float | None = None
        if seed.direction == p1.Direction.LONG and right.low > left.high:
            gap_low, gap_high = left.high, right.low
        elif seed.direction == p1.Direction.SHORT and right.high < left.low:
            gap_low, gap_high = right.high, left.low

        gap_atr = (
            0.0
            if gap_low is None or gap_high is None
            else (gap_high - gap_low) / seed.atr
        )
        origin_zone = self._origin_zone(seed, gap_atr=gap_atr)
        if (
            gap_low is None
            or gap_high is None
            or gap_atr < self.config.min_gap_atr
        ):
            return origin_zone, None, None

        primary = seed.event_evidence[0]
        fvg_evidence = p1._make_evidence(
            cluster_id=seed.cluster_id,
            parent_event_id=primary.evidence_id,
            symbol=impulse.symbol,
            timeframe=impulse.timeframe,
            event_type="FVG_IMBALANCE",
            relation=p1.EvidenceRelation.DERIVED,
            anchor_time=impulse.open_time,
            confirmed_at=right.close_time,
            low=gap_low,
            high=gap_high,
            direction=seed.direction,
            strength=p1._clamp(
                gap_atr * 180.0 + seed.body_atr * 20.0
            ),
            metadata={"gap_atr": round(gap_atr, 6)},
        )
        fvg_zone = p1._zone(
            symbol=impulse.symbol,
            timeframe=impulse.timeframe,
            source_type=p1.POISourceType.FVG_IMBALANCE,
            low=gap_low,
            high=gap_high,
            direction=seed.direction,
            formed_at=impulse.open_time,
            confirmed_at=right.close_time,
            evidence_ids=[
                primary.evidence_id,
                fvg_evidence.evidence_id,
            ],
            cluster_ids=[seed.cluster_id],
            origin_event_id=seed.origin_event_id,
            atr_at_formation=seed.atr,
            components=p1._score_components(
                body_atr=seed.body_atr,
                range_atr=seed.range_atr,
                structure_broken=seed.structure_broken,
                gap_atr=gap_atr,
                volume_ratio=seed.volume_ratio,
                source=p1.POISourceType.FVG_IMBALANCE,
            ),
        )
        return origin_zone, fvg_zone, fvg_evidence

    def _replace_origin_zones(
        self,
        origin_event_id: str,
        zones: Sequence[p1.POIZone],
    ) -> None:
        self.raw_by_origin[origin_event_id] = list(zones)
        merged = p1.merge_composite_zones(
            self.raw_by_origin[origin_event_id],
            self.config,
        )
        previous = self.runtime_by_origin.get(origin_event_id, {})
        updated: dict[str, _ZoneRuntime] = {}
        for zone in merged:
            runtime = previous.get(zone.poi_id)
            if runtime is None:
                runtime = _ZoneRuntime(zone=zone)
            else:
                runtime.zone = zone
            updated[zone.poi_id] = runtime
        self.runtime_by_origin[origin_event_id] = updated

    def _process_index(self, index: int) -> None:
        current = self.rows[index]
        changed: dict[str, list[p1.POIZone]] = {}

        built = self._build_seed(index)
        if built is not None:
            seed, origin_zone = built
            self.seeds[index] = seed
            changed[seed.origin_event_id] = [origin_zone]
            for item in seed.event_evidence:
                self.evidence_by_id[item.evidence_id] = item

        previous_seed = self.seeds.get(index - 1)
        if previous_seed is not None:
            origin_zone, fvg_zone, fvg_evidence = self._finalize_right_bar(
                previous_seed,
                index,
            )
            zones = [origin_zone]
            if fvg_zone is not None:
                zones.append(fvg_zone)
            changed[previous_seed.origin_event_id] = zones
            if fvg_evidence is not None:
                self.evidence_by_id[
                    fvg_evidence.evidence_id
                ] = fvg_evidence

        for origin_event_id, zones in changed.items():
            self._replace_origin_zones(origin_event_id, zones)

        for runtimes in self.runtime_by_origin.values():
            for runtime in runtimes.values():
                runtime.advance(current, self.config)

    def advance(
        self,
        asof: datetime,
    ) -> tuple[tuple[p1.POIZone, ...], Mapping[str, p1.EvidenceRecord]]:
        if self.last_asof is not None and asof < self.last_asof:
            raise ValueError("incremental POI stream requires monotonic asof")
        self.last_asof = asof
        while (
            self.cursor < len(self.rows)
            and self.rows[self.cursor].close_time <= asof
        ):
            self._process_index(self.cursor)
            self.cursor += 1

        zones = [
            runtime.materialize(self.config)
            for runtimes in self.runtime_by_origin.values()
            for runtime in runtimes.values()
            if not runtime.invalidated
        ]
        zones.sort(key=lambda item: (item.confirmed_at, item.poi_id))
        return tuple(zones), self.evidence_by_id


class IncrementalPOIProvider:
    """Combine exact incremental 1h and 4h P1 streams for one P7 symbol."""

    def __init__(self, engine: Any):
        self.streams = tuple(
            IncrementalPOITimeframeStream(engine.bars[timeframe])
            for timeframe in ("1h", "4h")
        )

    def advance(
        self,
        asof: datetime,
    ) -> tuple[tuple[p1.POIZone, ...], Mapping[str, p1.EvidenceRecord]]:
        zones: list[p1.POIZone] = []
        evidence_maps: list[Mapping[str, p1.EvidenceRecord]] = []
        for stream in self.streams:
            stream_zones, evidence = stream.advance(asof)
            zones.extend(stream_zones)
            evidence_maps.append(evidence)

        unique = {zone.poi_id: zone for zone in zones}
        ordered = tuple(
            sorted(
                unique.values(),
                key=lambda zone: (zone.confirmed_at, zone.poi_id),
            )
        )
        return ordered, ChainMap(*evidence_maps)


def install_incremental_poi_adapter(runner_module: Any) -> None:
    """Patch only the P7 runner's POI retrieval topology."""
    if getattr(runner_module, "_p7_incremental_poi_installed", False):
        return

    providers: dict[int, IncrementalPOIProvider] = {}

    def _active_pois(
        engine: Any,
        timestamp: datetime,
        _unused_poi_engine: Any,
    ) -> tuple[
        tuple[p1.POIZone, ...],
        Mapping[str, p1.EvidenceRecord],
    ]:
        key = id(engine)
        provider = providers.get(key)
        if provider is None:
            provider = IncrementalPOIProvider(engine)
            providers[key] = provider
        return provider.advance(timestamp)

    runner_module._active_pois = _active_pois
    runner_module._p7_incremental_poi_installed = True


__all__ = [
    "IncrementalPOIProvider",
    "IncrementalPOITimeframeStream",
    "install_incremental_poi_adapter",
]
