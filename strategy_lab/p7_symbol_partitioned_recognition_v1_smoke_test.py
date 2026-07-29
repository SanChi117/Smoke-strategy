#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from strategy_lab.outcome_blind_recognition_v1 import ALLOWED_SYMBOLS, RecognitionObservation
from strategy_lab.p7_full_recognition_runner_v1 import RECOGNITION_ID
from strategy_lab.p7_partitioned_recognition_v1 import _observation_to_dict
from strategy_lab.p7_symbol_partitioned_recognition_v1 import (
    EXECUTION_TOPOLOGY,
    FOLD_COUNT,
    aggregate_symbol_partitions,
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


def write_payload(root: Path, symbol: str, rows: list[RecognitionObservation]) -> None:
    payload = {
        "recognition_id": RECOGNITION_ID,
        "symbol": symbol,
        "folds": list(range(FOLD_COUNT)),
        "data_manifest_sha256": "a" * 64,
        "source": "BINANCE_VISION_USDM_FUTURES",
        "interval": "5m",
        "start_inclusive": "2024-01-01T00:00:00+00:00",
        "end_inclusive": "2024-06-30T23:55:00+00:00",
        "diagnostics": {"symbol": symbol},
        "observations": [_observation_to_dict(row) for row in rows],
    }
    (root / f"p7_symbol_{symbol}.json").write_text(json.dumps(payload), encoding="utf-8")


class P7SymbolPartitionedRecognitionV1Test(unittest.TestCase):
    def test_five_symbol_partitions_preserve_ten_fold_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for symbol in ALLOWED_SYMBOLS:
                rows = [
                    observation(symbol, fold, index)
                    for fold in range(FOLD_COUNT)
                    for index in range(2)
                ]
                write_payload(root, symbol, rows)

            result = aggregate_symbol_partitions(root.glob("p7_symbol_*.json"), root / "report.json")
            self.assertEqual(result["recognition"]["independent_entry_ready"], 100)
            self.assertTrue(result["recognition"]["gate_pass"])
            self.assertEqual(result["recognition"]["duplicate_rows"], 0)
            self.assertEqual(set(result["recognition"]["by_symbol"]), set(ALLOWED_SYMBOLS))
            self.assertEqual(set(map(int, result["recognition"]["by_fold"])), set(range(FOLD_COUNT)))
            self.assertEqual(result["execution_topology"], EXECUTION_TOPOLOGY)

    def test_symbol_partition_rejects_foreign_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for symbol in ALLOWED_SYMBOLS:
                row_symbol = "ETHUSDT" if symbol == "BTCUSDT" else symbol
                write_payload(root, symbol, [observation(row_symbol, 0, 0)])
            with self.assertRaisesRegex(ValueError, "escaped symbol"):
                aggregate_symbol_partitions(root.glob("p7_symbol_*.json"), root / "report.json")

    def test_symbol_partition_rejects_invalid_fold(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for symbol in ALLOWED_SYMBOLS:
                fold = FOLD_COUNT if symbol == "BTCUSDT" else 0
                write_payload(root, symbol, [observation(symbol, fold, 0)])
            with self.assertRaisesRegex(ValueError, "invalid fold"):
                aggregate_symbol_partitions(root.glob("p7_symbol_*.json"), root / "report.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
