#!/usr/bin/env python3
"""Technical fold sharding for exact P7 full recognition.

Each preregistered symbol x fold is divided into four contiguous execution
shards only to keep every GitHub Actions job below the hosted-runner time limit.
Every shard reconstructs the same full causal history before its first evaluated
boundary. Shards are merged back into the original exact 50 symbol-fold
partitions before the frozen global fingerprint de-duplication and gate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

# Install the existing side-enum compatibility, incremental P1 transport and
# exact precomputed-level transport before importing the partition module.
import strategy_lab.p7_partitioned_recognition_entrypoint_v1 as _entrypoint  # noqa: F401,E402
import strategy_lab.p7_partitioned_recognition_v1 as partition  # noqa: E402
import strategy_lab.p7_full_recognition_runner_v1 as runner  # noqa: E402

_BASE_FOLD_BOUNDS = partition._fold_bounds


def _shard_bounds(length: int, shard_index: int, shard_count: int) -> tuple[int, int]:
    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    if shard_index not in range(shard_count):
        raise ValueError(f"shard_index must be in [0, {shard_count - 1}]")
    base, remainder = divmod(length, shard_count)
    start = shard_index * base + min(shard_index, remainder)
    size = base + (1 if shard_index < remainder else 0)
    return start, start + size


def _install_fold_shard(fold: int, shard_index: int, shard_count: int) -> None:
    def _sharded_fold_bounds(boundaries: Sequence[Any], requested_fold: int) -> tuple[int, int]:
        start, end = _BASE_FOLD_BOUNDS(boundaries, requested_fold)
        if requested_fold != fold:
            return start, end
        relative_start, relative_end = _shard_bounds(end - start, shard_index, shard_count)
        return start + relative_start, start + relative_end

    partition._fold_bounds = _sharded_fold_bounds


def scan_shard(
    symbol: str,
    fold: int,
    shard_index: int,
    shard_count: int,
    output: Path,
) -> dict[str, Any]:
    _install_fold_shard(fold, shard_index, shard_count)
    payload = partition.scan_partition(symbol, fold, output)
    diagnostics = payload["diagnostics"]
    fold_start, fold_end = _BASE_FOLD_BOUNDS(range(int(diagnostics["boundaries"])), fold)
    relative_start, relative_end = _shard_bounds(fold_end - fold_start, shard_index, shard_count)
    diagnostics.update({
        "fold_boundaries_total": fold_end - fold_start,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "shard_relative_start": relative_start,
        "shard_relative_end": relative_end,
        "shard_boundaries": relative_end - relative_start,
    })
    payload["shard_index"] = shard_index
    payload["shard_count"] = shard_count
    runner._assert_no_outcomes(payload)
    output.write_text(json.dumps(runner._jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")
    return payload


def merge_shards(paths: Iterable[Path], symbol: str, fold: int, output: Path) -> dict[str, Any]:
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(paths)]
    if not payloads:
        raise ValueError("no shard payloads")
    shard_counts = {int(payload["shard_count"]) for payload in payloads}
    if len(shard_counts) != 1:
        raise ValueError("shard count mismatch")
    shard_count = next(iter(shard_counts))
    if len(payloads) != shard_count:
        raise ValueError(f"expected {shard_count} shards, got {len(payloads)}")
    if {int(payload["shard_index"]) for payload in payloads} != set(range(shard_count)):
        raise ValueError("shard index mismatch")
    if {payload["symbol"] for payload in payloads} != {symbol}:
        raise ValueError("shard symbol mismatch")
    if {int(payload["fold"]) for payload in payloads} != {fold}:
        raise ValueError("shard fold mismatch")
    if {payload["recognition_id"] for payload in payloads} != {partition.RECOGNITION_ID}:
        raise ValueError("shard recognition id mismatch")
    if len({payload["data_manifest_sha256"] for payload in payloads}) != 1:
        raise ValueError("shard manifest mismatch")

    ordered = sorted(payloads, key=lambda payload: int(payload["shard_index"]))
    spans = [
        (
            int(payload["diagnostics"]["shard_relative_start"]),
            int(payload["diagnostics"]["shard_relative_end"]),
        )
        for payload in ordered
    ]
    expected_start = 0
    for start, end in spans:
        if start != expected_start or end <= start:
            raise ValueError("shard coverage is not contiguous")
        expected_start = end
    fold_boundaries = int(ordered[0]["diagnostics"]["fold_boundaries_total"])
    if expected_start != fold_boundaries:
        raise ValueError("shard coverage is incomplete")

    observations = [row for payload in ordered for row in payload["observations"]]
    if any(int(row["fold"]) != fold for row in observations):
        raise ValueError("observation escaped its fixed fold")

    diagnostics = {
        "symbol": symbol,
        "fold": fold,
        "boundaries": int(ordered[0]["diagnostics"]["boundaries"]),
        "fold_boundaries": fold_boundaries,
        "anchors_seen": sum(int(payload["diagnostics"]["anchors_seen"]) for payload in ordered),
        "family_specs": sum(int(payload["diagnostics"]["family_specs"]) for payload in ordered),
        "entry_geometries": sum(int(payload["diagnostics"]["entry_geometries"]) for payload in ordered),
        "observations": len(observations),
        "raw_levels": int(ordered[0]["diagnostics"]["raw_levels"]),
        "poi_transport": ordered[0]["diagnostics"]["poi_transport"],
        "level_precompute_end": max(payload["diagnostics"]["level_precompute_end"] for payload in ordered),
        "execution_shards": shard_count,
        "shard_transport": "CONTIGUOUS_FOLD_SHARDS_MERGED_BEFORE_GLOBAL_DEDUPE_V1",
    }
    payload = {
        "recognition_id": partition.RECOGNITION_ID,
        "symbol": symbol,
        "fold": fold,
        "data_manifest_sha256": ordered[0]["data_manifest_sha256"],
        "source": ordered[0]["source"],
        "interval": ordered[0]["interval"],
        "start_inclusive": ordered[0]["start_inclusive"],
        "end_inclusive": ordered[0]["end_inclusive"],
        "diagnostics": diagnostics,
        "observations": observations,
    }
    runner._assert_no_outcomes(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(runner._jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan")
    scan.add_argument("--symbol", required=True)
    scan.add_argument("--fold", required=True, type=int)
    scan.add_argument("--shard-index", required=True, type=int)
    scan.add_argument("--shard-count", required=True, type=int)
    scan.add_argument("--output", required=True, type=Path)

    merge = sub.add_parser("merge")
    merge.add_argument("--input-dir", required=True, type=Path)
    merge.add_argument("--symbol", required=True)
    merge.add_argument("--fold", required=True, type=int)
    merge.add_argument("--output", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "scan":
        scan_shard(args.symbol.upper(), args.fold, args.shard_index, args.shard_count, args.output)
        return 0
    pattern = f"p7_partition_shard_{args.symbol.upper()}_{args.fold}_*.json"
    merge_shards(args.input_dir.rglob(pattern), args.symbol.upper(), args.fold, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
