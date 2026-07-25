#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta
import json
import unittest

from strategy_lab.execution_structure_engine_v1 import (
    ExecutionMode,
    ExecutionState,
    ExecutionStructureConfig,
    build_execution_structure_snapshot,
    family_entry_policy,
    snapshot_to_no_pnl_dict,
)
from strategy_lab.interaction_engine_v1 import AnchorEventV1, AnchorKind, InteractionState
from strategy_lab.mtf_dealing_range_v2 import ClosedBar
from strategy_lab.poi_imbalance_engine_v1 import Direction

BASE = datetime(2026, 1, 1, 0, 0)


def anchor(direction: Direction = Direction.LONG, state: InteractionState = InteractionState.CONFIRMED) -> AnchorEventV1:
    return AnchorEventV1(
        anchor_id="anchor-1",
        event_id="event-1",
        symbol="BTCUSDT",
        timeframe="5m",
        direction=direction,
        kind=AnchorKind.LIQUIDITY_SWEEP,
        state=state,
        confirmed_at=BASE,
        valid_until=BASE + timedelta(hours=4),
        source_poi_id="poi-1",
        source_liquidity_id="liq-1",
        evidence_ids=("e-1",),
        dependencies=("poi-1", "liq-1"),
        conflicts=(),
    )


def bar(index: int, open_: float, high: float, low: float, close: float, timeframe: str = "5m") -> ClosedBar:
    minutes = 15 if timeframe == "15m" else 5
    opened = BASE + timedelta(minutes=minutes * index)
    return ClosedBar("BTCUSDT", timeframe, opened, opened + timedelta(minutes=minutes), open_, high, low, close, 100.0)


def cfg() -> ExecutionStructureConfig:
    return ExecutionStructureConfig(
        atr_length=2,
        reaction_bars=3,
        displacement_body_atr=0.45,
        directional_close_location=0.60,
        acceptance_closes=2,
        expiry_5m_bars=30,
        expiry_15m_bars=10,
    )


class ExecutionStructureEngineV1SmokeTest(unittest.TestCase):
    def test_unconfirmed_anchor_is_hard_blocked(self) -> None:
        result = build_execution_structure_snapshot(
            anchor(state=InteractionState.DISCOVERED), [], [], BASE + timedelta(minutes=5), cfg()
        )
        self.assertTrue(result.hard_block)
        self.assertEqual(result.state, ExecutionState.INVALIDATED)

    def test_expiry_prevents_retroactive_confirmation(self) -> None:
        short_cfg = ExecutionStructureConfig(atr_length=2, reaction_bars=3, expiry_5m_bars=2, expiry_15m_bars=1)
        result = build_execution_structure_snapshot(anchor(), [], [], BASE + timedelta(hours=1), short_cfg)
        self.assertEqual(result.state, ExecutionState.EXPIRED)
        self.assertIsNone(result.confirmation_time)

    def test_only_post_anchor_closed_bars_are_used(self) -> None:
        rows = [bar(-2, 100, 101, 99, 100.5), bar(-1, 100.5, 102, 100, 101)]
        result = build_execution_structure_snapshot(anchor(), rows, [], BASE + timedelta(minutes=10), cfg())
        self.assertEqual(result.state, ExecutionState.NO_STRUCTURE)

    def test_mode_a_textbook_break(self) -> None:
        rows = [
            bar(0, 100, 101, 99, 100),
            bar(1, 100, 101.2, 99.5, 100.5),
            bar(2, 100.5, 101.1, 100, 100.8),
            bar(3, 100.8, 103, 100.7, 102.8),
        ]
        result = build_execution_structure_snapshot(anchor(), rows, [], rows[-1].close_time, cfg())
        self.assertEqual(result.state, ExecutionState.CONFIRMED)
        self.assertEqual(result.mode, ExecutionMode.A_TEXTBOOK_BREAK)
        self.assertEqual(result.confirmation_time, rows[-1].close_time)

    def test_mode_b_acceptance_then_retest(self) -> None:
        rows = [
            bar(0, 100, 101, 99, 100),
            bar(1, 100, 101.2, 99.5, 100.5),
            bar(2, 100.5, 101.1, 100, 100.8),
            bar(3, 100.8, 101.5, 100.7, 101.25),
            bar(4, 101.25, 101.6, 101.0, 101.3),
            bar(5, 101.3, 101.5, 101.0, 101.4),
        ]
        result = build_execution_structure_snapshot(anchor(), rows, [], rows[-1].close_time, cfg())
        self.assertEqual(result.mode, ExecutionMode.B_ACCEPTANCE_RETEST)
        self.assertEqual(result.confirmation_time, rows[-1].close_time)

    def test_mode_c_displacement_failed_retest(self) -> None:
        rows = [
            bar(0, 100, 101, 99, 100),
            bar(1, 100, 101.2, 99.5, 100.5),
            bar(2, 100.5, 101.1, 100, 100.8),
            bar(3, 100.8, 103, 100.7, 102.8),
            bar(4, 102.8, 103, 101.0, 102.2),
        ]
        result = build_execution_structure_snapshot(anchor(), rows, [], rows[-1].close_time, cfg())
        self.assertEqual(result.mode, ExecutionMode.C_DISPLACEMENT_FAILED_RETEST)
        self.assertEqual(result.confirmation_time, rows[-1].close_time)

    def test_dirty_wick_break_is_soft_conflict(self) -> None:
        rows = [
            bar(0, 100, 101, 99, 100),
            bar(1, 100, 101.2, 99.5, 100.5),
            bar(2, 100.5, 101.1, 100, 100.8),
            bar(3, 100.8, 101.5, 100.5, 100.9),
        ]
        result = build_execution_structure_snapshot(anchor(), rows, [], rows[-1].close_time, cfg())
        self.assertFalse(result.hard_block)
        self.assertTrue(result.dirty_break)
        self.assertIn("wick_only_break", result.conflicts)

    def test_protected_swing_break_invalidates(self) -> None:
        rows = [
            bar(0, 100, 101, 99, 100),
            bar(1, 100, 101.2, 99.5, 100.5),
            bar(2, 100.5, 101.1, 100, 100.8),
            bar(3, 100.8, 101, 97.5, 98.0),
        ]
        result = build_execution_structure_snapshot(anchor(), rows, [], rows[-1].close_time, cfg())
        self.assertEqual(result.state, ExecutionState.INVALIDATED)
        self.assertTrue(result.hard_block)

    def test_family_policies_are_frozen_and_specific(self) -> None:
        raid = family_entry_policy("RAID_REVERSAL")
        trend = family_entry_policy("TREND_CONTINUATION")
        self.assertIn(ExecutionMode.C_DISPLACEMENT_FAILED_RETEST, raid.allowed_modes)
        self.assertIn(ExecutionMode.B_ACCEPTANCE_RETEST, trend.allowed_modes)
        self.assertNotEqual(raid.entry_reference, trend.entry_reference)

    def test_no_pnl_export_contains_no_outcome_fields(self) -> None:
        result = build_execution_structure_snapshot(anchor(), [], [], BASE + timedelta(minutes=5), cfg())
        raw = json.dumps(snapshot_to_no_pnl_dict(result), default=str).lower()
        for forbidden in ("pnl", "future_return", "trade_outcome", "mfe", "mae", "profit_factor", "drawdown"):
            self.assertNotIn(f'"{forbidden}"', raw)

    def test_deterministic_snapshot(self) -> None:
        rows = [bar(0, 100, 101, 99, 100), bar(1, 100, 101, 99.5, 100.5), bar(2, 100.5, 101.2, 100, 100.8)]
        first = build_execution_structure_snapshot(anchor(), rows, [], rows[-1].close_time, cfg())
        second = build_execution_structure_snapshot(anchor(), rows, [], rows[-1].close_time, cfg())
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main(verbosity=2)
