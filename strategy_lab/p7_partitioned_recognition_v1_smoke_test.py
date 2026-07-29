#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from strategy_lab.outcome_blind_recognition_v1 import ALLOWED_SYMBOLS, RecognitionObservation
from strategy_lab.p7_full_recognition_runner_v1 import RECOGNITION_ID
from strategy_lab.p7_partitioned_recognition_v1 import (
    _observation_from_dict,
    _observation_to_dict,
    aggregate_partitions,
)

NOW = datetime(2024, 1, 2, tzinfo=timezone.utc)


def observation(symbol: str, index: int) -> RecognitionObservation:
    return RecognitionObservation(
        symbol=symbol,
        direction="LONG" if index % 2 == 0 else "SHORT",
        fold=index % 10,
        timestamp=NOW,
        family="LIQUIDITY_RAID_REVERSAL",
        decision="VALID_SETUP",
        lifecycle="ENTRY_READY",
        fingerprint=f"fp_{symbol}_{index}",
        rearm_parent=None,
        poi_id=f"poi_{symbol}_{index}",
        liquidity_ids=(f"liq_{index}",),
        interaction_ids=(f"interaction_{index}",),
        anchor_id=f"anchor_{index}",
        structure_id=f"structure_{index}",
        evidence_ids=(f"evidence_{index}",),
        evidence_cluster_ids=(f"cluster_{index}",),
        economics_valid=True,
        risk_valid=True,
        block_reasons=(),
        hard_blocks=(),
    )


class P7PartitionedRecognitionV1Test(unittest.TestCase):
    def test_observation_round_trip_is_exact(self) -> None:
        row = observation("BTCUSDT", 3)
        self.assertEqual(_observation_from_dict(_observation_to_dict(row)), row)

    def test_five_partitions_keep_global_dedupe_and_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for symbol in ALLOWED_SYMBOLS:
                rows = [observation(symbol, index) for index in range(12)]
                payload = {
                    "recognition_id": RECOGNITION_ID,
                    "symbol": symbol,
                    "data_manifest_sha256": "a" * 64,
                    "source": "BINANCE_VISION_USDM_FUTURES",
                    "interval": "5m",
                    "start_inclusive": "2024-01-01T00:00:00+00:00",
                    "end_inclusive": "2024-06-30T23:55:00+00:00",
                    "diagnostics": {"symbol": symbol},
                    "observations": [_observation_to_dict(row) for row in rows],
                }
                (root / f"p7_partition_{symbol}.json").write_text(json.dumps(payload), encoding="utf-8")
            result = aggregate_partitions(root.glob("p7_partition_*.json"), root / "report.json")
            self.assertEqual(result["recognition"]["independent_entry_ready"], 60)
            self.assertTrue(result["recognition"]["gate_pass"])
            self.assertEqual(result["recognition"]["duplicate_rows"], 0)
            self.assertEqual(set(result["recognition"]["by_symbol"]), set(ALLOWED_SYMBOLS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
