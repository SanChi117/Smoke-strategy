#!/usr/bin/env python3
"""Technical partition runner for exact P7 full recognition.

This module changes only execution topology: each frozen symbol is scanned in an
independent GitHub Actions job, then all outcome-blind observations are combined
and passed through the original global fingerprint de-duplication and gate.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from strategy_lab.outcome_blind_recognition_v1 import (
    ALLOWED_SYMBOLS,
    RecognitionObservation,
    dedupe_global,
    is_counted,
    report_to_no_outcome_dict,
    run_full_recognition,
)
from strategy_lab.p7_full_recognition_runner_v1 import (
    DATA_ROOT,
    RECOGNITION_ID,
    REPORT_PATH,
    ScenarioFamily,
    _assert_no_outcomes,
    _jsonable,
    load_locked_dataset,
    scan_symbol,
)


def _observation_to_dict(row: RecognitionObservation) -> dict[str, Any]:
    payload = asdict(row)
    payload["timestamp"] = row.timestamp.isoformat()
    return payload


def _observation_from_dict(payload: dict[str, Any]) -> RecognitionObservation:
    return RecognitionObservation(
        symbol=str(payload["symbol"]),
        direction=str(payload["direction"]),
        fold=int(payload["fold"]),
        timestamp=datetime.fromisoformat(str(payload["timestamp"])),
        family=str(payload["family"]),
        decision=str(payload["decision"]),
        lifecycle=str(payload["lifecycle"]),
        fingerprint=str(payload["fingerprint"]),
        rearm_parent=payload.get("rearm_parent"),
        poi_id=str(payload["poi_id"]),
        liquidity_ids=tuple(payload.get("liquidity_ids", ())),
        interaction_ids=tuple(payload.get("interaction_ids", ())),
        anchor_id=payload.get("anchor_id"),
        structure_id=payload.get("structure_id"),
        evidence_ids=tuple(payload.get("evidence_ids", ())),
        evidence_cluster_ids=tuple(payload.get("evidence_cluster_ids", ())),
        economics_valid=bool(payload["economics_valid"]),
        risk_valid=bool(payload["risk_valid"]),
        block_reasons=tuple(payload.get("block_reasons", ())),
        hard_blocks=tuple(payload.get("hard_blocks", ())),
    )


def scan_partition(symbol: str, output: Path, root: Path = DATA_ROOT) -> dict[str, Any]:
    symbol = symbol.upper()
    if symbol not in ALLOWED_SYMBOLS:
        raise ValueError(f"unexpected symbol: {symbol}")
    manifest, candles_by_symbol = load_locked_dataset(root)
    rows, diagnostics = scan_symbol(symbol, candles_by_symbol[symbol])
    payload = {
        "recognition_id": RECOGNITION_ID,
        "symbol": symbol,
        "data_manifest_sha256": hashlib.sha256((root / "p7_full_recognition_data_manifest_v1.json").read_bytes()).hexdigest(),
        "source": manifest["source"],
        "interval": manifest["interval"],
        "start_inclusive": manifest["start_inclusive"],
        "end_inclusive": manifest["end_inclusive"],
        "diagnostics": diagnostics,
        "observations": [_observation_to_dict(row) for row in rows],
    }
    _assert_no_outcomes(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")
    return payload


def aggregate_partitions(paths: Iterable[Path], output: Path = REPORT_PATH) -> dict[str, Any]:
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(paths)]
    if len(payloads) != len(ALLOWED_SYMBOLS):
        raise ValueError(f"expected {len(ALLOWED_SYMBOLS)} symbol partitions, got {len(payloads)}")
    if {payload["symbol"] for payload in payloads} != set(ALLOWED_SYMBOLS):
        raise ValueError("partition universe mismatch")
    if {payload["recognition_id"] for payload in payloads} != {RECOGNITION_ID}:
        raise ValueError("recognition id mismatch")
    manifest_shas = {payload["data_manifest_sha256"] for payload in payloads}
    if len(manifest_shas) != 1:
        raise ValueError("partition manifest mismatch")

    all_rows = [
        _observation_from_dict(row)
        for payload in payloads
        for row in payload["observations"]
    ]
    report = run_full_recognition(all_rows)
    deduped, _ = dedupe_global(all_rows)
    counted_rows = tuple(row for row in deduped if is_counted(row))
    result = {
        "recognition_id": RECOGNITION_ID,
        "candidate_id": "SMOKE_CORE_1_0_CANDIDATE_1",
        "data_manifest_sha256": next(iter(manifest_shas)),
        "source": payloads[0]["source"],
        "interval": payloads[0]["interval"],
        "start_inclusive": payloads[0]["start_inclusive"],
        "end_inclusive": payloads[0]["end_inclusive"],
        "fold_count": 10,
        "status": "PASS" if report.gate_pass else "FAIL",
        "recognition": report_to_no_outcome_dict(report),
        "by_family": {
            family.value: sum(row.family == family.value for row in counted_rows)
            for family in ScenarioFamily
        },
        "diagnostics": [payload["diagnostics"] for payload in payloads],
        "execution_topology": "FIVE_SYMBOL_PARTITIONS_THEN_GLOBAL_DEDUPE_V1",
    }
    _assert_no_outcomes(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--symbol", required=True)
    scan.add_argument("--output", required=True, type=Path)
    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("--input-dir", required=True, type=Path)
    aggregate.add_argument("--output", default=REPORT_PATH, type=Path)
    args = parser.parse_args()

    if args.command == "scan":
        scan_partition(args.symbol, args.output)
        return 0
    paths = tuple(args.input_dir.rglob("p7_partition_*.json"))
    result = aggregate_partitions(paths, args.output)
    print(json.dumps({
        "recognition_id": result["recognition_id"],
        "status": result["status"],
        "independent_entry_ready": result["recognition"]["independent_entry_ready"],
        "gate_pass": result["recognition"]["gate_pass"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
