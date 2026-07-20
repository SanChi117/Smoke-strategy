#!/usr/bin/env python3
"""Build causal semantic-review packets for frozen SMOKE MTF V2 cases.

Only information available at each evaluation timestamp is exported. The
current recognition model must reproduce the frozen candidate payload exactly;
otherwise the replay fails before writing a review artifact.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from strategy_lab.market_data import parse_dt, read_candles_csv, validate_candles
from strategy_lab.mtf_dealing_range_v2 import MtfDealingRangeEngine
from strategy_lab.mtf_entry_model_v2 import MtfEntryModelV2
from strategy_lab.mtf_recognition_export_v2 import assert_no_outcome_fields, plan_payload
from strategy_lab.mtf_recognition_fast_runtime_v2 import install_fast_runtime

WINDOWS = {
    "5m": 144,
    "15m": 192,
    "1h": 168,
    "4h": 180,
    "1d": 240,
    "1w": 80,
    "1M": 24,
}

INDEX_FIELDS = [
    "review_index",
    "case_id",
    "cluster_size",
    "timestamp",
    "symbol",
    "side",
    "setup_state",
    "scenario",
    "route",
    "poi_timeframe",
    "m5_bos",
    "entry_ready",
    "planned_rr",
    "quality_state",
    "packet_file",
]


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {field.name: jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(child) for child in value]
    return value


def case_identity(row: dict[str, Any]) -> dict[str, Any]:
    poi = row.get("poi") or {}
    return {
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "setup_state": row.get("setup_state"),
        "scenario": row.get("scenario"),
        "monthly_state": row.get("monthly_state"),
        "weekly_state": row.get("weekly_state"),
        "daily_state": row.get("daily_state"),
        "h4_state": row.get("h4_state"),
        "h1_state": row.get("h1_state"),
        "poi": {
            "timeframe": poi.get("timeframe"),
            "kind": poi.get("kind"),
            "side": poi.get("side"),
            "low": poi.get("low"),
            "high": poi.get("high"),
            "confirmed_at": poi.get("confirmed_at"),
            "source": poi.get("source"),
        },
        "h1_raid": row.get("h1_raid"),
        "h1_vc": row.get("h1_vc"),
        "vc_zone_test": row.get("vc_zone_test"),
        "m5_bos": row.get("m5_bos"),
        "entry_ready": row.get("entry_ready"),
        "target_timeframe": row.get("target_timeframe"),
        "target_source": row.get("target_source"),
    }


def case_fingerprint(row: dict[str, Any]) -> str:
    raw = json.dumps(case_identity(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def frozen_unique_cases(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], Counter[str]]:
    ordered = sorted(rows, key=lambda row: (row["timestamp"], row["symbol"], row["side"]))
    clusters = Counter(case_fingerprint(row) for row in ordered)
    unique: dict[str, dict[str, Any]] = {}
    for row in ordered:
        unique.setdefault(case_fingerprint(row), row)
    cases = sorted(
        unique.values(),
        key=lambda row: (-int(row.get("stage_rank", -1)), row["timestamp"], row["symbol"], row["side"]),
    )
    return cases, clusters


def closed_window(engine: MtfDealingRangeEngine, symbol: str, timeframe: str, timestamp: datetime) -> list[dict[str, Any]]:
    rows = [
        bar
        for bar in engine.bars[timeframe]
        if bar.symbol == symbol and bar.close_time <= timestamp
    ][-WINDOWS[timeframe] :]
    return [jsonable(bar) for bar in rows]


def first_difference(expected: Any, actual: Any, path: str = "root") -> str | None:
    if type(expected) is not type(actual):
        return f"{path}: type {type(expected).__name__} != {type(actual).__name__}"
    if isinstance(expected, dict):
        if set(expected) != set(actual):
            missing = sorted(set(expected) - set(actual))
            extra = sorted(set(actual) - set(expected))
            return f"{path}: key mismatch missing={missing} extra={extra}"
        for key in expected:
            difference = first_difference(expected[key], actual[key], f"{path}.{key}")
            if difference:
                return difference
        return None
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return f"{path}: length {len(expected)} != {len(actual)}"
        for index, (left, right) in enumerate(zip(expected, actual)):
            difference = first_difference(left, right, f"{path}[{index}]")
            if difference:
                return difference
        return None
    if isinstance(expected, float):
        if abs(expected - actual) > 1e-9 * max(1.0, abs(expected), abs(actual)):
            return f"{path}: {expected} != {actual}"
        return None
    if expected != actual:
        return f"{path}: {expected!r} != {actual!r}"
    return None


def route_name(plan) -> str:
    if plan.raid is not None:
        return "fresh_h1_raid"
    if plan.volume_confirmation is not None:
        return "h1_vc_with_15m_test" if plan.vc_test is not None else "h1_vc_waiting_15m_test"
    return "none"


def build_packet(
    engine: MtfDealingRangeEngine,
    model: MtfEntryModelV2,
    frozen: dict[str, Any],
    review_index: int,
    cluster_size: int,
) -> dict[str, Any]:
    timestamp = parse_dt(frozen["timestamp"])
    plan = model.evaluate(frozen["symbol"], timestamp, frozen["side"])
    replayed = plan_payload(plan)
    difference = first_difference(frozen, replayed)
    if difference:
        raise RuntimeError(
            f"Frozen replay mismatch for {frozen['symbol']} {frozen['side']} "
            f"{frozen['timestamp']}: {difference}"
        )

    packet = {
        "study_id": "SMOKE_MTF_V2_SEMANTIC_REPLAY_PACKET_V1",
        "mode": "CLOSED_INFORMATION_ONLY_NO_OUTCOME_FIELDS",
        "review_index": review_index,
        "case_id": case_fingerprint(frozen),
        "cluster_size": cluster_size,
        "frozen_payload_exact_match": True,
        "timestamp": frozen["timestamp"],
        "symbol": frozen["symbol"],
        "side": frozen["side"],
        "setup_state": frozen["setup_state"],
        "route": route_name(plan),
        "frozen_candidate": frozen,
        "decision_trace": {
            "context": jsonable(plan.context),
            "poi": jsonable(plan.poi),
            "raid": jsonable(plan.raid),
            "h1_reaction_diagnostic": plan.h1_reaction,
            "volume_confirmation": jsonable(plan.volume_confirmation),
            "vc_zone_test": jsonable(plan.vc_test),
            "m5_bos": jsonable(plan.bos),
            "planned_execution": {
                "entry_time": jsonable(plan.entry_time),
                "entry_open_price": plan.entry,
                "stop": plan.stop,
                "target": plan.target,
                "target_timeframe": plan.target_timeframe,
                "target_source": plan.target_source,
                "rr": plan.rr,
                "allowed": plan.allowed,
            },
            "event_risk": {
                "blocked": plan.event_blocked,
                "risk_multiplier": plan.event_risk_multiplier,
            },
            "reasons": list(plan.reasons),
        },
        "closed_candle_windows": {
            timeframe: closed_window(engine, frozen["symbol"], timeframe, timestamp)
            for timeframe in WINDOWS
        },
        "human_semantic_review": {
            "macro_context_correct": None,
            "active_dealing_range_correct": None,
            "poi_correct": None,
            "fresh_raid_correct": None,
            "h1_vc_correct": None,
            "late_15m_test_correct": None,
            "m5_body_close_bos_correct": None,
            "structural_stop_correct": None,
            "timeframe_fta_correct": None,
            "verdict": "UNREVIEWED",
            "notes": "",
        },
    }
    assert_no_outcome_fields(packet)
    return packet


def main() -> int:
    parser = argparse.ArgumentParser(description="Build SMOKE MTF V2 causal semantic replay packets")
    parser.add_argument("--candles", required=True)
    parser.add_argument("--frozen-candidates", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()

    candles = read_candles_csv(args.candles)
    validate_candles(candles)
    frozen_payload = json.loads(Path(args.frozen_candidates).read_text(encoding="utf-8"))
    assert_no_outcome_fields(frozen_payload)
    if frozen_payload.get("mode") != "NO_PNL_NO_FUTURE_OUTCOME":
        raise RuntimeError("unexpected frozen recognition mode")
    rows = frozen_payload.get("candidates")
    if not isinstance(rows, list):
        raise RuntimeError("frozen candidates are missing")

    cases, clusters = frozen_unique_cases(rows)
    engine = MtfDealingRangeEngine(candles)
    runtime = install_fast_runtime(engine)
    model = MtfEntryModelV2(engine)
    out = Path(args.out_dir)
    packets_dir = out / "packets"
    packets_dir.mkdir(parents=True, exist_ok=True)

    index_rows: list[dict[str, Any]] = []
    for review_index, frozen in enumerate(cases, start=1):
        case_id = case_fingerprint(frozen)
        packet = build_packet(engine, model, frozen, review_index, clusters[case_id])
        filename = f"{review_index:04d}_{frozen['symbol']}_{frozen['side']}_{frozen['setup_state']}_{case_id}.json"
        (packets_dir / filename).write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        poi = frozen.get("poi") or {}
        index_rows.append(
            {
                "review_index": review_index,
                "case_id": case_id,
                "cluster_size": clusters[case_id],
                "timestamp": frozen["timestamp"],
                "symbol": frozen["symbol"],
                "side": frozen["side"],
                "setup_state": frozen["setup_state"],
                "scenario": frozen.get("scenario"),
                "route": packet["route"],
                "poi_timeframe": poi.get("timeframe"),
                "m5_bos": frozen.get("m5_bos"),
                "entry_ready": frozen.get("entry_ready"),
                "planned_rr": frozen.get("planned_rr"),
                "quality_state": frozen.get("quality_state"),
                "packet_file": f"packets/{filename}",
            }
        )

    with (out / "semantic_replay_index.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(index_rows)

    summary = {
        "study_id": "SMOKE_MTF_V2_SEMANTIC_REPLAY_V1",
        "mode": "CLOSED_INFORMATION_ONLY_NO_OUTCOME_FIELDS",
        "frozen_rows": len(rows),
        "unique_cases": len(cases),
        "repeated_rows": len(rows) - len(cases),
        "exact_replay_matches": len(cases),
        "exact_replay_mismatches": 0,
        "state_counts": dict(Counter(row["setup_state"] for row in cases)),
        "route_counts": dict(Counter(row["route"] for row in index_rows)),
        "entry_ready_cases": sum(bool(row["entry_ready"]) for row in index_rows),
        "runtime_cache": runtime.stats(),
        "candle_windows": WINDOWS,
        "review_rule": "semantic correctness only; no outcome or profitability information",
    }
    assert_no_outcome_fields(summary)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "semantic_replay_index.json").write_text(json.dumps(index_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Built {len(cases)} exact causal replay packets from {len(rows)} frozen rows; "
        "no outcome fields exported"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
