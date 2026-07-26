#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import unittest

from strategy_lab.execution_structure_v1 import ExecutionMode, ExecutionState, LocalStructureV1
from strategy_lab.mtf_dealing_range_v2 import ClosedBar
from strategy_lab.poi_imbalance_engine_v1 import Direction
from strategy_lab.p7_full_recognition_runner_v1 import (
    RECOGNITION_ID,
    ScenarioFamily,
    _assert_no_outcomes,
    _entry_geometry,
    assign_folds,
)

BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def bar(index: int, open_: float = 100.0, high: float = 101.0, low: float = 99.0, close: float = 100.5) -> ClosedBar:
    opened = BASE + timedelta(minutes=15 * index)
    return ClosedBar("BTCUSDT", "15m", opened, opened + timedelta(minutes=15), open_, high, low, close, 100.0)


def structure(direction: Direction = Direction.LONG, confirmed_at: datetime | None = None) -> LocalStructureV1:
    confirmed = confirmed_at or BASE
    return LocalStructureV1(
        structure_id="structure-1", symbol="BTCUSDT", anchor_id="anchor-1", direction=direction,
        anchor_confirmed_at=confirmed - timedelta(minutes=15), evaluated_at=confirmed + timedelta(minutes=15),
        reaction_low=99.0, reaction_high=101.0,
        protected_swing=99.0 if direction == Direction.LONG else 101.0,
        weak_swing=101.0 if direction == Direction.LONG else 99.0,
        boundary=100.0, confirmation_mode=ExecutionMode.A_TEXTBOOK_BREAK,
        state=ExecutionState.CONFIRMED, confirmed_at=confirmed, entry_time=confirmed,
        valid_until=confirmed + timedelta(hours=2), confidence_0_100=86.0,
        clean_structure=True, source_timeframe="15m", source_bar_close=confirmed,
        dependencies=("anchor-1",), conflicts=(), reasons=("fixture",),
    )


class P7FullRecognitionRunnerV1Test(unittest.TestCase):
    def test_exact_ten_equal_count_folds(self) -> None:
        boundaries = [BASE + timedelta(minutes=15 * index) for index in range(103)]
        mapping = assign_folds(boundaries)
        counts = [sum(fold == index for fold in mapping.values()) for index in range(10)]
        self.assertEqual(counts[:3], [11, 11, 11])
        self.assertEqual(counts[3:], [10] * 7)
        self.assertEqual(set(mapping.values()), set(range(10)))

    def test_raid_next_aligned_open_emits_only_when_first_bar_closes(self) -> None:
        rows = [bar(0, open_=101.25), bar(1, open_=102.0)]
        result = _entry_geometry(structure(BASE), ScenarioFamily.LIQUIDITY_RAID_REVERSAL, rows, rows[0].close_time)
        self.assertEqual(result, (101.25, rows[0].close_time))
        self.assertIsNone(_entry_geometry(structure(BASE), ScenarioFamily.LIQUIDITY_RAID_REVERSAL, rows, rows[1].close_time))

    def test_continuation_requires_causal_boundary_retest(self) -> None:
        rows = [
            bar(0, open_=101.0, high=102.0, low=100.5, close=101.5),
            bar(1, open_=101.5, high=102.0, low=99.8, close=100.4),
        ]
        item = structure(confirmed_at=BASE)
        self.assertIsNone(_entry_geometry(item, ScenarioFamily.TREND_PULLBACK_CONTINUATION, rows, rows[0].close_time))
        self.assertEqual(_entry_geometry(item, ScenarioFamily.TREND_PULLBACK_CONTINUATION, rows, rows[1].close_time), (100.0, rows[1].close_time))

    def test_short_continuation_must_hold_below_boundary(self) -> None:
        rows = [
            bar(0, open_=99.0, high=100.2, low=98.0, close=99.5),
            bar(1, open_=99.5, high=100.1, low=98.5, close=100.05),
        ]
        item = structure(Direction.SHORT, BASE)
        self.assertEqual(_entry_geometry(item, ScenarioFamily.TREND_PULLBACK_CONTINUATION, rows, rows[0].close_time), (100.0, rows[0].close_time))
        self.assertIsNone(_entry_geometry(item, ScenarioFamily.TREND_PULLBACK_CONTINUATION, rows, rows[1].close_time))

    def test_no_outcome_guard_and_frozen_id(self) -> None:
        payload = {"recognition_id": RECOGNITION_ID, "status": "PASS", "count": 60}
        _assert_no_outcomes(payload)
        self.assertEqual(RECOGNITION_ID, "SMOKE_CORE_P7_FULL_RECOGNITION_FIXED_V1")
        with self.assertRaises(ValueError):
            _assert_no_outcomes({"future_return": 1})

    def test_contract_side_compatibility_changes_no_fingerprint_input(self) -> None:
        import strategy_lab.scenario_fusion_v1 as fusion
        import strategy_lab.p7_full_recognition_entrypoint_v1  # noqa: F401
        data = fusion.FusionInput(
            symbol="BTCUSDT", side="LONG", family=fusion.ScenarioFamily.LIQUIDITY_RAID_REVERSAL,
            evaluated_at=BASE, target_level_id="target", poi_id="poi", anchor_id="anchor",
            structure_id="structure", protected_swing_id="swing", poi_lifecycle_id="life",
        )
        self.assertTrue(fusion.build_fingerprint(data).startswith("fp_"))

    def test_report_shape_is_json_safe(self) -> None:
        payload = {"recognition_id": RECOGNITION_ID, "fold_count": 10, "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AAVEUSDT"]}
        self.assertIn(RECOGNITION_ID, json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
