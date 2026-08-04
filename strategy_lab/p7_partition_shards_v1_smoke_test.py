#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from strategy_lab.outcome_blind_recognition_v1 import RecognitionObservation
from strategy_lab.p7_full_recognition_runner_v1 import RECOGNITION_ID
from strategy_lab.p7_partitioned_recognition_v1 import _observation_to_dict
from strategy_lab.p7_partition_shards_v1 import _shard_bounds, merge_shards

NOW = datetime(2024, 1, 2, tzinfo=timezone.utc)


def observation(symbol: str, fold: int, index: int) -> RecognitionObservation:
    return RecognitionObservation(
        symbol=symbol,
        direction="LONG" if index % 2 == 0 else "SHORT",
        fold=fold,
        timestamp=NOW + timedelta(minutes=15 * index),
        family="LIQUIDITY_RAID_REVERSAL",
        decision="VALID_SETUP",
        lifecycle="ENTRY_READY",
        fingerprint=f"fp_{symbol}_{fold}_{index}",
        rearm_parent=None,
        poi_id=f"poi_{symbol}_{fold}_{index}",
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


class P7PartitionShardsV1Test(unittest.TestCase):
    def test_shard_bounds_are_exact_and_exhaustive(self) -> None:
        spans = [_shard_bounds(103, index, 4) for index in range(4)]
        self.assertEqual(spans, [(0, 26), (26, 52), (52, 78), (78, 103)])
        covered = [index for start, end in spans for index in range(start, end)]
        self.assertEqual(covered, list(range(103)))

    def test_merge_restores_one_exact_fold_partition(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            symbol = "BTCUSDT"
            fold = 8
            shard_count = 4
            fold_boundaries = 103
            for shard_index in range(shard_count):
                start, end = _shard_bounds(fold_boundaries, shard_index, shard_count)
                rows = [observation(symbol, fold, shard_index * 10 + index) for index in range(2)]
                payload = {
                    "recognition_id": RECOGNITION_ID,
                    "symbol": symbol,
                    "fold": fold,
                    "shard_index": shard_index,
                    "shard_count": shard_count,
                    "data_manifest_sha256": "a" * 64,
                    "source": "BINANCE_VISION_USDM_FUTURES",
                    "interval": "5m",
                    "start_inclusive": "2024-01-01T00:00:00+00:00",
                    "end_inclusive": "2024-06-30T23:55:00+00:00",
                    "diagnostics": {
                        "symbol": symbol,
                        "fold": fold,
                        "boundaries": 1000,
                        "fold_boundaries": end - start,
                        "fold_boundaries_total": fold_boundaries,
                        "shard_index": shard_index,
                        "shard_count": shard_count,
                        "shard_relative_start": start,
                        "shard_relative_end": end,
                        "shard_boundaries": end - start,
                        "anchors_seen": 1,
                        "family_specs": 2,
                        "entry_geometries": 3,
                        "observations": len(rows),
                        "raw_levels": 7,
                        "poi_transport": "EXACT_INCREMENTAL_P1_EQUIVALENT_V1",
                        "level_precompute_end": f"2024-06-{20 + shard_index:02d}T00:00:00+00:00",
                    },
                    "observations": [_observation_to_dict(row) for row in rows],
                }
                path = root / f"p7_partition_shard_{symbol}_{fold}_{shard_index}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")

            output = root / f"p7_partition_{symbol}_{fold}.json"
            result = merge_shards(root.glob("p7_partition_shard_*.json"), symbol, fold, output)
            self.assertEqual(result["symbol"], symbol)
            self.assertEqual(result["fold"], fold)
            self.assertEqual(result["diagnostics"]["fold_boundaries"], fold_boundaries)
            self.assertEqual(result["diagnostics"]["execution_shards"], shard_count)
            self.assertEqual(result["diagnostics"]["anchors_seen"], shard_count)
            self.assertEqual(len(result["observations"]), shard_count * 2)
            self.assertNotIn("shard_index", result)

    def test_merge_rejects_incomplete_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = {
                "recognition_id": RECOGNITION_ID,
                "symbol": "BTCUSDT",
                "fold": 0,
                "shard_index": 0,
                "shard_count": 2,
                "data_manifest_sha256": "a" * 64,
                "source": "BINANCE_VISION_USDM_FUTURES",
                "interval": "5m",
                "start_inclusive": "2024-01-01T00:00:00+00:00",
                "end_inclusive": "2024-06-30T23:55:00+00:00",
                "diagnostics": {
                    "boundaries": 100,
                    "fold_boundaries_total": 10,
                    "shard_relative_start": 0,
                    "shard_relative_end": 5,
                    "anchors_seen": 0,
                    "family_specs": 0,
                    "entry_geometries": 0,
                    "raw_levels": 0,
                    "poi_transport": "EXACT_INCREMENTAL_P1_EQUIVALENT_V1",
                    "level_precompute_end": "2024-01-01T00:00:00+00:00",
                },
                "observations": [],
            }
            path = root / "p7_partition_shard_BTCUSDT_0_0.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "expected 2 shards"):
                merge_shards(root.glob("*.json"), "BTCUSDT", 0, root / "out.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
