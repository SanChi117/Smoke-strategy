#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timedelta
import json
import unittest

from strategy_lab.execution_structure_v1 import (
    ExecutionConfig, ExecutionMode, ExecutionState,
    evaluate_execution_structure, structure_to_no_pnl_dict,
)
from strategy_lab.interaction_engine_v1 import AnchorEventV1, AnchorKind, InteractionState
from strategy_lab.mtf_dealing_range_v2 import ClosedBar
from strategy_lab.poi_imbalance_engine_v1 import Direction

BASE = datetime(2026, 1, 1, 0, 0)

def bar(i, o, h, l, c, tf="5m"):
    step = timedelta(minutes=15 if tf=="15m" else 5)
    t = BASE + i*step
    return ClosedBar("BTCUSDT", tf, t, t+step, o,h,l,c,100)

def anchor(direction=Direction.LONG, state=InteractionState.CONFIRMED):
    return AnchorEventV1(
        anchor_id="anchor-1", event_id="event-1", symbol="BTCUSDT",
        timeframe="5m", direction=direction, kind=AnchorKind.POI_REJECTION,
        state=state, confirmed_at=BASE, valid_until=BASE+timedelta(hours=4),
        source_poi_id="poi-1", source_liquidity_id=None,
        evidence_ids=("e1",), dependencies=("event-1","poi-1"), conflicts=(),
    )

class P4Smoke(unittest.TestCase):
    def test_unconfirmed_anchor_hard_blocks(self):
        s=evaluate_execution_structure(anchor(state=InteractionState.DISCOVERED),{},BASE)
        self.assertEqual(s.state,ExecutionState.INVALIDATED)
        self.assertIn("anchor_not_confirmed",s.conflicts)
    def test_no_bars_discovered(self):
        s=evaluate_execution_structure(anchor(),{},BASE+timedelta(minutes=5))
        self.assertEqual(s.state,ExecutionState.DISCOVERED)
    def test_mode_a_long(self):
        rows=[bar(0,100,101,99,100),bar(1,100,101,99.5,100.2),bar(2,100.2,101,99.8,100.5,"15m"),bar(3,100.5,103,100.2,102.8,"15m")]
        s=evaluate_execution_structure(anchor(),{"5m":rows[:2],"15m":rows[2:]},rows[-1].close_time,ExecutionConfig(atr_length=2,reaction_window_bars=1))
        self.assertEqual(s.state,ExecutionState.CONFIRMED)
        self.assertEqual(s.confirmation_mode,ExecutionMode.A_TEXTBOOK_BREAK)
    def test_mode_a_short(self):
        rows=[bar(0,100,101,99,100),bar(1,100,100.5,98.8,99),bar(2,99,100,98.5,99.2,"15m"),bar(3,99.2,99.4,96,96.3,"15m")]
        s=evaluate_execution_structure(anchor(Direction.SHORT),{"5m":rows[:2],"15m":rows[2:]},rows[-1].close_time,ExecutionConfig(atr_length=2,reaction_window_bars=1))
        self.assertEqual(s.state,ExecutionState.CONFIRMED)
    def test_soft_penalty_for_5m_confirmation(self):
        rows=[bar(0,100,101,99,100),bar(1,100,103,99.8,102.8)]
        s=evaluate_execution_structure(anchor(),{"5m":rows},rows[-1].close_time,ExecutionConfig(atr_length=2,reaction_window_bars=1))
        self.assertEqual(s.state,ExecutionState.CONFIRMED)
        self.assertIn("unclean_structure_soft_penalty",s.conflicts)
        self.assertLess(s.confidence_0_100,86)
    def test_two_close_invalidation(self):
        rows=[bar(0,100,101,99,100),bar(1,99,99.5,97,97.5),bar(2,97.5,98,96,96.5)]
        s=evaluate_execution_structure(anchor(),{"5m":rows},rows[-1].close_time,ExecutionConfig(atr_length=2,reaction_window_bars=1))
        self.assertEqual(s.state,ExecutionState.INVALIDATED)
    def test_one_close_not_invalidation(self):
        rows=[bar(0,100,101,99,100),bar(1,99,99.5,97,97.5)]
        s=evaluate_execution_structure(anchor(),{"5m":rows},rows[-1].close_time,ExecutionConfig(atr_length=2,reaction_window_bars=1))
        self.assertNotEqual(s.state,ExecutionState.INVALIDATED)
    def test_expired_anchor(self):
        s=evaluate_execution_structure(anchor(),{},BASE+timedelta(hours=5))
        self.assertEqual(s.state,ExecutionState.EXPIRED)
    def test_no_retro_fill(self):
        rows=[bar(0,100,101,99,100),bar(1,100,103,99.8,102.8)]
        early=evaluate_execution_structure(anchor(),{"5m":rows},rows[0].close_time,ExecutionConfig(atr_length=2,reaction_window_bars=1))
        late=evaluate_execution_structure(anchor(),{"5m":rows},rows[1].close_time,ExecutionConfig(atr_length=2,reaction_window_bars=1))
        self.assertNotEqual(early.state,ExecutionState.CONFIRMED)
        self.assertEqual(late.entry_time,rows[1].close_time)
    def test_deterministic(self):
        rows=[bar(0,100,101,99,100)]
        a=evaluate_execution_structure(anchor(),{"5m":rows},rows[0].close_time)
        b=evaluate_execution_structure(anchor(),{"5m":rows},rows[0].close_time)
        self.assertEqual(a,b)
    def test_dependencies_preserved(self):
        rows=[bar(0,100,101,99,100)]
        s=evaluate_execution_structure(anchor(),{"5m":rows},rows[0].close_time)
        self.assertIn("anchor-1",s.dependencies)
        self.assertIn("poi-1",s.dependencies)
    def test_no_pnl_export(self):
        rows=[bar(0,100,101,99,100)]
        raw=json.dumps(structure_to_no_pnl_dict(evaluate_execution_structure(anchor(),{"5m":rows},rows[0].close_time)),default=str).lower()
        for key in ("pnl","future_return","trade_outcome","mfe","mae","drawdown"):
            self.assertNotIn(f'"{key}"',raw)
    def test_directional_structure_levels(self):
        rows=[bar(0,100,101,99,100)]
        long=evaluate_execution_structure(anchor(),{"5m":rows},rows[0].close_time)
        short=evaluate_execution_structure(anchor(Direction.SHORT),{"5m":rows},rows[0].close_time)
        self.assertEqual(long.protected_swing,99)
        self.assertEqual(short.protected_swing,101)
    def test_fixed_defaults(self):
        c=ExecutionConfig()
        self.assertEqual(c.acceptance_closes,2)
        self.assertEqual(c.invalidation_closes,2)
        self.assertEqual(c.soft_unclean_penalty,12.0)

if __name__=="__main__":
    unittest.main(verbosity=2)
