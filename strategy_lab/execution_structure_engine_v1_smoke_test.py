#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta
import json
import unittest

from strategy_lab.execution_structure_engine_v1 import (
    ConfirmationMode,
    ExecutionState,
    FAMILY_ENTRY_POLICIES,
    ScenarioFamily,
    evaluate_execution_structure,
    execution_to_no_pnl_dict,
)
from strategy_lab.interaction_engine_v1 import AnchorEventV1, AnchorKind, InteractionState
from strategy_lab.mtf_dealing_range_v2 import ClosedBar
from strategy_lab.poi_imbalance_engine_v1 import Direction

BASE = datetime(2026, 1, 1, 0, 0)


def anchor(direction: Direction = Direction.LONG, state: InteractionState = InteractionState.CONFIRMED) -> AnchorEventV1:
    return AnchorEventV1(
        anchor_id="anchor-1", event_id="event-1", symbol="BTCUSDT", timeframe="5m",
        direction=direction, kind=AnchorKind.LIQUIDITY_SWEEP, state=state,
        confirmed_at=BASE, valid_until=BASE + timedelta(hours=3),
        source_poi_id="poi-1", source_liquidity_id="liq-1",
        evidence_ids=("e-1",), dependencies=("poi-1", "liq-1"), conflicts=(),
    )


def bar(i: int, o: float, h: float, l: float, c: float, tf: str = "5m") -> ClosedBar:
    step = timedelta(minutes=5 if tf == "5m" else 15)
    opened = BASE + i * step
    return ClosedBar("BTCUSDT", tf, opened, opened + step, o, h, l, c, 100.0)


class P4SmokeTest(unittest.TestCase):
    def test_unconfirmed_anchor_hard_blocks(self) -> None:
        result = evaluate_execution_structure(anchor(state=InteractionState.DISCOVERED), [], BASE, ScenarioFamily.RAID_REVERSAL)
        self.assertTrue(result.hard_block)
        self.assertEqual(result.state, ExecutionState.INVALIDATED)

    def test_insufficient_bars_waits_for_reaction(self) -> None:
        result = evaluate_execution_structure(anchor(), [bar(0, 100, 101, 99, 100.5)], BASE + timedelta(minutes=5), ScenarioFamily.RAID_REVERSAL)
        self.assertEqual(result.state, ExecutionState.WAIT_REACTION)

    def test_reaction_is_anchored_after_confirmation(self) -> None:
        rows = [bar(-2, 80, 120, 70, 100), bar(0, 100, 101, 99, 100), bar(1, 100, 102, 99.5, 101)]
        result = evaluate_execution_structure(anchor(), rows, BASE + timedelta(minutes=10), ScenarioFamily.RAID_REVERSAL)
        self.assertEqual(result.reaction_leg.low, 99)
        self.assertEqual(result.reaction_leg.high, 102)

    def test_mode_a_textbook_break(self) -> None:
        rows = [bar(0,100,101,99,100), bar(1,100,102,99.5,101), bar(2,101,103.4,100.8,103.2)]
        result = evaluate_execution_structure(anchor(), rows, BASE + timedelta(minutes=15), ScenarioFamily.RAID_REVERSAL)
        self.assertEqual(result.state, ExecutionState.CONFIRMED)
        self.assertEqual(result.mode, ConfirmationMode.A_TEXTBOOK_BREAK)

    def test_unclean_break_is_soft_not_hard(self) -> None:
        rows = [bar(0,100,101,99,100), bar(1,100,102,99.5,101), bar(2,102,102.3,101.8,102.2)]
        result = evaluate_execution_structure(anchor(), rows, BASE + timedelta(minutes=15), ScenarioFamily.RAID_REVERSAL)
        self.assertFalse(result.hard_block)
        self.assertIn("unclean_bos_choch_soft_penalty", result.conflicts)

    def test_mode_b_acceptance_retest(self) -> None:
        rows = [bar(0,100,101,99,100), bar(1,100,102,99.5,101), bar(2,101,102.3,100.9,102.2), bar(3,102.1,102.5,101.8,102.3), bar(4,102.3,102.6,101.95,102.15)]
        result = evaluate_execution_structure(anchor(), rows, BASE + timedelta(minutes=25), ScenarioFamily.RANGE_ROTATION)
        self.assertEqual(result.mode, ConfirmationMode.B_ACCEPTANCE_RETEST)

    def test_mode_c_failed_retest(self) -> None:
        rows = [bar(0,100,101,99,100), bar(1,100,102,99.5,101), bar(2,101,103.5,100.8,103.3), bar(3,103.2,103.3,101.95,102.2)]
        result = evaluate_execution_structure(anchor(), rows, BASE + timedelta(minutes=20), ScenarioFamily.RANGE_ROTATION)
        self.assertEqual(result.mode, ConfirmationMode.C_DISPLACEMENT_FAILED_RETEST)

    def test_family_policy_rejects_mode_a_for_range(self) -> None:
        self.assertNotIn(ConfirmationMode.A_TEXTBOOK_BREAK, FAMILY_ENTRY_POLICIES[ScenarioFamily.RANGE_ROTATION].allowed_modes)

    def test_expiry_has_no_retro_fill(self) -> None:
        rows = [bar(0,100,101,99,100), bar(1,100,102,99.5,101)]
        result = evaluate_execution_structure(anchor(), rows, BASE + timedelta(hours=3), ScenarioFamily.RANGE_ROTATION)
        self.assertEqual(result.state, ExecutionState.EXPIRED)
        self.assertIsNone(result.confirmed_at)

    def test_two_close_invalidation(self) -> None:
        rows = [bar(0,100,101,99,100), bar(1,100,102,99.5,101), bar(2,98.5,99,97.5,98), bar(3,98,98.4,97,97.5)]
        result = evaluate_execution_structure(anchor(), rows, BASE + timedelta(minutes=20), ScenarioFamily.RAID_REVERSAL)
        self.assertEqual(result.state, ExecutionState.INVALIDATED)
        self.assertTrue(result.hard_block)

    def test_short_textbook_break(self) -> None:
        rows = [bar(0,100,101,99,100), bar(1,100,100.5,98,99), bar(2,99,99.2,96.5,96.7)]
        result = evaluate_execution_structure(anchor(Direction.SHORT), rows, BASE + timedelta(minutes=15), ScenarioFamily.RAID_REVERSAL)
        self.assertEqual(result.mode, ConfirmationMode.A_TEXTBOOK_BREAK)

    def test_m15_stability_bonus(self) -> None:
        rows = [bar(0,100,101,99,100,"15m"), bar(1,100,102,99.5,101,"15m"), bar(2,101,104,100.8,103.8,"15m")]
        result = evaluate_execution_structure(anchor(), rows, BASE + timedelta(minutes=45), ScenarioFamily.TREND_CONTINUATION)
        self.assertIn("15m_stability_bonus", result.reasons)

    def test_confirmation_id_deterministic(self) -> None:
        rows = [bar(0,100,101,99,100), bar(1,100,102,99.5,101), bar(2,101,103.4,100.8,103.2)]
        first = evaluate_execution_structure(anchor(), rows, BASE + timedelta(minutes=15), ScenarioFamily.RAID_REVERSAL)
        second = evaluate_execution_structure(anchor(), rows, BASE + timedelta(minutes=15), ScenarioFamily.RAID_REVERSAL)
        self.assertEqual(first.confirmation_id, second.confirmation_id)

    def test_export_has_no_outcomes(self) -> None:
        rows = [bar(0,100,101,99,100), bar(1,100,102,99.5,101)]
        result = evaluate_execution_structure(anchor(), rows, BASE + timedelta(minutes=10), ScenarioFamily.RAID_REVERSAL)
        raw = json.dumps(execution_to_no_pnl_dict(result), default=str).lower()
        for forbidden in ("pnl", "future_return", "trade_outcome", "profit_factor", "drawdown"):
            self.assertNotIn(f'"{forbidden}"', raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
