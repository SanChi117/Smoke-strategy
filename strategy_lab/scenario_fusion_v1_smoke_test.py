#!/usr/bin/env python3
from datetime import datetime, timezone
import unittest

from strategy_lab.scenario_fusion_v1 import (
    Decision, Direction, EvidenceInput, EvidenceRelation, FusionInput,
    FAMILY_NODE_WEIGHTS, ScenarioFamily, ScenarioState, build_fingerprint,
    can_rearm, fuse_scenario, scenario_to_no_pnl_dict,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def evidence_for(family: ScenarioFamily, strength: float = 100.0):
    return [
        EvidenceInput(f"e{i}", f"c{i}", node, EvidenceRelation.PRIMARY, strength, NOW)
        for i, node in enumerate(FAMILY_NODE_WEIGHTS[family])
    ]


def base(**changes):
    values = dict(
        symbol="BTCUSDT", side=Direction.LONG,
        family=ScenarioFamily.LIQUIDITY_RAID_REVERSAL, evaluated_at=NOW,
        target_level_id="target1", poi_id="poi1", anchor_id="anchor1",
        structure_id="structure1", protected_swing_id="swing1",
        poi_lifecycle_id="poi-life-1", armed=True, reaction_detected=True,
        structure_confirmed=True, economics_valid=True, risk_valid=True,
    )
    values.update(changes)
    return FusionInput(**values)


class ScenarioFusionTests(unittest.TestCase):
    def test_frozen_weights_sum_to_100(self):
        for weights in FAMILY_NODE_WEIGHTS.values():
            self.assertEqual(sum(weights.values()), 100.0)

    def test_all_three_families_can_score(self):
        for family in ScenarioFamily:
            data = base(family=family)
            result = fuse_scenario(data, evidence_for(family))
            self.assertEqual(result.scenario.total_score_0_100, 100.0)

    def test_entry_ready_high_confidence(self):
        result = fuse_scenario(base(), evidence_for(ScenarioFamily.LIQUIDITY_RAID_REVERSAL))
        self.assertEqual(result.scenario.state, ScenarioState.ENTRY_READY)
        self.assertEqual(result.decision, Decision.HIGH_CONFIDENCE_SETUP)

    def test_valid_setup_70_to_79(self):
        result = fuse_scenario(base(), evidence_for(ScenarioFamily.LIQUIDITY_RAID_REVERSAL, 75))
        self.assertEqual(result.decision, Decision.VALID_SETUP)

    def test_watch_for_incomplete_lifecycle(self):
        data = base(structure_confirmed=False, economics_valid=False, risk_valid=False)
        result = fuse_scenario(data, evidence_for(data.family))
        self.assertEqual(result.scenario.state, ScenarioState.REACTION_DETECTED)
        self.assertEqual(result.decision, Decision.WATCH)

    def test_no_setup_below_60(self):
        result = fuse_scenario(base(), evidence_for(ScenarioFamily.LIQUIDITY_RAID_REVERSAL, 50))
        self.assertEqual(result.decision, Decision.NO_SETUP)

    def test_hard_block_forces_no_setup(self):
        result = fuse_scenario(base(hard_blocks=("missing_exact_anchor",)), evidence_for(ScenarioFamily.LIQUIDITY_RAID_REVERSAL))
        self.assertEqual(result.decision, Decision.NO_SETUP)

    def test_economics_cancel_state(self):
        result = fuse_scenario(base(economics_cancelled=True), evidence_for(ScenarioFamily.LIQUIDITY_RAID_REVERSAL))
        self.assertEqual(result.scenario.state, ScenarioState.CANCELLED_BY_ECONOMICS)
        self.assertEqual(result.decision, Decision.NO_SETUP)

    def test_risk_cancel_state(self):
        result = fuse_scenario(base(risk_cancelled=True), evidence_for(ScenarioFamily.LIQUIDITY_RAID_REVERSAL))
        self.assertEqual(result.scenario.state, ScenarioState.CANCELLED_BY_RISK)

    def test_critical_conflict_caps_high_confidence(self):
        result = fuse_scenario(base(critical_conflicts=("critical_data_conflict",)), evidence_for(ScenarioFamily.LIQUIDITY_RAID_REVERSAL))
        self.assertEqual(result.decision, Decision.VALID_SETUP)

    def test_same_cluster_not_double_counted_across_nodes(self):
        family = ScenarioFamily.LIQUIDITY_RAID_REVERSAL
        rows = [EvidenceInput("a", "same", "location", EvidenceRelation.PRIMARY, 100, NOW),
                EvidenceInput("b", "same", "raid", EvidenceRelation.PRIMARY, 100, NOW)]
        result = fuse_scenario(base(), rows)
        nonzero = [n for n in result.scenario.node_scores if n.awarded > 0]
        self.assertEqual(len(nonzero), 1)

    def test_cluster_cap_30(self):
        family = ScenarioFamily.LIQUIDITY_RAID_REVERSAL
        rows = [EvidenceInput(str(i), "same", node, EvidenceRelation.PRIMARY, 100, NOW)
                for i, node in enumerate(FAMILY_NODE_WEIGHTS[family])]
        result = fuse_scenario(base(), rows)
        self.assertLessEqual(result.scenario.total_score_0_100, 30.0)

    def test_future_evidence_is_ignored(self):
        future = datetime(2027, 1, 1, tzinfo=timezone.utc)
        row = EvidenceInput("future", "future", "raid", EvidenceRelation.PRIMARY, 100, future)
        result = fuse_scenario(base(), [row])
        self.assertEqual(result.scenario.total_score_0_100, 0.0)

    def test_fingerprint_stable(self):
        self.assertEqual(build_fingerprint(base()), build_fingerprint(base()))

    def test_new_anchor_rearms(self):
        previous = fuse_scenario(base(), evidence_for(ScenarioFamily.LIQUIDITY_RAID_REVERSAL)).scenario
        self.assertTrue(can_rearm(previous, base(anchor_id="anchor2")))
        self.assertFalse(can_rearm(previous, base()))

    def test_new_protected_swing_rearms(self):
        previous = fuse_scenario(base(), evidence_for(ScenarioFamily.LIQUIDITY_RAID_REVERSAL)).scenario
        self.assertTrue(can_rearm(previous, base(protected_swing_id="swing2")))

    def test_no_pnl_export(self):
        result = fuse_scenario(base(), evidence_for(ScenarioFamily.LIQUIDITY_RAID_REVERSAL))
        payload = scenario_to_no_pnl_dict(result)
        text = str(payload).lower()
        for forbidden in ("pnl", "profit_factor", "future_return", "trade_outcome", "mfe", "mae"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
