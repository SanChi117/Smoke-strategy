#!/usr/bin/env python3
"""Efficient technical partitioning for exact P7 full recognition.

Each job scans one complete symbol exactly once, preserving the preregistered
10 chronological folds inside every emitted observation. The aggregate step
still performs one global fingerprint de-duplication and the frozen P7 gate.
No market period, source, symbol, direction, threshold, lifecycle, provenance,
fingerprint, rearm, economics/risk rule, or no-outcome constraint is changed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

# Apply the already-approved P6 side-enum compatibility shim before the frozen
# runner builds any scenario fingerprints.
import strategy_lab.p7_full_recognition_entrypoint_v1 as _compat  # noqa: F401
import strategy_lab.p7_full_recognition_runner_v1 as runner
from strategy_lab.outcome_blind_recognition_v1 import (
    ALLOWED_SYMBOLS,
    dedupe_global,
    is_counted,
    report_to_no_outcome_dict,
    run_full_recognition,
)
from strategy_lab.p7_partitioned_recognition_v1 import (
    _observation_from_dict,
    _observation_to_dict,
)

RECOGNITION_ID = runner.RECOGNITION_ID
DATA_ROOT = runner.DATA_ROOT
REPORT_PATH = runner.REPORT_PATH
FOLD_COUNT = runner.FOLD_COUNT
ScenarioFamily = runner.ScenarioFamily
EXECUTION_TOPOLOGY = "FIVE_SYMBOL_PARTITIONS_WITH_INTERNAL_TEN_FOLD_ACCOUNTING_THEN_GLOBAL_DEDUPE_V1"


def _validate_symbol_rows(symbol: str, rows: Iterable[Any]) -> None:
    for row in rows:
        if row.symbol != symbol:
            raise ValueError(f"observation escaped symbol partition: {row.symbol} != {symbol}")
        if int(row.fold) not in range(FOLD_COUNT):
            raise ValueError(f"observation has invalid fold: {row.fold}")


def scan_symbol_partition(symbol: str, output: Path, root: Path = DATA_ROOT) -> dict[str, Any]:
    """Scan one frozen symbol once and retain exact internal 10-fold labels."""
    symbol = symbol.upper()
    if symbol not in ALLOWED_SYMBOLS:
        raise ValueError(f"unexpected symbol: {symbol}")

    manifest, candles_by_symbol = runner.load_locked_dataset(root)
    print(json.dumps({
        "event": "p7_symbol_scan_started",
        "symbol": symbol,
        "candles_5m": len(candles_by_symbol[symbol]),
        "fold_count": FOLD_COUNT,
    }, sort_keys=True), flush=True)

    rows, diagnostics = runner.scan_symbol(symbol, candles_by_symbol[symbol])
    _validate_symbol_rows(symbol, rows)
    by_fold = Counter(int(row.fold) for row in rows)

    payload = {
        "recognition_id": RECOGNITION_ID,
        "symbol": symbol,
        "folds": list(range(FOLD_COUNT)),
        "data_manifest_sha256": hashlib.sha256(
            (root / "p7_full_recognition_data_manifest_v1.json").read_bytes()
        ).hexdigest(),
        "source": manifest["source"],
        "interval": manifest["interval"],
        "start_inclusive": manifest["start_inclusive"],
        "end_inclusive": manifest["end_inclusive"],
        "diagnostics": {
            **diagnostics,
            "execution_partition": "ONE_COMPLETE_SYMBOL_WITH_INTERNAL_TEN_FOLDS_V1",
            "observations_by_fold": {str(fold): by_fold.get(fold, 0) for fold in range(FOLD_COUNT)},
        },
        "observations": [_observation_to_dict(row) for row in rows],
    }
    runner._assert_no_outcomes(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(runner._jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps({
        "event": "p7_symbol_scan_completed",
        "symbol": symbol,
        "observations": len(rows),
        "observations_by_fold": payload["diagnostics"]["observations_by_fold"],
    }, sort_keys=True), flush=True)
    return payload


def aggregate_symbol_partitions(paths: Iterable[Path], output: Path = REPORT_PATH) -> dict[str, Any]:
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(paths)]
    if len(payloads) != len(ALLOWED_SYMBOLS):
        raise ValueError(f"expected {len(ALLOWED_SYMBOLS)} symbol partitions, got {len(payloads)}")

    actual_symbols = {str(payload.get("symbol", "")) for payload in payloads}
    if actual_symbols != set(ALLOWED_SYMBOLS):
        raise ValueError("symbol partition universe mismatch")
    if {payload.get("recognition_id") for payload in payloads} != {RECOGNITION_ID}:
        raise ValueError("recognition id mismatch")
    if any(payload.get("folds") != list(range(FOLD_COUNT)) for payload in payloads):
        raise ValueError("internal fold declaration mismatch")

    manifest_shas = {payload.get("data_manifest_sha256") for payload in payloads}
    if len(manifest_shas) != 1:
        raise ValueError("partition manifest mismatch")

    all_rows = []
    for payload in payloads:
        symbol = str(payload["symbol"])
        rows = [_observation_from_dict(row) for row in payload.get("observations", ())]
        _validate_symbol_rows(symbol, rows)
        all_rows.extend(rows)

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
        "fold_count": FOLD_COUNT,
        "status": "PASS" if report.gate_pass else "FAIL",
        "recognition": report_to_no_outcome_dict(report),
        "by_family": {
            family.value: sum(row.family == family.value for row in counted_rows)
            for family in ScenarioFamily
        },
        "diagnostics": [payload["diagnostics"] for payload in payloads],
        "execution_topology": EXECUTION_TOPOLOGY,
    }
    runner._assert_no_outcomes(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(runner._jsonable(result), indent=2, sort_keys=True), encoding="utf-8")
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
        scan_symbol_partition(args.symbol, args.output)
        return 0

    paths = tuple(args.input_dir.rglob("p7_symbol_*.json"))
    result = aggregate_symbol_partitions(paths, args.output)
    print(json.dumps({
        "recognition_id": result["recognition_id"],
        "status": result["status"],
        "independent_entry_ready": result["recognition"]["independent_entry_ready"],
        "gate_pass": result["recognition"]["gate_pass"],
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
