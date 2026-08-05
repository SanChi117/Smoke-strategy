#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path

from strategy_lab.outcome_blind_recognition_v1 import RecognitionObservation
from strategy_lab.p8_semantic_replay_freeze_v1 import (
    P8_ID,
    build_freeze_manifest,
    canonicalize,
    compare_paths,
)

BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def observation(*, fingerprint: str = "fp-1", decision: str = "VALID_SETUP", lifecycle: str = "ENTRY_READY") -> RecognitionObservation:
    return RecognitionObservation(
        symbol="BTCUSDT",
        direction="LONG",
        fold=0,
        timestamp=BASE,
        family="LIQUIDITY_RAID_REVERSAL",
        decision=decision,
        lifecycle=lifecycle,
        fingerprint=fingerprint,
        rearm_parent=None,
        poi_id="poi-1",
        liquidity_ids=("liq-1",),
        interaction_ids=("interaction-1",),
        anchor_id="anchor-1",
        structure_id="structure-1",
        evidence_ids=("evidence-1",),
        evidence_cluster_ids=("cluster-1",),
        economics_valid=True,
        risk_valid=True,
        block_reasons=(),
        hard_blocks=(),
    )


class P8SemanticReplayFreezeTest(unittest.TestCase):
    def test_identical_paths_have_zero_mismatches(self) -> None:
        rows = [observation()]
        result = compare_paths(rows, list(reversed(rows)))
        self.assertEqual(result["mismatch_count"], 0)
        self.assertEqual(result["causal_canonical_rows"], 1)
        self.assertEqual(result["fast_canonical_rows"], 1)

    def test_semantic_difference_is_detected(self) -> None:
        causal = [observation()]
        fast = [observation(decision="WATCH", lifecycle="CONFIRMED")]
        result = compare_paths(causal, fast)
        self.assertGreater(result["mismatch_count"], 0)
        self.assertTrue(result["sample_mismatches"])

    def test_global_duplicate_accounting_is_compared(self) -> None:
        one = observation()
        causal = [one, one]
        fast = [one]
        result = compare_paths(causal, fast)
        self.assertEqual(result["causal_duplicate_rows"], 1)
        self.assertEqual(result["fast_duplicate_rows"], 0)
        self.assertEqual(result["mismatch_count"], 1)

    def test_canonical_record_contains_counted_state(self) -> None:
        records, duplicates = canonicalize([observation()])
        self.assertEqual(duplicates, 0)
        self.assertTrue(records[0]["counted_after_global_dedupe"])
        self.assertEqual(records[0]["timestamp"], BASE.isoformat())

    def test_freeze_manifest_reports_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            manifest = build_freeze_manifest(Path(temp))
        self.assertEqual(manifest["p8_id"], P8_ID)
        self.assertGreater(len(manifest["missing_files"]), 0)
        self.assertEqual(manifest["hashed_file_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
