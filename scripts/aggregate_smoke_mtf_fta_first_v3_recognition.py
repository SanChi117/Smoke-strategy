#!/usr/bin/env python3
"""Aggregate exactly 100 outcome-blind FTA-first V3 recognition partitions."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from strategy_lab.mtf_fta_first_no_pnl_v3 import assert_outcome_blind, json_safe


STUDY_ID = "SMOKE_MTF_FTA_FIRST_V3_RECOGNITION_V1"
CANDIDATE_ID = "SMOKE_MTF_FTA_FIRST_V3_FROZEN_CANDIDATE_1"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AAVEUSDT")
SIDES = ("long", "short")
FOLDS = tuple(range(10))
EXPECTED_KEYS = {f"{fold}:{symbol}:{side}" for fold in FOLDS for symbol in SYMBOLS for side in SIDES}


def _merge_counter(parts: Iterable[Mapping[str, Any]], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for part in parts:
        values = part.get(field) or {}
        counter.update({str(key): int(value) for key, value in values.items()})
    return dict(counter.most_common())


def _fingerprint(record: Mapping[str, Any]) -> str:
    value = record.get("independent_fingerprint")
    if not isinstance(value, str) or not value:
        raise AssertionError("independent ENTRY_READY record lacks fingerprint")
    return value


def load_parts(input_dir: str | Path) -> list[dict[str, Any]]:
    paths = sorted(Path(input_dir).rglob("*.json"))
    rows: list[dict[str, Any]] = []
    keys: set[str] = set()
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("study_id") != STUDY_ID or not payload.get("partition_key"):
            continue
        assert_outcome_blind(payload)
        if payload.get("candidate_id") != CANDIDATE_ID:
            raise AssertionError(f"wrong candidate in {path}")
        contract = payload.get("contract") or {}
        required = (
            contract.get("closed_candles_only") is True,
            contract.get("future_outcomes_excluded") is True,
            contract.get("profitability_metrics_excluded") is True,
            int(contract.get("minimum_independent_cases_before_profitability") or 0) == 60,
        )
        if not all(required):
            raise AssertionError(f"invalid no-outcome contract in {path}")
        key = str(payload["partition_key"])
        if key in keys:
            raise AssertionError(f"duplicate partition key: {key}")
        keys.add(key)
        rows.append(payload)

    if len(rows) != 100 or keys != EXPECTED_KEYS:
        missing = sorted(EXPECTED_KEYS - keys)
        extra = sorted(keys - EXPECTED_KEYS)
        raise AssertionError(
            f"partition contract mismatch: rows={len(rows)} unique={len(keys)} missing={missing} extra={extra}"
        )
    return rows


def aggregate(parts: list[dict[str, Any]]) -> dict[str, Any]:
    fingerprints: dict[str, dict[str, Any]] = {}
    for part in parts:
        for raw_record in part.get("independent_entry_ready") or []:
            record = json_safe(raw_record)
            assert_outcome_blind(record)
            fp = _fingerprint(record)
            existing = fingerprints.get(fp)
            if existing is not None and existing != record:
                raise AssertionError(f"fingerprint collision with unequal records: {fp}")
            fingerprints.setdefault(fp, record)

    evaluated = sum(int(part.get("evaluated_15m_snapshots") or 0) for part in parts)
    allowed = sum(int(part.get("allowed_snapshots") or 0) for part in parts)

    per_fold: dict[str, dict[str, int]] = {}
    for fold in FOLDS:
        selected = [part for part in parts if int(part.get("fold")) == fold]
        fold_fps = {
            _fingerprint(record)
            for part in selected
            for record in (part.get("independent_entry_ready") or [])
        }
        per_fold[str(fold)] = {
            "partition_count": len(selected),
            "evaluated_15m_snapshots": sum(int(part.get("evaluated_15m_snapshots") or 0) for part in selected),
            "allowed_snapshots": sum(int(part.get("allowed_snapshots") or 0) for part in selected),
            "independent_entry_ready_count": len(fold_fps),
        }

    per_symbol: dict[str, dict[str, int]] = {}
    for symbol in SYMBOLS:
        selected = [part for part in parts if part.get("symbol") == symbol]
        symbol_fps = {
            _fingerprint(record)
            for part in selected
            for record in (part.get("independent_entry_ready") or [])
        }
        per_symbol[symbol] = {
            "partition_count": len(selected),
            "evaluated_15m_snapshots": sum(int(part.get("evaluated_15m_snapshots") or 0) for part in selected),
            "allowed_snapshots": sum(int(part.get("allowed_snapshots") or 0) for part in selected),
            "independent_entry_ready_count": len(symbol_fps),
        }

    independent_count = len(fingerprints)
    gate_passed = independent_count >= 60
    payload: dict[str, Any] = {
        "study_id": STUDY_ID,
        "mode": "OUTCOME_BLIND_PARTITIONED_RECOGNITION",
        "candidate_id": CANDIDATE_ID,
        "partition_count": len(parts),
        "symbols": list(SYMBOLS),
        "sides": list(SIDES),
        "folds": list(FOLDS),
        "recognition_start": "2025-01-01",
        "recognition_end_exclusive": "2026-07-01",
        "evaluated_15m_snapshots": evaluated,
        "state_counts": _merge_counter(parts, "state_counts"),
        "reason_counts": _merge_counter(parts, "reason_counts"),
        "route_counts": _merge_counter(parts, "route_counts"),
        "target_timeframe_counts": _merge_counter(parts, "target_timeframe_counts"),
        "stop_source_counts": _merge_counter(parts, "stop_source_counts"),
        "allowed_snapshots_before_global_dedup": allowed,
        "independent_entry_ready_count": independent_count,
        "duplicate_allowed_snapshots": allowed - independent_count,
        "minimum_independent_entry_ready_required": 60,
        "recognition_gate_passed": gate_passed,
        "decision": (
            "READY_FOR_SEMANTIC_REPLAY"
            if gate_passed
            else "CLOSE_V3_WITHOUT_PROFITABILITY_TEST"
        ),
        "independent_entry_ready": [fingerprints[key] for key in sorted(fingerprints)],
        "per_fold": per_fold,
        "per_symbol": per_symbol,
        "contract": {
            "closed_candles_only": True,
            "future_outcomes_excluded": True,
            "profitability_metrics_excluded": True,
            "global_fingerprint_deduplication": True,
            "threshold_tuning_performed": False,
        },
    }
    assert_outcome_blind(payload)
    return payload


def _nested(record: Mapping[str, Any], *keys: str) -> Any:
    value: Any = record
    for key in keys:
        if not isinstance(value, Mapping):
            return ""
        value = value.get(key)
    return "" if value is None else value


def write_outputs(payload: dict[str, Any], out_path: str | Path) -> None:
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    csv_path = output.parent / "independent_entry_ready.csv"
    fields = (
        "independent_fingerprint", "fold", "partition_key", "symbol", "side",
        "evaluated_at", "entry_time", "entry", "stop", "target", "rr", "quality_score",
        "external_fta_timeframe", "external_fta_source", "route", "bos_signal_time",
        "pullback_time", "stop_timeframe", "stop_source",
    )
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in payload["independent_entry_ready"]:
            writer.writerow({
                "independent_fingerprint": record.get("independent_fingerprint", ""),
                "fold": record.get("fold", ""),
                "partition_key": record.get("partition_key", ""),
                "symbol": record.get("symbol", ""),
                "side": record.get("side", ""),
                "evaluated_at": record.get("evaluated_at", ""),
                "entry_time": record.get("entry_time", ""),
                "entry": record.get("entry", ""),
                "stop": record.get("stop", ""),
                "target": record.get("target", ""),
                "rr": record.get("rr", ""),
                "quality_score": record.get("quality_score", ""),
                "external_fta_timeframe": _nested(record, "external_fta", "timeframe"),
                "external_fta_source": _nested(record, "external_fta", "source"),
                "route": _nested(record, "route", "name"),
                "bos_signal_time": _nested(record, "bos", "signal_bar", "close_time"),
                "pullback_time": _nested(record, "pullback", "bar", "close_time"),
                "stop_timeframe": _nested(record, "stop_selection", "timeframe"),
                "stop_source": _nested(record, "stop_selection", "source"),
            })

    md = [
        "# SMOKE MTF FTA-First V3 Recognition Result",
        "",
        f"- Partitions: **{payload['partition_count']}/100**",
        f"- Evaluated 15m snapshots: **{payload['evaluated_15m_snapshots']}**",
        f"- Allowed snapshots before dedup: **{payload['allowed_snapshots_before_global_dedup']}**",
        f"- Independent ENTRY_READY: **{payload['independent_entry_ready_count']}**",
        f"- Required: **{payload['minimum_independent_entry_ready_required']}**",
        f"- Recognition gate: **{'PASS' if payload['recognition_gate_passed'] else 'FAIL'}**",
        f"- Decision: `{payload['decision']}`",
        "",
        "No future outcomes or profitability metrics were used.",
    ]
    (output.parent / "RECOGNITION_RESULT.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    parts = load_parts(args.input_dir)
    payload = aggregate(parts)
    write_outputs(payload, args.out)
    print(json.dumps({
        "partition_count": payload["partition_count"],
        "evaluated_15m_snapshots": payload["evaluated_15m_snapshots"],
        "independent_entry_ready_count": payload["independent_entry_ready_count"],
        "decision": payload["decision"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
