#!/usr/bin/env python3
"""Sharded transport for Candidate 2 full causal replay."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

# Install the already-validated P7 execution transports before importing the
# shared runner: side compatibility, exact incremental POI and (when the
# workflow provides P7_LEVELS_FILE) authoritative precomputed levels.
import strategy_lab.p7_partitioned_recognition_entrypoint_v1 as _p7_transport  # noqa: F401,E402
import strategy_lab.p7_full_recognition_runner_v1 as p7  # noqa: E402
from strategy_lab.candidate_2_full_recognition_runner_v1 import REPLAY_ID
from strategy_lab.candidate_2_segmented_replay_v1 import SEGMENT_COUNT, scan_symbol_segment
from strategy_lab.candidate_2_outcome_blind_recognition_v1 import (
    Candidate2RecognitionObservation,
    assert_clean,
    dedupe_global,
    is_counted,
    run_recognition,
)

SHARD_ID = "SMOKE_CORE_CANDIDATE_2_REPLAY_SHARDS_V3_P7_FAST_TRANSPORT"


def _row_to_dict(row: Candidate2RecognitionObservation) -> dict[str, Any]:
    payload = asdict(row)
    payload["timestamp"] = row.timestamp.isoformat()
    return payload


def _row_from_dict(payload: dict[str, Any]) -> Candidate2RecognitionObservation:
    return Candidate2RecognitionObservation(
        symbol=str(payload["symbol"]), direction=str(payload["direction"]), fold=int(payload["fold"]),
        timestamp=datetime.fromisoformat(str(payload["timestamp"])), family=str(payload["family"]),
        lifecycle=str(payload["lifecycle"]), scenario_id=str(payload["scenario_id"]),
        fingerprint=str(payload["fingerprint"]), rearm_parent=payload.get("rearm_parent"),
        regime_id=str(payload["regime_id"]), persistence_id=payload.get("persistence_id"),
        reachability_id=payload.get("reachability_id"), quality_component_digest=str(payload["quality_component_digest"]),
        quality_score_0_100=float(payload["quality_score_0_100"]), economics_valid=bool(payload["economics_valid"]),
        risk_valid=bool(payload["risk_valid"]), evidence_ids=tuple(payload.get("evidence_ids", ())),
        block_reasons=tuple(payload.get("block_reasons", ())),
    )


def scan_physical_shard(symbol: str, segment_index: int, segment_count: int, data_root: Path, output: Path) -> dict[str, Any]:
    _manifest, candles_by_symbol = p7.load_locked_dataset(data_root)
    symbol = symbol.upper()
    if symbol not in p7.ALLOWED_SYMBOLS:
        raise ValueError(f"unsupported symbol: {symbol}")
    if not getattr(p7, "_p7_incremental_poi_installed", False):
        raise RuntimeError("authoritative P7 incremental POI transport is not installed")
    rows, diagnostics = scan_symbol_segment(
        symbol,
        candles_by_symbol[symbol],
        segment_index=segment_index,
        segment_count=segment_count,
    )
    diagnostics["p7_incremental_poi_installed"] = True
    diagnostics["p7_precomputed_levels_enabled"] = bool(__import__("os").environ.get("P7_LEVELS_FILE"))
    payload = {
        "shard_id": SHARD_ID,
        "replay_id": REPLAY_ID,
        "candidate_id": "SMOKE_CORE_1_0_CANDIDATE_2",
        "symbol": symbol,
        "segment_index": segment_index,
        "segment_count": segment_count,
        "purpose": "CAUSAL_REPLAY_DEBUG_ONLY_NOT_PROFITABILITY",
        "data_manifest_sha256": hashlib.sha256((data_root / "p7_full_recognition_data_manifest_v1.json").read_bytes()).hexdigest(),
        "rows": [_row_to_dict(row) for row in rows],
        "diagnostics": diagnostics,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def aggregate_shards(paths: Iterable[Path], output: Path) -> dict[str, Any]:
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(paths)]
    expected = len(p7.ALLOWED_SYMBOLS) * SEGMENT_COUNT
    if len(payloads) != expected:
        raise ValueError(f"expected {expected} Candidate 2 physical shards, got {len(payloads)}")
    if {p["symbol"] for p in payloads} != set(p7.ALLOWED_SYMBOLS):
        raise ValueError("Candidate 2 replay symbol coverage mismatch")
    if len({p["data_manifest_sha256"] for p in payloads}) != 1:
        raise ValueError("Candidate 2 replay data manifest mismatch")
    coverage = {(p["symbol"], int(p["segment_index"])) for p in payloads}
    expected_coverage = {(symbol, idx) for symbol in p7.ALLOWED_SYMBOLS for idx in range(SEGMENT_COUNT)}
    if coverage != expected_coverage:
        raise ValueError("Candidate 2 replay physical-shard coverage mismatch")
    if not all(p["diagnostics"].get("p7_incremental_poi_installed") is True for p in payloads):
        raise ValueError("incremental POI transport missing in one or more shards")
    if not all(p["diagnostics"].get("p7_precomputed_levels_enabled") is True for p in payloads):
        raise ValueError("precomputed P7 levels missing in one or more shards")

    rows = [_row_from_dict(row) for payload in payloads for row in payload["rows"]]
    report = run_recognition(rows)
    assert_clean(report)
    deduped, _ = dedupe_global(rows)
    counted = tuple(row for row in deduped if is_counted(row))
    fingerprint_digest = hashlib.sha256("\n".join(sorted(row.fingerprint for row in counted)).encode("utf-8")).hexdigest()
    result = {
        "replay_id": REPLAY_ID,
        "shard_id": SHARD_ID,
        "candidate_id": "SMOKE_CORE_1_0_CANDIDATE_2",
        "purpose": "CAUSAL_REPLAY_DEBUG_ONLY_NOT_PROFITABILITY",
        "data_manifest_sha256": payloads[0]["data_manifest_sha256"],
        "physical_shard_count": len(payloads),
        "segments_per_symbol": SEGMENT_COUNT,
        "semantic_clean": True,
        "transport": "AUTHORITATIVE_P7_INCREMENTAL_POI_PLUS_PRECOMPUTED_LEVELS",
        "recognition": {
            "total_rows": report.total_rows,
            "independent_entry_ready": report.independent_entry_ready,
            "duplicate_rows": report.duplicate_rows,
            "forbidden_rows": report.forbidden_rows,
            "missing_provenance_rows": report.missing_provenance_rows,
            "invalid_lifecycle_rows": report.invalid_lifecycle_rows,
            "reproducible": report.reproducible,
            "by_symbol": dict(report.by_symbol),
            "by_direction": dict(report.by_direction),
            "by_fold": {str(k): v for k, v in report.by_fold.items()},
        },
        "fingerprint_digest_sha256": fingerprint_digest,
        "fingerprints": sorted(row.fingerprint for row in counted),
        "diagnostics": [p["diagnostics"] for p in payloads],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan-segment")
    scan.add_argument("--symbol", required=True)
    scan.add_argument("--segment-index", type=int, required=True)
    scan.add_argument("--segment-count", type=int, default=SEGMENT_COUNT)
    scan.add_argument("--data-root", type=Path, required=True)
    scan.add_argument("--output", type=Path, required=True)
    agg = sub.add_parser("aggregate")
    agg.add_argument("--input-dir", type=Path, required=True)
    agg.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "scan-segment":
        result = scan_physical_shard(args.symbol, args.segment_index, args.segment_count, args.data_root, args.output)
        print(json.dumps({"symbol": result["symbol"], "segment": result["segment_index"], "rows": len(result["rows"])}, sort_keys=True))
    else:
        result = aggregate_shards(args.input_dir.rglob("candidate_2_replay_*.json"), args.output)
        print(json.dumps({"entry_ready": result["recognition"]["independent_entry_ready"], "fingerprint_digest": result["fingerprint_digest_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
