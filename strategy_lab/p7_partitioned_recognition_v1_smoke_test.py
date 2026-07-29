#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from strategy_lab.outcome_blind_recognition_v1 import ALLOWED_SYMBOLS, RecognitionObservation
from strategy_lab.p7_full_recognition_runner_v1 import RECOGNITION_ID
from strategy_lab.p7_partitioned_recognition_v1 import (
    FOLD_COUNT,
    _fold_bounds,
    _observation_from_dict,
    _observation_to_dict,
    aggregate_partitions,
)

NOW = datetime(2024, 1, 2, tzinfo=timezone.utc)


def observation(symbol: str, fold: int, index: int) -> RecognitionObservation:
    return RecognitionObservation(
        symbol=symbol,
        direction="LONG" if index % 2 == 0 else "SHORT",
        fold=fold,
        timestamp=NOW + timedelta(minutes=15 * (fold * 10 + index)),
        family="LIQUIDITY_RAID_REVERSAL",
        decision="VALID_SETUP",
        lifecycle="ENTRY_READY",
        fingerprint=f"fp_{symbol}_{fold}_{index}",
        rearm_parent=None,
        poi_id=f"poi_{symbol}_{fold}_{index}",
        liquidity_ids=(f"liq_{fold}_{index}",),
        interaction_ids=(f"interaction_{fold}_{index}",),
        anchor_id=f"anchor_{fold}_{index}",
        structure_id=f"structure_{fold}_{index}",
        evidence_ids=(f"evidence_{fold}_{index}",),
        evidence_cluster_ids=(f"cluster_{fold}_{index}",),
        economics_valid=True,
        risk_valid=True,
        block_reasons=(),
        hard_blocks=(),
    )


class P7PartitionedRecognitionV1Test(unittest.TestCase):
    def test_observation_round_trip_is_exact(self) -> None:
        row = observation("BTCUSDT", 3, 1)
        self.assertEqual(_observation_from_dict(_observation_to_dict(row)), row)

    def test_fold_bounds_are_exact_and_exhaustive(self) -> None:
        boundaries = [NOW + timedelta(minutes=15 * index) for index in range(103)]
        spans = [_fold_bounds(boundaries, fold) for fold in range(FOLD_COUNT)]
        self.assertEqual(spans[0], (0, 11))
        self.assertEqual(spans[2], (22, 33))
        self.assertEqual(spans[3], (33, 43))
        self.assertEqual(spans[-1], (93, 103))
        covered = [index for start, end in spans for index in range(start, end)]
        self.assertEqual(covered, list(range(103)))

    def test_fifty_partitions_keep_global_dedupe_and_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for symbol in ALLOWED_SYMBOLS:
                for fold in range(FOLD_COUNT):
                    rows = [observation(symbol, fold, index) for index in range(2)]
                    payload = {
                        "recognition_id": RECOGNITION_ID,
                        "symbol": symbol,
                        "fold": fold,
                        "data_manifest_sha256": "a" * 64,
                        "source": "BINANCE_VISION_USDM_FUTURES",
                        "interval": "5m",
                        "start_inclusive": "2024-01-01T00:00:00+00:00",
                        "end_inclusive": "2024-06-30T23:55:00+00:00",
                        "diagnostics": {"symbol": symbol, "fold": fold},
                        "observations": [_observation_to_dict(row) for row in rows],
                    }
                    path = root / f"p7_partition_{symbol}_fold{fold}.json"
                    path.write_text(json.dumps(payload), encoding="utf-8")
            result = aggregate_partitions(root.glob("p7_partition_*.json"), root / "report.json")
            self.assertEqual(result["recognition"]["independent_entry_ready"], 100)
            self.assertTrue(result["recognition"]["gate_pass"])
            self.assertEqual(result["recognition"]["duplicate_rows"], 0)
            self.assertEqual(set(result["recognition"]["by_symbol"]), set(ALLOWED_SYMBOLS))
            self.assertEqual(set(map(int, result["recognition"]["by_fold"])), set(range(FOLD_COUNT)))
            self.assertEqual(result["execution_topology"], "FIFTY_SYMBOL_FOLD_PARTITIONS_THEN_GLOBAL_DEDUPE_V1")

    def test_partition_rejects_observation_from_another_fold(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for symbol in ALLOWED_SYMBOLS:
                for fold in range(FOLD_COUNT):
                    row_fold = (fold + 1) % FOLD_COUNT if symbol == "BTCUSDT" and fold == 0 else fold
                    payload = {
                        "recognition_id": RECOGNITION_ID,
                        "symbol": symbol,
                        "fold": fold,
                        "data_manifest_sha256": "a" * 64,
                        "source": "BINANCE_VISION_USDM_FUTURES",
                        "interval": "5m",
                        "start_inclusive": "2024-01-01T00:00:00+00:00",
                        "end_inclusive": "2024-06-30T23:55:00+00:00",
                        "diagnostics": {"symbol": symbol, "fold": fold},
                        "observations": [_observation_to_dict(observation(symbol, row_fold, 0))],
                    }
                    (root / f"p7_partition_{symbol}_fold{fold}.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escaped"):
                aggregate_partitions(root.glob("p7_partition_*.json"), root / "report.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
