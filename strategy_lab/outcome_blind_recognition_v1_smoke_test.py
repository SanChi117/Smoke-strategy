#!/usr/bin/env python3
from datetime import datetime, timedelta, timezone
import unittest

from strategy_lab.outcome_blind_recognition_v1 import (
    PilotStatus, RecognitionObservation, dedupe_global, is_counted,
    report_to_no_outcome_dict, run_full_recognition, run_pilot,
)

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def row(**overrides):
    values = dict(
        symbol="BTCUSDT", direction="LONG", fold=0, timestamp=BASE,
        family="LIQUIDITY_RAID_REVERSAL", decision="VALID_SETUP",
        lifecycle="ENTRY_READY", fingerprint="fp_1", rearm_parent=None,
        poi_id="poi_1", liquidity_ids=("liq_1",), interaction_ids=("int_1",),
        anchor_id="anchor_1", structure_id="structure_1",
        evidence_ids=("ev_1",), evidence_cluster_ids=("cl_1",),
        economics_valid=True, risk_valid=True, block_reasons=(), hard_blocks=(),
    )
    values.update(overrides)
    return RecognitionObservation(**values)


class P7RecognitionTests(unittest.TestCase):
    def test_valid_entry_ready_is_counted(self):
        self.assertTrue(is_counted(row()))

    def test_watch_is_not_counted(self):
        self.assertFalse(is_counted(row(decision="WATCH")))

    def test_wrong_universe_is_not_counted(self):
        self.assertFalse(is_counted(row(symbol="DOGEUSDT")))

    def test_economics_failure_is_not_counted(self):
        self.assertFalse(is_counted(row(economics_valid=False)))

    def test_risk_failure_is_not_counted(self):
        self.assertFalse(is_counted(row(risk_valid=False)))

    def test_missing_provenance_is_not_counted(self):
        self.assertFalse(is_counted(row(evidence_ids=())))

    def test_global_duplicate_suppression(self):
        unique, duplicates = dedupe_global([row(), row(timestamp=BASE + timedelta(minutes=5))])
        self.assertEqual(len(unique), 1)
        self.assertEqual(duplicates, 1)

    def test_rearm_lineage_can_emit_new_observation(self):
        first = row()
        second = row(timestamp=BASE + timedelta(days=1), rearm_parent="fp_1")
        unique, duplicates = dedupe_global([first, second])
        self.assertEqual(len(unique), 2)
        self.assertEqual(duplicates, 0)

    def test_pilot_passes_clean_fixture(self):
        report = run_pilot([row()])
        self.assertEqual(report.status, PilotStatus.PASS)
        self.assertTrue(report.reproducible)

    def test_pilot_rejects_invalid_lifecycle(self):
        report = run_pilot([row(lifecycle="CONFIRMED")])
        self.assertEqual(report.status, PilotStatus.FAIL)
        self.assertEqual(report.invalid_lifecycle_rows, 1)

    def test_pilot_rejects_unexplained_hard_block(self):
        report = run_pilot([row(decision="NO_SETUP", lifecycle="DISCOVERED", hard_blocks=("mystery",))])
        self.assertEqual(report.status, PilotStatus.FAIL)
        self.assertEqual(report.unexplained_block_rows, 1)

    def test_causal_block_prefix_is_allowed(self):
        report = run_pilot([row(decision="NO_SETUP", lifecycle="DISCOVERED", hard_blocks=("causal:missing_closed_bar",))])
        self.assertEqual(report.unexplained_block_rows, 0)

    def test_full_gate_requires_sixty(self):
        rows = [row(fingerprint=f"fp_{i}", timestamp=BASE + timedelta(minutes=i), fold=i % 10) for i in range(59)]
        self.assertFalse(run_full_recognition(rows).gate_pass)
        rows.append(row(fingerprint="fp_59", timestamp=BASE + timedelta(minutes=59), fold=9))
        self.assertTrue(run_full_recognition(rows).gate_pass)

    def test_fold_partition_is_exact(self):
        rows = [row(fingerprint=f"fp_{i}", timestamp=BASE + timedelta(minutes=i), fold=i) for i in range(10)]
        report = run_full_recognition(rows)
        self.assertEqual(report.by_fold, {i: 1 for i in range(10)})

    def test_no_outcome_serialization(self):
        payload = report_to_no_outcome_dict(run_full_recognition([row()]))
        flattened = str(payload).lower()
        for key in ("pnl", "future_return", "mfe", "mae", "profit_factor", "drawdown"):
            self.assertNotIn(key, flattened)


if __name__ == "__main__":
    unittest.main()
