#!/usr/bin/env python3
"""Dynamic aggregate for Candidate 2 checkpoint transport.

Transport-only: accepts a complete symbol x segment grid and applies the same
Candidate 2 recognition audit/fingerprint logic regardless of physical segment
count. Trading semantics are untouched.
"""
from __future__ import annotations

import argparse
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
    if not all(p["diagnostics"].get("p7_incremental_poi_installed") is True for p in payloads):
        raise ValueError("incremental POI transport missing")
    if not all(p["diagnostics"].get("p7_precomputed_levels_enabled") is True for p in payloads):
        raise ValueError("precomputed P7 levels missing")
    if not all(p["diagnostics"].get("checkpoint_transport") is True for p in payloads):
        raise ValueError("checkpoint transport missing")

    rows = [_row_from_dict(row) for payload in payloads for row in payload["rows"]]
    report = run_recognition(rows)
    assert_clean(report)
    deduped, _ = dedupe_global(rows)
    counted = tuple(row for row in deduped if is_counted(row))
    digest = hashlib.sha256("\n".join(sorted(row.fingerprint for row in counted)).encode("utf-8")).hexdigest()

    result = {
        "replay_id": payloads[0]["replay_id"],
        "candidate_id": payloads[0]["candidate_id"],
        "purpose": "CAUSAL_REPLAY_DEBUG_ONLY_NOT_PROFITABILITY",
        "data_manifest_sha256": payloads[0]["data_manifest_sha256"],
        "physical_shard_count": len(payloads),
        "segments_per_symbol": segment_count,
        "semantic_clean": True,
        "transport": TRANSPORT,
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
    print(json.dumps({"entry_ready": result["recognition"]["independent_entry_ready"], "fingerprint_digest": result["fingerprint_digest_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
