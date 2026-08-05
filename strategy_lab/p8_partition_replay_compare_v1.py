#!/usr/bin/env python3
"""P8 partition transport for exact causal-vs-fast semantic equivalence.

The causal side is the immutable set of 50 symbol-fold partitions produced by
the authoritative P7 PASS run. The fast side is a fresh replay of the same
locked dataset through the already equivalence-tested P7 technical topology:
200 contiguous execution shards merged back into the same 50 symbol-fold
partitions before unchanged global fingerprint de-duplication.

No P1-P7 trading semantics, thresholds, lifecycle, fingerprints, rearm rules,
universe, period, directions or no-outcome scope are changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from strategy_lab.outcome_blind_recognition_v1 import (
    ALLOWED_DIRECTIONS,
    ALLOWED_SYMBOLS,
    RecognitionObservation,
)
import strategy_lab.p7_partitioned_recognition_v1 as partition
from strategy_lab.p7_full_recognition_runner_v1 import RECOGNITION_ID, _assert_no_outcomes
from strategy_lab.p8_semantic_replay_freeze_v1 import (
    CANDIDATE_ID,
    FREEZE_PATH,
    P8_ID,
    REPORT_PATH,
    build_freeze_manifest,
    compare_paths,
)

AUTHORITATIVE_P7_RUN_ID = 30899050584
AUTHORITATIVE_P7_HEAD = "b749be2578251a3b447a78a79009ff3d45cffc57"
EXPECTED_PARTITIONS = len(ALLOWED_SYMBOLS) * 10
TOPOLOGY = (
    "AUTHORITATIVE_P7_FIFTY_PARTITIONS_VS_FRESH_P8_"
    "TWO_HUNDRED_SHARDS_THEN_FIFTY_PARTITIONS_V1"
)
HELPER_RELATIVE_PATH = "strategy_lab/p8_partition_replay_compare_v1.py"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _partition_paths(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(root.rglob("p7_partition_*.json")))


def load_partition_replay(
    root: Path,
    *,
    transport: str,
) -> tuple[list[RecognitionObservation], list[dict[str, Any]], dict[str, Any]]:
    paths = _partition_paths(root)
    if len(paths) != EXPECTED_PARTITIONS:
        raise ValueError(
            f"{transport}: expected {EXPECTED_PARTITIONS} partitions, got {len(paths)}"
        )
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    actual_keys = {(str(row["symbol"]), int(row["fold"])) for row in payloads}
    expected_keys = {
        (symbol, fold)
        for symbol in ALLOWED_SYMBOLS
        for fold in range(10)
    }
    if actual_keys != expected_keys:
        raise ValueError(f"{transport}: partition universe/fold mismatch")
    if {str(row["recognition_id"]) for row in payloads} != {RECOGNITION_ID}:
        raise ValueError(f"{transport}: recognition id mismatch")

    manifest_shas = {str(row["data_manifest_sha256"]) for row in payloads}
    if len(manifest_shas) != 1:
        raise ValueError(f"{transport}: data manifest mismatch")
    contract_fields = ("source", "interval", "start_inclusive", "end_inclusive")
    contract_values = {
        field: {str(row[field]) for row in payloads}
        for field in contract_fields
    }
    if any(len(values) != 1 for values in contract_values.values()):
        raise ValueError(f"{transport}: partition contract mismatch")

    for payload in payloads:
        fold = int(payload["fold"])
        if any(int(row["fold"]) != fold for row in payload["observations"]):
            raise ValueError(f"{transport}: observation escaped fixed fold")

    observations = [
        partition._observation_from_dict(row)
        for payload in payloads
        for row in payload["observations"]
    ]
    diagnostics = [dict(payload["diagnostics"]) for payload in payloads]
    metadata = {
        "data_manifest_sha256": next(iter(manifest_shas)),
        **{field: next(iter(values)) for field, values in contract_values.items()},
        "partition_count": len(payloads),
        "transport": transport,
    }
    _assert_no_outcomes({"metadata": metadata, "diagnostics": diagnostics})
    return observations, diagnostics, metadata


def _extend_freeze_manifest(freeze: dict[str, Any]) -> dict[str, Any]:
    path = Path(HELPER_RELATIVE_PATH)
    if not path.is_file():
        if HELPER_RELATIVE_PATH not in freeze["missing_files"]:
            freeze["missing_files"].append(HELPER_RELATIVE_PATH)
        freeze["required_file_count"] += 1
        return freeze
    freeze["required_file_count"] += 1
    freeze["hashed_file_count"] += 1
    freeze["files"][HELPER_RELATIVE_PATH] = {
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }
    freeze["files"] = dict(sorted(freeze["files"].items()))
    return freeze


def execute(causal_dir: Path, fast_dir: Path) -> dict[str, Any]:
    causal_rows, causal_diagnostics, causal_meta = load_partition_replay(
        causal_dir,
        transport="AUTHORITATIVE_P7_CAUSAL_PARTITIONS_V1",
    )
    fast_rows, fast_diagnostics, fast_meta = load_partition_replay(
        fast_dir,
        transport="P8_BOUNDED_PARALLEL_REPLAY_PARTITIONS_V1",
    )
    contract_keys = (
        "data_manifest_sha256",
        "source",
        "interval",
        "start_inclusive",
        "end_inclusive",
        "partition_count",
    )
    differences = {
        key: {"causal": causal_meta[key], "fast": fast_meta[key]}
        for key in contract_keys
        if causal_meta[key] != fast_meta[key]
    }
    if differences:
        raise ValueError(f"causal/fast partition contract mismatch: {differences}")

    equivalence = compare_paths(causal_rows, fast_rows)
    freeze = _extend_freeze_manifest(build_freeze_manifest())
    freeze_complete = (
        not freeze["missing_files"]
        and freeze["hashed_file_count"] == freeze["required_file_count"]
    )
    contract = {
        "source": causal_meta["source"],
        "interval": causal_meta["interval"],
        "start_inclusive": causal_meta["start_inclusive"],
        "end_inclusive": causal_meta["end_inclusive"],
        "symbols": list(ALLOWED_SYMBOLS),
        "directions": list(ALLOWED_DIRECTIONS),
        "fold_count": 10,
        "global_fingerprint_dedupe": True,
        "recognition_id": RECOGNITION_ID,
        "data_manifest_sha256": causal_meta["data_manifest_sha256"],
    }
    status = "PASS" if equivalence["mismatch_count"] == 0 and freeze_complete else "FAIL"
    report = {
        "p8_id": P8_ID,
        "candidate_id": CANDIDATE_ID,
        "status": status,
        "contract": contract,
        "equivalence": equivalence,
        "freeze_complete": freeze_complete,
        "freeze_manifest_sha256": hashlib.sha256(
            json.dumps(freeze, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "execution_topology": TOPOLOGY,
        "authoritative_p7_reference": {
            "run_id": AUTHORITATIVE_P7_RUN_ID,
            "head_sha": AUTHORITATIVE_P7_HEAD,
        },
        "causal_diagnostics": causal_diagnostics,
        "fast_diagnostics": fast_diagnostics,
        "git_commit_sha": os.environ.get("GITHUB_SHA", "LOCAL_UNSET"),
    }
    _assert_no_outcomes(report)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    FREEZE_PATH.write_text(json.dumps(freeze, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--causal-dir", required=True, type=Path)
    parser.add_argument("--fast-dir", required=True, type=Path)
    args = parser.parse_args()
    report = execute(args.causal_dir, args.fast_dir)
    print(json.dumps({
        "p8_id": report["p8_id"],
        "status": report["status"],
        "mismatch_count": report["equivalence"]["mismatch_count"],
        "freeze_complete": report["freeze_complete"],
        "execution_topology": report["execution_topology"],
    }, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
