#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta
import json
import unittest

from strategy_lab.execution_family_policy_v1 import (
    FAMILY_ENTRY_POLICIES,
    ScenarioFamily,
    apply_family_policy,
    family_policy_to_no_pnl_dict,
)
from strategy_lab.execution_structure_v1 import ExecutionMode, ExecutionState, LocalStructureV1
from strategy_lab.poi_imbalance_engine_v1 import Direction

BASE = datetime(2026, 1, 1)


def structure(mode: ExecutionMode, confidence: float = 80.0, state: ExecutionState = ExecutionState.CONFIRMED) -> LocalStructureV1:
    return LocalStructureV1(
        structure_id="s1", symbol="BTCUSDT", anchor_id="a1", direction=Direction.LONG,
        anchor_confirmed_at=BASE, evaluated_at=BASE + timedelta(minutes=15),
        reaction_low=99.0, reaction_high=101.0, protected_swing=99.0,
        weak_swing=101.0, boundary=101.0, confirmation_mode=mode, state=state,
        confirmed_at=BASE + timedelta(minutes=15), entry_time=BASE + timedelta(minutes=15),
        valid_until=BASE + timedelta(hours=2), confidence_0_100=confidence,
        clean_structure=True, source_timeframe="5m", source_bar_close=BASE + timedelta(minutes=15),
        dependencies=("a1", "event1"), conflicts=(), reasons=("fixture",),
    )


class P4FamilyPolicySmoke(unittest.TestCase):
    def test_raid_allows_mode_a(self):
        self.assertTrue(apply_family_policy(structure(ExecutionMode.A_TEXTBOOK_BREAK), ScenarioFamily.RAID_REVERSAL).allowed)

    def test_range_rejects_mode_a(self):
        result = apply_family_policy(structure(ExecutionMode.A_TEXTBOOK_BREAK), ScenarioFamily.RANGE_ROTATION)
        self.assertFalse(result.allowed)
        self.assertIn("confirmation_mode_not_allowed_for_family", result.conflicts)

    def test_range_allows_mode_b(self):
        self.assertTrue(apply_family_policy(structure(ExecutionMode.B_ACCEPTANCE_RETEST), ScenarioFamily.RANGE_ROTATION).allowed)

    def test_trend_allows_all_three_modes(self):
        for mode in (ExecutionMode.A_TEXTBOOK_BREAK, ExecutionMode.B_ACCEPTANCE_RETEST, ExecutionMode.C_DISPLACEMENT_FAILED_RETEST):
            self.assertTrue(apply_family_policy(structure(mode), ScenarioFamily.TREND_CONTINUATION).allowed)

    def test_unconfirmed_structure_rejected(self):
        result = apply_family_policy(structure(ExecutionMode.A_TEXTBOOK_BREAK, state=ExecutionState.ARMED), ScenarioFamily.RAID_REVERSAL)
        self.assertFalse(result.allowed)
        self.assertEqual(result.reason, "structure_not_confirmed")

    def test_family_confidence_floor(self):
        result = apply_family_policy(structure(ExecutionMode.B_ACCEPTANCE_RETEST, confidence=60), ScenarioFamily.RANGE_ROTATION)
        self.assertFalse(result.allowed)
        self.assertIn("below_family_minimum_confidence", result.conflicts)

    def test_frozen_expiry_bars(self):
        self.assertEqual(FAMILY_ENTRY_POLICIES[ScenarioFamily.RAID_REVERSAL].expiry_5m_bars, 18)
        self.assertEqual(FAMILY_ENTRY_POLICIES[ScenarioFamily.TREND_CONTINUATION].expiry_5m_bars, 24)
        self.assertEqual(FAMILY_ENTRY_POLICIES[ScenarioFamily.RANGE_ROTATION].expiry_5m_bars, 16)

    def test_no_outcome_export(self):
        result = apply_family_policy(structure(ExecutionMode.A_TEXTBOOK_BREAK), ScenarioFamily.RAID_REVERSAL)
        raw = json.dumps(family_policy_to_no_pnl_dict(result), default=str).lower()
        for key in ("pnl", "future_return", "trade_outcome", "profit_factor", "drawdown"):
            self.assertNotIn(f'"{key}"', raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
