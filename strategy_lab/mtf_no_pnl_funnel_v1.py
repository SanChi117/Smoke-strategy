#!/usr/bin/env python3
"""Outcome-blind funnel accounting for the frozen SMOKE MTF V2 recognizer."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from hashlib import sha256
import json
import re
from typing import Any, Mapping

STAGES = (
    "CLOSED_DATA_AVAILABLE",
    "CONTEXT_ALIGNED",
    "ACTIVE_POI",
    "ROUTE_TRIGGERED",
    "POI_TESTED",
    "M5_BOS_CONFIRMED",
    "NEXT_15M_EXECUTION_ELIGIBLE",
    "STRUCTURAL_STOP_VALID",
    "ACTIVE_FTA_VALID",
    "RR_GATE_PASSED",
    "ENTRY_READY",
)

_FORBIDDEN_FRAGMENTS = (
    "pnl", "future_return", "trade_outcome", "tp_result", "sl_result",
    "mfe", "mae", "win_rate", "profit_factor", "net_return", "drawdown",
    "exit_time", "exit_price", "exit_reason", "gross_return", "funding_return",
)


def contiguous_fold_bounds(start: datetime, end: datetime, folds: int = 10) -> list[tuple[datetime, datetime]]:
    if folds <= 0 or end <= start:
        raise ValueError("invalid fold request")
    total_days = (end - start).days
    if start + timedelta(days=total_days) != end:
        raise ValueError("audit bounds must be whole UTC days")
    base_days, extra = divmod(total_days, folds)
    if base_days <= 0:
        raise ValueError("not enough days for requested folds")
    output: list[tuple[datetime, datetime]] = []
    cursor = start
    for index in range(folds):
        days = base_days + (1 if index < extra else 0)
        right = cursor + timedelta(days=days)
        output.append((cursor, right))
        cursor = right
    if cursor != end:
        raise AssertionError("fold construction did not cover the full period")
    return output


def assert_no_outcome_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = re.sub(r"[^a-z0-9]+", "_", str(raw_key).lower()).strip("_")
            for fragment in _FORBIDDEN_FRAGMENTS:
                if fragment in key:
                    raise AssertionError(f"forbidden outcome field at {path}.{raw_key}: {fragment}")
            assert_no_outcome_fields(child, f"{path}.{raw_key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            assert_no_outcome_fields(child, f"{path}[{index}]")


def route_name(plan: Any) -> str:
    if bool(plan.h1_raid):
        return "fresh_h1_raid"
    if bool(plan.h1_vc) and bool(plan.vc_zone_test):
        return "h1_vc_with_15m_test"
    if bool(plan.h1_vc):
        return "h1_vc_unretested"
    return "none"


def stage_flags(plan: Any, side: str, min_rr: float) -> dict[str, bool]:
    direction_allowed = bool(plan.context.long_allowed if side == "long" else plan.context.short_allowed)
    active_poi = bool(direction_allowed and plan.poi is not None)
    route_triggered = bool(active_poi and (plan.h1_raid or plan.h1_vc))
    poi_tested = bool(route_triggered and (plan.h1_raid or plan.vc_zone_test))
    bos_confirmed = bool(poi_tested and plan.bos is not None)
    execution_eligible = bool(bos_confirmed and plan.entry is not None)
    stop_valid = bool(
        execution_eligible and plan.stop is not None and
        ((side == "long" and plan.stop < plan.entry) or (side == "short" and plan.stop > plan.entry))
    )
    fta_geometry_valid = bool(
        plan.target is not None and
        ((side == "long" and plan.target > plan.entry) or (side == "short" and plan.target < plan.entry))
    ) if execution_eligible else False
    fta_valid = bool(stop_valid and fta_geometry_valid)
    rr_passed = bool(fta_valid and plan.rr is not None and plan.rr >= min_rr)
    entry_ready = bool(rr_passed and plan.allowed)
    return {
        "CLOSED_DATA_AVAILABLE": True,
        "CONTEXT_ALIGNED": direction_allowed,
        "ACTIVE_POI": active_poi,
        "ROUTE_TRIGGERED": route_triggered,
        "POI_TESTED": poi_tested,
        "M5_BOS_CONFIRMED": bos_confirmed,
        "NEXT_15M_EXECUTION_ELIGIBLE": execution_eligible,
        "STRUCTURAL_STOP_VALID": stop_valid,
        "ACTIVE_FTA_VALID": fta_valid,
        "RR_GATE_PASSED": rr_passed,
        "ENTRY_READY": entry_ready,
    }


def geometry_record(plan: Any, side: str) -> dict[str, Any] | None:
    if plan.entry is None:
        return None
    record: dict[str, Any] = {
        "evaluated_at": plan.evaluated_at.isoformat(),
        "setup_state": plan.setup_state.value,
        "route": route_name(plan),
        "quality_score": round(float(plan.quality_score), 6),
    }
    if plan.stop is not None:
        stop_distance = ((plan.entry - plan.stop) / plan.entry if side == "long" else (plan.stop - plan.entry) / plan.entry)
        record["structural_stop_distance_fraction"] = round(float(stop_distance), 12)
    if plan.target is not None:
        fta_distance = ((plan.target - plan.entry) / plan.entry if side == "long" else (plan.entry - plan.target) / plan.entry)
        record["active_fta_distance_fraction"] = round(float(fta_distance), 12)
        record["target_timeframe"] = str(plan.target_timeframe or "")
        record["target_source"] = str(plan.target_source or "")
    if plan.rr is not None:
        record["structural_rr"] = round(float(plan.rr), 8)
    return record


def structural_fingerprint(plan: Any, side: str) -> str | None:
    if plan.poi is None and plan.bos is None and not plan.h1_raid and not plan.h1_vc:
        return None
    poi = plan.poi
    raid = plan.raid
    bos = plan.bos
    payload = {
        "symbol": plan.symbol,
        "side": side,
        "scenario": plan.context.scenario.value,
        "poi": None if poi is None else {
            "timeframe": poi.timeframe, "kind": poi.kind, "source": poi.source,
            "confirmed_at": poi.confirmed_at.isoformat(), "low": round(poi.low, 8), "high": round(poi.high, 8),
        },
        "route": route_name(plan),
        "raid": None if raid is None else {
            "pivot_time": raid.pivot.confirmed_at.isoformat(), "raid_time": raid.raid_bar.close_time.isoformat(),
        },
        "bos": None if bos is None else {
            "pivot_time": bos.pivot.confirmed_at.isoformat(), "signal_time": bos.signal_bar.close_time.isoformat(),
        },
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def transition_rates(stage_counts: Mapping[str, int]) -> dict[str, dict[str, float | int]]:
    output: dict[str, dict[str, float | int]] = {}
    for left, right in zip(STAGES, STAGES[1:]):
        denominator = int(stage_counts.get(left, 0))
        numerator = int(stage_counts.get(right, 0))
        output[f"{left}->{right}"] = {
            "from_count": denominator,
            "to_count": numerator,
            "rate": round(numerator / denominator, 8) if denominator else 0.0,
        }
    return output


def merge_counter_dicts(rows: list[Mapping[str, int]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        counter.update({str(key): int(value) for key, value in row.items()})
    return dict(sorted(counter.items()))
