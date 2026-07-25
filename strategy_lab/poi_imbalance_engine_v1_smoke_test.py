#!/usr/bin/env python3
"""Semantic/regression tests for SMOKE CORE P1 POI/imbalance engine."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import unittest

from strategy_lab.mtf_dealing_range_v2 import ClosedBar
from strategy_lab.poi_imbalance_engine_v1 import (
    Direction,
    EvidenceRecord,
    EvidenceRelation,
    POIConfig,
    POIImbalanceEngine,
    POIScoreComponents,
    POISourceType,
    POIState,
    POIZone,
    cluster_evidence,
    enrich_zone,
    evaluate_zone_lifecycle,
    merge_composite_zones,
    snapshot_to_no_pnl_dict,
)


BASE = datetime(2026, 1, 1, 0, 0)


def bar(index: int, open_: float, high: float, low: float, close: float, volume: float = 100.0) -> ClosedBar:
    opened = BASE + timedelta(hours=index)
    return ClosedBar(
        symbol="BTCUSDT",
        timeframe="1h",
        open_time=opened,
        close_time=opened + timedelta(hours=1),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def components() -> POIScoreComponents:
    return POIScoreComponents(80, 70, 60, 100, 50, 50, 100)


def zone(
    *,
    poi_id: str = "poi-a",
    direction: Direction = Direction.LONG,
    low: float = 99.0,
    high: float = 100.0,
    origin_event_id: str = "origin-a",
    source: POISourceType = POISourceType.ORIGIN_OF_DISPLACEMENT,
) -> POIZone:
    base_components = components()
    return POIZone(
        poi_id=poi_id,
        symbol="BTCUSDT",
        timeframe="1h",
        source_type=source,
        low=low,
        high=high,
        core_low=low,
        core_high=high,
        direction=direction,
        state=POIState.CANDIDATE,
        formed_at=BASE,
        confirmed_at=BASE + timedelta(hours=1),
        last_test_at=None,
        mitigation_fraction=0.0,
        test_count=0,
        quality_0_100=base_components.total,
        score_components=base_components,
        evidence_ids=("ev-a",),
        evidence_cluster_ids=("cluster-a",),
        component_poi_ids=(),
        origin_event_id=origin_event_id,
        atr_at_formation=1.0,
        invalidation_rule="test",
    )


class POIImbalanceEngineSmokeTest(unittest.TestCase):
    def config(self) -> POIConfig:
        return POIConfig(
            atr_length=3,
            min_body_atr=0.45,
            min_range_atr=0.70,
            min_close_location=0.60,
            min_gap_atr=0.05,
            volume_lookback=3,
            merge_overlap_ratio=0.20,
        )

    def bullish_fixture(self) -> list[ClosedBar]:
        return [
            bar(0, 100.0, 100.4, 99.4, 99.7, 90),
            bar(1, 99.7, 100.1, 99.1, 99.3, 95),
            bar(2, 99.3, 100.0, 98.9, 99.0, 100),
            bar(3, 99.0, 105.0, 98.8, 104.7, 180),
            bar(4, 104.4, 105.2, 100.6, 104.9, 130),
            bar(5, 104.9, 106.0, 104.0, 105.5, 110),
        ]

    def bearish_fixture(self) -> list[ClosedBar]:
        return [
            bar(0, 100.0, 100.7, 99.7, 100.4, 90),
            bar(1, 100.4, 101.2, 100.1, 100.9, 95),
            bar(2, 100.9, 101.4, 100.6, 101.2, 100),
            bar(3, 101.2, 101.4, 95.0, 95.3, 185),
            bar(4, 95.6, 99.9, 94.8, 95.1, 125),
            bar(5, 95.1, 96.0, 93.9, 94.4, 110),
        ]

    def test_bullish_origin_and_fvg_are_detected(self) -> None:
        rows = self.bullish_fixture()
        snapshot = POIImbalanceEngine(self.config()).detect(rows, rows[-1].close_time)
        self.assertTrue(any(item.direction == Direction.LONG for item in snapshot.zones))
        sources = {item.source_type for item in snapshot.zones}
        self.assertIn(POISourceType.ORIGIN_OF_DISPLACEMENT, sources)
        self.assertIn(POISourceType.FVG_IMBALANCE, sources)

    def test_bearish_origin_and_fvg_are_detected(self) -> None:
        rows = self.bearish_fixture()
        snapshot = POIImbalanceEngine(self.config()).detect(rows, rows[-1].close_time)
        self.assertTrue(any(item.direction == Direction.SHORT for item in snapshot.zones))
        self.assertIn(POISourceType.FVG_IMBALANCE, {item.source_type for item in snapshot.zones})

    def test_no_retroactive_zone_before_confirmation(self) -> None:
        rows = self.bullish_fixture()
        asof = rows[3].close_time
        snapshot = POIImbalanceEngine(self.config()).detect(rows, asof)
        self.assertFalse(any(item.confirmed_at > asof for item in snapshot.zones))
        self.assertFalse(any(item.confirmed_at == rows[4].close_time for item in snapshot.zones))

    def test_same_input_produces_deterministic_ids(self) -> None:
        rows = self.bullish_fixture()
        engine = POIImbalanceEngine(self.config())
        first = engine.detect(rows, rows[-1].close_time)
        second = engine.detect(rows, rows[-1].close_time)
        self.assertEqual([item.poi_id for item in first.zones], [item.poi_id for item in second.zones])
        self.assertEqual([item.evidence_id for item in first.evidence], [item.evidence_id for item in second.evidence])

    def test_derived_fvg_and_volume_share_parent_cluster(self) -> None:
        rows = self.bullish_fixture()
        snapshot = POIImbalanceEngine(self.config()).detect(rows, rows[-1].close_time)
        cluster_events: dict[str, set[str]] = {}
        for item in snapshot.evidence:
            cluster_events.setdefault(item.cluster_id, set()).add(item.event_type)
        self.assertTrue(any("DISPLACEMENT_IMPULSE" in events and "FVG_IMBALANCE" in events for events in cluster_events.values()))
        self.assertTrue(all(item.relation != EvidenceRelation.INDEPENDENT for item in snapshot.evidence if item.parent_event_id))

    def test_cluster_uses_diminishing_return_and_cap(self) -> None:
        evidence = [
            EvidenceRecord("p", "c", None, "BTCUSDT", "1h", "IMPULSE", EvidenceRelation.PRIMARY, BASE, BASE, 99, 101, Direction.LONG, 25, {}),
            EvidenceRecord("d1", "c", "p", "BTCUSDT", "1h", "FVG", EvidenceRelation.DERIVED, BASE, BASE, 99, 100, Direction.LONG, 20, {}),
            EvidenceRecord("d2", "c", "p", "BTCUSDT", "1h", "VOLUME", EvidenceRelation.DERIVED, BASE, BASE, 99, 101, Direction.LONG, 20, {}),
        ]
        result = cluster_evidence(evidence, POIConfig(cluster_total_cap=30.0))[0]
        self.assertEqual(result.raw_primary_score, 25)
        self.assertEqual(result.raw_secondary_sum, 40)
        self.assertEqual(result.cluster_score_0_100, 30.0)

    def test_overlapping_same_origin_zones_merge(self) -> None:
        first = zone(poi_id="a", low=99.0, high=100.0, origin_event_id="same")
        second = zone(poi_id="b", low=99.5, high=100.4, origin_event_id="same", source=POISourceType.FVG_IMBALANCE)
        merged = merge_composite_zones([first, second], POIConfig(merge_overlap_ratio=0.20))
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source_type, POISourceType.COMPOSITE)
        self.assertEqual(set(merged[0].component_poi_ids), {"a", "b"})
        self.assertEqual((merged[0].core_low, merged[0].core_high), (99.5, 100.0))

    def test_opposite_direction_zones_do_not_merge(self) -> None:
        first = zone(poi_id="a", direction=Direction.LONG, origin_event_id="same")
        second = zone(poi_id="b", direction=Direction.SHORT, origin_event_id="same")
        self.assertEqual(len(merge_composite_zones([first, second])), 2)

    def test_lifecycle_active_without_touch(self) -> None:
        result = evaluate_zone_lifecycle(zone(), [bar(2, 101.0, 102.0, 100.5, 101.5)], BASE + timedelta(hours=3))
        self.assertEqual(result.state, POIState.ACTIVE)
        self.assertEqual(result.test_count, 0)

    def test_lifecycle_tested_on_shallow_touch(self) -> None:
        rows = [bar(2, 100.6, 101.0, 99.8, 100.5)]
        result = evaluate_zone_lifecycle(zone(), rows, rows[-1].close_time)
        self.assertEqual(result.state, POIState.TESTED)
        self.assertGreater(result.mitigation_fraction, 0)
        self.assertLess(result.mitigation_fraction, 0.5)

    def test_lifecycle_partially_mitigated_on_deep_touch(self) -> None:
        original = zone()
        rows = [bar(2, 100.5, 100.8, 99.3, 100.2)]
        result = evaluate_zone_lifecycle(original, rows, rows[-1].close_time)
        self.assertEqual(result.state, POIState.PARTIALLY_MITIGATED)
        self.assertGreaterEqual(result.mitigation_fraction, 0.5)
        self.assertLess(result.quality_0_100, original.quality_0_100)

    def test_lifecycle_requires_acceptance_for_invalidation(self) -> None:
        original = zone()
        one_close = [bar(2, 99.4, 99.6, 98.7, 98.8)]
        first = evaluate_zone_lifecycle(original, one_close, one_close[-1].close_time)
        self.assertNotEqual(first.state, POIState.INVALIDATED)
        two_closes = one_close + [bar(3, 98.8, 99.0, 98.2, 98.5)]
        second = evaluate_zone_lifecycle(original, two_closes, two_closes[-1].close_time)
        self.assertEqual(second.state, POIState.INVALIDATED)
        self.assertEqual(second.quality_0_100, 0.0)

    def test_external_location_and_liquidity_are_modifiers(self) -> None:
        original = zone()
        enriched = enrich_zone(original, location_score=90, liquidity_relation_score=85)
        self.assertGreater(enriched.quality_0_100, original.quality_0_100)
        self.assertEqual(enriched.score_components.location, 90)
        self.assertEqual(enriched.score_components.liquidity_relation, 85)

    def test_no_pnl_export_contains_no_outcome_fields(self) -> None:
        rows = self.bullish_fixture()
        snapshot = POIImbalanceEngine(self.config()).detect(rows, rows[-1].close_time)
        raw = json.dumps(snapshot_to_no_pnl_dict(snapshot)).lower()
        for forbidden in ("pnl", "future_return", "trade_outcome", "mfe", "mae", "profit_factor", "drawdown"):
            self.assertNotIn(f'"{forbidden}"', raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
