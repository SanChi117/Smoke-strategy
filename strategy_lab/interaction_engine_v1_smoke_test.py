#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta
import json
import unittest

from strategy_lab.context_liquidity_engine_v1 import (
    LiquidityKind,
    LiquidityLevelV1,
    LiquiditySide,
    LiquidityState,
)
from strategy_lab.interaction_engine_v1 import (
    AnchorKind,
    InteractionConfig,
    InteractionEngineV1,
    InteractionKind,
    InteractionState,
    RelationKind,
    apply_interaction_lifecycle,
    build_anchor_events,
    build_interaction_relations,
    detect_liquidity_interactions,
    detect_poi_interactions,
    snapshot_to_no_pnl_dict,
)
from strategy_lab.mtf_dealing_range_v2 import ClosedBar
from strategy_lab.poi_imbalance_engine_v1 import (
    Direction,
    POIScoreComponents,
    POISourceType,
    POIState,
    POIZone,
)

BASE = datetime(2026, 1, 1, 0, 0)


def bar(index: int, open_: float, high: float, low: float, close: float) -> ClosedBar:
    opened = BASE + timedelta(minutes=5 * index)
    return ClosedBar(
        "BTCUSDT",
        "5m",
        opened,
        opened + timedelta(minutes=5),
        open_,
        high,
        low,
        close,
        100.0,
    )


def level(
    *,
    level_id: str = "liq-1",
    side: LiquiditySide = LiquiditySide.BUY_SIDE,
    price: float = 101.0,
) -> LiquidityLevelV1:
    return LiquidityLevelV1(
        level_id=level_id,
        symbol="BTCUSDT",
        timeframe="1h",
        kind=LiquidityKind.SWING_HIGH if side == LiquiditySide.BUY_SIDE else LiquidityKind.SWING_LOW,
        side=side,
        low=price,
        high=price,
        formed_at=BASE - timedelta(hours=1),
        confirmed_at=BASE,
        state=LiquidityState.FRESH,
        strength_0_100=75.0,
        touch_count=0,
        swept_at=None,
        invalidated_at=None,
        source="fixture",
        source_event_ids=(f"evidence:{level_id}",),
        external=True,
    )


def poi(
    *,
    poi_id: str = "poi-1",
    direction: Direction = Direction.LONG,
    low: float = 99.5,
    high: float = 100.5,
) -> POIZone:
    components = POIScoreComponents(
        displacement_strength=80,
        structural_consequence=75,
        imbalance_quality=70,
        freshness=90,
        location=70,
        liquidity_relation=65,
        age=95,
    )
    return POIZone(
        poi_id=poi_id,
        symbol="BTCUSDT",
        timeframe="1h",
        source_type=POISourceType.ORIGIN_OF_DISPLACEMENT,
        low=low,
        high=high,
        core_low=low + (high - low) * 0.25,
        core_high=high - (high - low) * 0.25,
        direction=direction,
        state=POIState.ACTIVE,
        formed_at=BASE - timedelta(hours=1),
        confirmed_at=BASE,
        last_test_at=None,
        mitigation_fraction=0.0,
        test_count=0,
        quality_0_100=80.0,
        score_components=components,
        evidence_ids=(f"evidence:{poi_id}",),
        evidence_cluster_ids=(f"cluster:{poi_id}",),
        component_poi_ids=(),
        origin_event_id=f"origin:{poi_id}",
        atr_at_formation=1.0,
        invalidation_rule="two_closes_beyond_zone",
    )


class InteractionEngineV1SmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = InteractionConfig(atr_length=2)

    def test_buy_side_sweep_creates_short_event_with_exact_level_id(self) -> None:
        rows = [bar(1, 100.0, 101.3, 99.8, 100.8)]
        events = detect_liquidity_interactions(rows, [level()], rows[-1].close_time, self.cfg)
        sweep = next(item for item in events if item.kind == InteractionKind.SWEEP)
        self.assertEqual(sweep.direction, Direction.SHORT)
        self.assertEqual(sweep.source_liquidity_id, "liq-1")

    def test_sell_side_sweep_creates_long_event(self) -> None:
        rows = [bar(1, 99.5, 99.7, 98.6, 99.3)]
        events = detect_liquidity_interactions(
            rows,
            [level(side=LiquiditySide.SELL_SIDE, price=99.0)],
            rows[-1].close_time,
            self.cfg,
        )
        sweep = next(item for item in events if item.kind == InteractionKind.SWEEP)
        self.assertEqual(sweep.direction, Direction.LONG)

    def test_nearby_bar_without_exact_cross_creates_no_sweep(self) -> None:
        rows = [bar(1, 100.0, 100.7, 99.8, 100.5)]
        events = detect_liquidity_interactions(rows, [level(price=105.0)], rows[-1].close_time, self.cfg)
        self.assertFalse(any(item.kind == InteractionKind.SWEEP for item in events))

    def test_acceptance_requires_two_closed_candles(self) -> None:
        source = level(price=101.0)
        one = [bar(1, 101.0, 101.4, 100.9, 101.2)]
        first = detect_liquidity_interactions(one, [source], one[-1].close_time, self.cfg)
        self.assertFalse(any(item.kind == InteractionKind.ACCEPTANCE for item in first))
        two = one + [bar(2, 101.2, 101.5, 101.1, 101.3)]
        second = detect_liquidity_interactions(two, [source], two[-1].close_time, self.cfg)
        acceptance = next(item for item in second if item.kind == InteractionKind.ACCEPTANCE)
        self.assertEqual(acceptance.direction, Direction.LONG)

    def test_poi_rejection_requires_exact_touch_and_wick_quality(self) -> None:
        rows = [
            bar(1, 100.2, 100.3, 99.6, 99.8),
            bar(2, 100.0, 100.4, 99.2, 100.3),
        ]
        events = detect_poi_interactions(rows, [poi()], rows[-1].close_time, self.cfg)
        rejection = next(item for item in events if item.kind == InteractionKind.REJECTION)
        self.assertEqual(rejection.source_poi_id, "poi-1")
        self.assertEqual(rejection.direction, Direction.LONG)

    def test_victim_candle_is_linked_only_when_it_touches_same_poi(self) -> None:
        rows = [
            bar(1, 100.2, 100.3, 99.6, 99.8),
            bar(2, 100.0, 100.4, 99.2, 100.3),
        ]
        source_poi = poi()
        events = detect_poi_interactions(rows, [source_poi], rows[-1].close_time, self.cfg)
        relations = build_interaction_relations(events, [source_poi], [], self.cfg)
        relation = next(item for item in relations if item.relation == RelationKind.VICTIM_CANDLE_TO_REACTION)
        self.assertEqual(relation.target_poi_id, source_poi.poi_id)

    def test_poi_mitigation_is_not_itself_an_anchor(self) -> None:
        rows = [bar(1, 100.0, 100.2, 99.7, 100.05)]
        events = detect_poi_interactions(rows, [poi()], rows[-1].close_time, self.cfg)
        anchors = build_anchor_events(events)
        self.assertFalse(any(item.event_id == events[0].event_id for item in anchors))

    def test_rejection_anchor_preserves_exact_poi_dependency(self) -> None:
        rows = [
            bar(1, 100.2, 100.3, 99.6, 99.8),
            bar(2, 100.0, 100.4, 99.2, 100.3),
        ]
        events = detect_poi_interactions(rows, [poi()], rows[-1].close_time, self.cfg)
        anchors = build_anchor_events(events)
        anchor = next(item for item in anchors if item.kind == AnchorKind.POI_REJECTION)
        self.assertEqual(anchor.source_poi_id, "poi-1")
        self.assertIn("POI:poi-1", anchor.dependencies)

    def test_inducement_requires_spatial_and_temporal_link(self) -> None:
        source_level = level(level_id="sell-liq", side=LiquiditySide.SELL_SIDE, price=99.0)
        source_poi = poi(low=99.4, high=100.4)
        sweep_rows = [bar(1, 99.4, 99.6, 98.6, 99.3)]
        sweep_events = detect_liquidity_interactions(
            sweep_rows,
            [source_level],
            sweep_rows[-1].close_time,
            self.cfg,
        )
        reaction_rows = [
            bar(2, 100.2, 100.3, 99.6, 99.8),
            bar(3, 100.0, 100.4, 99.2, 100.3),
        ]
        reaction_events = detect_poi_interactions(
            reaction_rows,
            [source_poi],
            reaction_rows[-1].close_time,
            self.cfg,
        )
        relations = build_interaction_relations(
            sweep_events + reaction_events,
            [source_poi],
            [source_level],
            self.cfg,
        )
        self.assertTrue(any(item.relation == RelationKind.INDUCEMENT_TO_REACTION for item in relations))

    def test_far_liquidity_is_not_arbitrarily_linked_as_inducement(self) -> None:
        far_level = level(level_id="far", side=LiquiditySide.SELL_SIDE, price=90.0)
        source_poi = poi(low=99.4, high=100.4)
        sweep_rows = [bar(1, 90.5, 90.6, 89.5, 90.3)]
        sweep_events = detect_liquidity_interactions(
            sweep_rows,
            [far_level],
            sweep_rows[-1].close_time,
            self.cfg,
        )
        reaction_rows = [
            bar(2, 100.2, 100.3, 99.6, 99.8),
            bar(3, 100.0, 100.4, 99.2, 100.3),
        ]
        reaction_events = detect_poi_interactions(
            reaction_rows,
            [source_poi],
            reaction_rows[-1].close_time,
            self.cfg,
        )
        relations = build_interaction_relations(
            sweep_events + reaction_events,
            [source_poi],
            [far_level],
            self.cfg,
        )
        self.assertFalse(any(item.relation == RelationKind.INDUCEMENT_TO_REACTION for item in relations))

    def test_interaction_expires_after_frozen_bar_window(self) -> None:
        source = level()
        rows = [bar(1, 100.0, 101.3, 99.8, 100.8)]
        events = detect_liquidity_interactions(rows, [source], rows[-1].close_time, self.cfg)
        later = rows + [bar(i, 100.2, 100.5, 99.9, 100.1) for i in range(2, 10)]
        updated = apply_interaction_lifecycle(
            events,
            later,
            [],
            [source],
            later[-1].close_time,
            self.cfg,
        )
        sweep = next(item for item in updated if item.kind == InteractionKind.SWEEP)
        self.assertEqual(sweep.state, InteractionState.EXPIRED)

    def test_two_closes_beyond_source_invalidate_long_anchor(self) -> None:
        source = level(side=LiquiditySide.SELL_SIDE, price=99.0)
        rows = [bar(1, 99.5, 99.7, 98.6, 99.3)]
        events = detect_liquidity_interactions(rows, [source], rows[-1].close_time, self.cfg)
        later = rows + [
            bar(2, 99.0, 99.1, 98.6, 98.8),
            bar(3, 98.8, 98.9, 98.5, 98.7),
        ]
        updated = apply_interaction_lifecycle(
            events,
            later,
            [],
            [source],
            later[-1].close_time,
            self.cfg,
        )
        sweep = next(item for item in updated if item.kind == InteractionKind.SWEEP)
        self.assertEqual(sweep.state, InteractionState.INVALIDATED)

    def test_snapshot_hard_blocks_without_causal_sources(self) -> None:
        rows = [bar(1, 100.0, 100.5, 99.5, 100.2)]
        snapshot = InteractionEngineV1(self.cfg).snapshot(
            symbol="BTCUSDT",
            timeframe="5m",
            bars=rows,
            pois=[],
            levels=[],
            evaluated_at=rows[-1].close_time,
        )
        self.assertTrue(snapshot.hard_block)
        self.assertEqual(snapshot.hard_block_reason, "no_causal_interaction_sources")

    def test_no_pnl_export_contains_no_outcome_fields(self) -> None:
        rows = [bar(1, 100.0, 101.3, 99.8, 100.8)]
        snapshot = InteractionEngineV1(self.cfg).snapshot(
            symbol="BTCUSDT",
            timeframe="5m",
            bars=rows,
            pois=[],
            levels=[level()],
            evaluated_at=rows[-1].close_time,
        )
        raw = json.dumps(snapshot_to_no_pnl_dict(snapshot), sort_keys=True).lower()
        for forbidden in (
            "pnl",
            "future_return",
            "trade_outcome",
            "mfe",
            "mae",
            "profit_factor",
            "drawdown",
        ):
            self.assertNotIn(f'"{forbidden}"', raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
