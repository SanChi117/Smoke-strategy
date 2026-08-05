#!/usr/bin/env python3
"""P8 exact semantic replay, causal-vs-fast equivalence and freeze manifest.

This module does not alter or reinterpret P1-P7 semantics.  It executes the
frozen P7 symbol scanner through two transport paths:

* causal: fixed sequential symbol order;
* fast: bounded concurrent symbol execution with deterministic collection.

Both paths consume the same locked closed-candle dataset and are compared after
P7 global fingerprint de-duplication.  Only execution scheduling differs.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from strategy_lab.outcome_blind_recognition_v1 import (
    ALLOWED_DIRECTIONS,
    ALLOWED_SYMBOLS,
    RecognitionObservation,
    dedupe_global,
    is_counted,
)
from strategy_lab.p7_full_recognition_runner_v1 import (
    DATA_ROOT,
    RECOGNITION_ID,
    _assert_no_outcomes,
    load_locked_dataset,
    scan_symbol,
)

P8_ID = "SMOKE_CORE_P8_SEMANTIC_REPLAY_FREEZE_FIXED_V1"
CANDIDATE_ID = "SMOKE_CORE_1_0_CANDIDATE_1"
REPORT_PATH = Path("research_outputs/p8_semantic_replay_freeze_report_v1.json")
FREEZE_PATH = Path("research_outputs/p8_semantic_freeze_manifest_v1.json")

SEMANTIC_FILES = (
    "strategy_lab/poi_imbalance_engine_v1.py",
    "strategy_lab/context_liquidity_engine_v1.py",
    "strategy_lab/interaction_engine_v1.py",
    "strategy_lab/execution_structure_v1.py",
    "strategy_lab/execution_family_policy_v1.py",
    "strategy_lab/economics_risk_portfolio_v1.py",
    "strategy_lab/scenario_fusion_v1.py",
    "strategy_lab/outcome_blind_recognition_v1.py",
    "strategy_lab/p7_full_recognition_runner_v1.py",
    "strategy_lab/p7_full_recognition_entrypoint_v1.py",
    "strategy_lab/p8_semantic_replay_freeze_v1.py",
    "strategy_lab/poi_imbalance_engine_v1_smoke_test.py",
    "strategy_lab/context_liquidity_engine_v1_smoke_test.py",
    "strategy_lab/interaction_engine_v1_smoke_test.py",
    "strategy_lab/execution_structure_v1_smoke_test.py",
    "strategy_lab/execution_family_policy_v1_smoke_test.py",
    "strategy_lab/economics_risk_portfolio_v1_smoke_test.py",
    "strategy_lab/scenario_fusion_v1_smoke_test.py",
    "strategy_lab/outcome_blind_recognition_v1_smoke_test.py",
    "strategy_lab/p7_full_recognition_runner_v1_smoke_test.py",
    "strategy_lab/p8_semantic_replay_freeze_v1_smoke_test.py",
    "research/SMOKE_CORE_P7_FULL_RECOGNITION_PREREG_V1.md",
    "research/SMOKE_CORE_P8_SEMANTIC_REPLAY_FREEZE_PREREG_V1.md",
    ".github/workflows/smoke-core-p7-full-recognition.yml",
    ".github/workflows/smoke-core-p8-semantic-freeze.yml",
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_row(row: RecognitionObservation, counted: bool) -> dict[str, Any]:
    payload = asdict(row)
    payload["timestamp"] = row.timestamp.isoformat()
    payload["counted_after_global_dedupe"] = counted
    return _jsonable(payload)


def canonicalize(rows: Sequence[RecognitionObservation]) -> tuple[list[dict[str, Any]], int]:
    deduped, duplicates = dedupe_global(rows)
    records = [_canonical_row(row, is_counted(row)) for row in deduped]
    records.sort(
        key=lambda row: (
            row["timestamp"], row["symbol"], row["direction"],
            row["family"], row["fingerprint"], row["fold"],
        )
    )
    return records, duplicates


def _scan_causal(candles_by_symbol: Mapping[str, Sequence[Any]]) -> tuple[list[RecognitionObservation], list[dict[str, Any]]]:
    rows: list[RecognitionObservation] = []
    diagnostics: list[dict[str, Any]] = []
    for symbol in ALLOWED_SYMBOLS:
        symbol_rows, symbol_diag = scan_symbol(symbol, candles_by_symbol[symbol])
        rows.extend(symbol_rows)
        diagnostics.append(symbol_diag)
    return rows, diagnostics


def _scan_fast(candles_by_symbol: Mapping[str, Sequence[Any]]) -> tuple[list[RecognitionObservation], list[dict[str, Any]]]:
    # Bounded concurrency is the only optimization. Results are collected in the
    # frozen symbol order, so scheduling cannot affect canonical output.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="p8-fast") as pool:
        futures = {
            symbol: pool.submit(scan_symbol, symbol, candles_by_symbol[symbol])
            for symbol in ALLOWED_SYMBOLS
        }
        ordered = [futures[symbol].result() for symbol in ALLOWED_SYMBOLS]
    rows = [row for symbol_rows, _ in ordered for row in symbol_rows]
    diagnostics = [diag for _, diag in ordered]
    return rows, diagnostics


def compare_paths(
    causal_rows: Sequence[RecognitionObservation],
    fast_rows: Sequence[RecognitionObservation],
) -> dict[str, Any]:
    causal, causal_duplicates = canonicalize(causal_rows)
    fast, fast_duplicates = canonicalize(fast_rows)
    mismatches: list[dict[str, Any]] = []
    width = max(len(causal), len(fast))
    for index in range(width):
        left = causal[index] if index < len(causal) else None
        right = fast[index] if index < len(fast) else None
        if left != right:
            mismatches.append({"index": index, "causal": left, "fast": right})
            if len(mismatches) >= 20:
                break
    duplicate_mismatch = causal_duplicates != fast_duplicates
    mismatch_count = sum(
        1
        for index in range(width)
        if (causal[index] if index < len(causal) else None)
        != (fast[index] if index < len(fast) else None)
    ) + int(duplicate_mismatch)
    return {
        "mismatch_count": mismatch_count,
        "causal_canonical_rows": len(causal),
        "fast_canonical_rows": len(fast),
        "causal_duplicate_rows": causal_duplicates,
        "fast_duplicate_rows": fast_duplicates,
        "sample_mismatches": mismatches,
    }


def build_freeze_manifest(repository_root: Path = Path(".")) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for relative in SEMANTIC_FILES:
        path = repository_root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        files[relative] = {"sha256": _sha256(path), "size_bytes": path.stat().st_size}
    payload = {
        "p8_id": P8_ID,
        "candidate_id": CANDIDATE_ID,
        "p7_recognition_id": RECOGNITION_ID,
        "git_commit_sha": os.environ.get("GITHUB_SHA", "LOCAL_UNSET"),
        "required_file_count": len(SEMANTIC_FILES),
        "hashed_file_count": len(files),
        "missing_files": missing,
        "files": dict(sorted(files.items())),
    }
    _assert_no_outcomes(payload)
    return payload


def execute(root: Path = DATA_ROOT) -> dict[str, Any]:
    manifest, candles_by_symbol = load_locked_dataset(root)
    causal_rows, causal_diagnostics = _scan_causal(candles_by_symbol)
    fast_rows, fast_diagnostics = _scan_fast(candles_by_symbol)
    equivalence = compare_paths(causal_rows, fast_rows)
    freeze = build_freeze_manifest()
    freeze_complete = not freeze["missing_files"] and freeze["hashed_file_count"] == freeze["required_file_count"]
    contract = {
        "source": manifest["source"],
        "interval": manifest["interval"],
        "start_inclusive": manifest["start_inclusive"],
        "end_inclusive": manifest["end_inclusive"],
        "symbols": list(ALLOWED_SYMBOLS),
        "directions": list(ALLOWED_DIRECTIONS),
        "fold_count": 10,
        "global_fingerprint_dedupe": True,
        "recognition_id": RECOGNITION_ID,
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
        "causal_diagnostics": causal_diagnostics,
        "fast_diagnostics": fast_diagnostics,
    }
    _assert_no_outcomes(report)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    FREEZE_PATH.write_text(json.dumps(freeze, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main() -> int:
    report = execute()
    print(json.dumps({
        "p8_id": report["p8_id"],
        "status": report["status"],
        "mismatch_count": report["equivalence"]["mismatch_count"],
        "freeze_complete": report["freeze_complete"],
    }, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
