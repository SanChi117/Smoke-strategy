#!/usr/bin/env python3
"""Dynamic aggregate for Candidate 2 checkpoint transport.

Transport-only: accepts a complete symbol x segment grid and applies the same
Candidate 2 recognition audit/fingerprint logic regardless of physical segment
count. Trading semantics are untouched.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

import strategy_lab.p7_full_recognition_runner_v1 as p7
from strategy_lab.candidate_2_replay_shards_v1 import _row_from_dict
from strategy_lab.candidate_2_outcome_blind_recognition_v1 import (
    assert_clean,
    dedupe_global,
    is_counted,
    run_recognition,
)

TRANSPORT = "AUTHORITATIVE_P7_INCREMENTAL_POI_CHECKPOINT_CHAIN_PLUS_PRECOMPUTED_LEVELS"
EXPECTED_SHARD_ID = "SMOKE_CORE_CANDIDATE_2_REPLAY_SHARDS_V4_CHECKPOINT_CHAIN"
EXPECTED_CHECKPOINT_VERSION = "C2_CAUSAL_CHECKPOINT_V1"


def _audit_transport(payloads: list[dict[str, Any]], segment_count: int) -> None:
    """Audit the transport contract that is actually serialized by replay shards."""
    bad_shard_ids = [
        (p.get("symbol"), p.get("segment_index"), p.get("shard_id"))
        for p in payloads
        if p.get("shard_id") != EXPECTED_SHARD_ID
    ]
    if bad_shard_ids:
        raise ValueError(f"unexpected Candidate 2 shard transport identity: {bad_shard_ids[:10]}")

    bad_precomputed = [
        (p["symbol"], int(p["segment_index"]))
        for p in payloads
        if p.get("diagnostics", {}).get("p7_precomputed_levels_enabled") is not True
    ]
    if bad_precomputed:
        raise ValueError(f"precomputed P7 levels missing: {bad_precomputed[:20]}")

    bad_chain = [
        (p["symbol"], int(p["segment_index"]))
        for p in payloads
        if p.get("diagnostics", {}).get("checkpoint_chain_enabled") is not True
    ]
    if bad_chain:
        raise ValueError(f"checkpoint chain missing: {bad_chain[:20]}")

    bad_version = [
        (p["symbol"], int(p["segment_index"]), p.get("diagnostics", {}).get("checkpoint_version"))
        for p in payloads
        if p.get("diagnostics", {}).get("checkpoint_version") != EXPECTED_CHECKPOINT_VERSION
    ]
    if bad_version:
        raise ValueError(f"checkpoint version mismatch: {bad_version[:20]}")

    bad_saved = [
        (p["symbol"], int(p["segment_index"]))
        for p in payloads
        if p.get("diagnostics", {}).get("checkpoint_saved") is not True
    ]
    if bad_saved:
        raise ValueError(f"checkpoint save audit failed: {bad_saved[:20]}")

    bad_continuity: list[tuple[str, int, Any]] = []
    for p in payloads:
        idx = int(p["segment_index"])
        restored = p.get("diagnostics", {}).get("checkpoint_restored")
        expected_restored = idx > 0
        if restored is not expected_restored:
            bad_continuity.append((p["symbol"], idx, restored))
    if bad_continuity:
        raise ValueError(f"checkpoint continuity audit failed: {bad_continuity[:20]}")

    coverage = {(p["symbol"], int(p["segment_index"])) for p in payloads}
    expected = {(symbol, idx) for symbol in p7.ALLOWED_SYMBOLS for idx in range(segment_count)}
    if coverage != expected:
        raise ValueError("checkpoint transport coverage mismatch")


def aggregate(input_dir: Path, output: Path) -> dict[str, Any]:
    paths = sorted(input_dir.rglob("candidate_2_replay_*.json"))
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if not payloads:
        raise ValueError("no Candidate 2 replay shards found")

    segment_counts = {int(p["segment_count"]) for p in payloads}
    if len(segment_counts) != 1:
        raise ValueError(f"segment_count mismatch: {sorted(segment_counts)}")
    segment_count = next(iter(segment_counts))
    symbols = set(p7.ALLOWED_SYMBOLS)
    expected_count = len(symbols) * segment_count
    if len(payloads) != expected_count:
        raise ValueError(f"expected {expected_count} physical shards, got {len(payloads)}")
    if {p["symbol"] for p in payloads} != symbols:
        raise ValueError("Candidate 2 replay symbol coverage mismatch")
    coverage = {(p["symbol"], int(p["segment_index"])) for p in payloads}
    expected_coverage = {(symbol, idx) for symbol in symbols for idx in range(segment_count)}
    if coverage != expected_coverage:
        raise ValueError("Candidate 2 replay segment coverage mismatch")
    if len({p["data_manifest_sha256"] for p in payloads}) != 1:
        raise ValueError("Candidate 2 replay data manifest mismatch")

    _audit_transport(payloads, segment_count)

    rows = [_row_from_dict(row) for payload in payloads for row in payload["rows"]]
    report = run_recognition(rows)
    assert_clean(report)
    deduped, _ = dedupe_global(rows)
    counted = tuple(row for row in deduped if is_counted(row))
    digest = hashlib.sha256("\n".join(sorted(row.fingerprint for row in counted)).encode("utf-8")).hexdigest()

    lifecycle_counts = Counter(row.lifecycle for row in rows)
    block_reason_counts = Counter(reason for row in rows for reason in row.block_reasons)
    family_counts = Counter(row.family for row in rows)
    direction_observation_counts = Counter(row.direction for row in rows)
    quality_by_lifecycle: dict[str, dict[str, float | int]] = {}
    for lifecycle in lifecycle_counts:
        scores = [row.quality_score_0_100 for row in rows if row.lifecycle == lifecycle]
        quality_by_lifecycle[lifecycle] = {
            "count": len(scores),
            "min": min(scores) if scores else 0.0,
            "max": max(scores) if scores else 0.0,
            "mean": (sum(scores) / len(scores)) if scores else 0.0,
        }

    result = {
        "replay_id": payloads[0]["replay_id"],
        "candidate_id": payloads[0]["candidate_id"],
        "purpose": "CAUSAL_REPLAY_DEBUG_ONLY_NOT_PROFITABILITY",
        "data_manifest_sha256": payloads[0]["data_manifest_sha256"],
        "physical_shard_count": len(payloads),
        "segments_per_symbol": segment_count,
        "semantic_clean": True,
        "transport": TRANSPORT,
        "transport_audit": {
            "shard_id": EXPECTED_SHARD_ID,
            "checkpoint_version": EXPECTED_CHECKPOINT_VERSION,
            "checkpoint_chain_complete": True,
            "checkpoint_continuity_clean": True,
            "precomputed_p7_levels_complete": True,
            "note": "incremental POI is proven by V4 checkpoint-chain shard identity and continuous serialized checkpoint state; non-serialized diagnostic flags are not required",
        },
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
        "recognition_diagnostics": {
            "lifecycle_counts": dict(sorted(lifecycle_counts.items())),
            "block_reason_counts": dict(sorted(block_reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
            "family_observation_counts": dict(sorted(family_counts.items())),
            "direction_observation_counts": dict(sorted(direction_observation_counts.items())),
            "quality_by_lifecycle": quality_by_lifecycle,
            "trend_triggers": sum(int(p.get("diagnostics", {}).get("trend_triggers", 0) or 0) for p in payloads),
            "pending_evaluations": sum(int(p.get("diagnostics", {}).get("pending_evaluations", 0) or 0) for p in payloads),
            "cancelled": sum(int(p.get("diagnostics", {}).get("cancelled", 0) or 0) for p in payloads),
        },
        "fingerprint_digest_sha256": digest,
        "fingerprints": sorted(row.fingerprint for row in counted),
        "diagnostics": [p["diagnostics"] for p in payloads],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = aggregate(args.input_dir, args.output)
    print(json.dumps({
        "entry_ready": result["recognition"]["independent_entry_ready"],
        "fingerprint_digest": result["fingerprint_digest_sha256"],
        "lifecycle_counts": result["recognition_diagnostics"]["lifecycle_counts"],
        "block_reason_counts": result["recognition_diagnostics"]["block_reason_counts"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
