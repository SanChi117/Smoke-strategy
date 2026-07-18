#!/usr/bin/env python3
"""Labelled candle replay for SMOKE MTF V2 recognition and entry states.

The replay compares model states with human-labelled expectations. It contains
no PnL fields and cannot be used to tune profitability.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable

from strategy_lab.market_data import Candle, parse_dt
from strategy_lab.mtf_dealing_range_v2 import MtfDealingRangeEngine
from strategy_lab.mtf_entry_model_v2 import EntryConfig, MtfEntryModelV2


SUPPORTED_EXPECTATIONS = {
    "scenario",
    "daily_state",
    "h4_state",
    "h1_state",
    "long_allowed",
    "short_allowed",
    "setup_state",
    "allowed",
    "poi_required",
    "poi_timeframe",
    "poi_kind",
    "poi_side",
    "h1_raid",
    "h1_reaction",
    "h1_vc",
    "bos_required",
    "entry_required",
    "required_reasons",
    "forbidden_reasons",
}


@dataclass(frozen=True)
class ReplayMismatch:
    case_id: str
    field: str
    expected: Any
    actual: Any


@dataclass(frozen=True)
class ReplayCaseResult:
    case_id: str
    symbol: str
    timestamp: str
    side: str
    passed: bool
    mismatches: tuple[ReplayMismatch, ...]
    observation: dict[str, Any]


@dataclass(frozen=True)
class LabelledReplayReport:
    study_id: str
    case_count: int
    passed_count: int
    failed_count: int
    results: tuple[ReplayCaseResult, ...]

    @property
    def ok(self) -> bool:
        return self.failed_count == 0


def _observation(model: MtfEntryModelV2, symbol: str, timestamp: datetime, side: str) -> dict[str, Any]:
    plan = model.evaluate(symbol, timestamp, side)
    poi = plan.poi
    return {
        "scenario": plan.context.scenario.value,
        "daily_state": plan.context.daily.state.value,
        "h4_state": plan.context.h4.state.value,
        "h1_state": plan.context.h1.state.value,
        "long_allowed": plan.context.long_allowed,
        "short_allowed": plan.context.short_allowed,
        "setup_state": plan.setup_state.value,
        "allowed": plan.allowed,
        "poi_required": poi is not None,
        "poi_timeframe": poi.timeframe if poi else None,
        "poi_kind": poi.kind if poi else None,
        "poi_side": poi.side if poi else None,
        "h1_raid": plan.h1_raid,
        "h1_reaction": plan.h1_reaction,
        "h1_vc": plan.h1_vc,
        "bos_required": plan.bos is not None,
        "entry_required": plan.entry is not None,
        "entry_time": plan.entry_time.isoformat() if plan.entry_time else None,
        "entry": plan.entry,
        "stop": plan.stop,
        "target": plan.target,
        "rr": plan.rr,
        "quality_score": plan.quality_score,
        "quality_state": plan.quality_state,
        "reasons": list(plan.reasons),
    }


def compare_expectation(case_id: str, expected: dict[str, Any], actual: dict[str, Any]) -> tuple[ReplayMismatch, ...]:
    mismatches: list[ReplayMismatch] = []
    unknown = sorted(set(expected) - SUPPORTED_EXPECTATIONS)
    for field in unknown:
        mismatches.append(ReplayMismatch(case_id, field, "supported expectation", "unknown field"))
    for field in sorted(set(expected) & SUPPORTED_EXPECTATIONS):
        wanted = expected[field]
        if field == "required_reasons":
            reasons = [str(item) for item in actual.get("reasons", [])]
            for token in wanted:
                if not any(str(token) in reason for reason in reasons):
                    mismatches.append(ReplayMismatch(case_id, field, token, reasons))
            continue
        if field == "forbidden_reasons":
            reasons = [str(item) for item in actual.get("reasons", [])]
            for token in wanted:
                if any(str(token) in reason for reason in reasons):
                    mismatches.append(ReplayMismatch(case_id, field, f"not {token}", reasons))
            continue
        observed = actual.get(field)
        if observed != wanted:
            mismatches.append(ReplayMismatch(case_id, field, wanted, observed))
    return tuple(mismatches)


def validate_label_payload(payload: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if payload.get("pnl_labels_forbidden") is not True:
        raise ValueError("label set must explicitly forbid PnL labels")
    study_id = str(payload.get("study_id") or "")
    if not study_id:
        raise ValueError("study_id is required")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases must be a non-empty list")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"cases[{index}] must be an object")
        case_id = str(case.get("id") or "")
        if not case_id or case_id in seen:
            raise ValueError(f"cases[{index}] has missing or duplicate id")
        seen.add(case_id)
        side = str(case.get("side") or "").lower()
        if side not in {"long", "short"}:
            raise ValueError(f"{case_id}: side must be long or short")
        expected = case.get("expected")
        if not isinstance(expected, dict) or not expected:
            raise ValueError(f"{case_id}: expected must be a non-empty object")
        normalized.append(
            {
                "id": case_id,
                "symbol": str(case.get("symbol") or "").upper(),
                "timestamp": parse_dt(case.get("timestamp")),
                "side": side,
                "expected": expected,
            }
        )
        if not normalized[-1]["symbol"]:
            raise ValueError(f"{case_id}: symbol is required")
    return study_id, normalized


def run_labelled_replay(
    candles: Iterable[Candle],
    labels: dict[str, Any],
    config: EntryConfig | None = None,
) -> LabelledReplayReport:
    study_id, cases = validate_label_payload(labels)
    engine = MtfDealingRangeEngine(candles)
    model = MtfEntryModelV2(engine, config)
    results: list[ReplayCaseResult] = []
    for case in cases:
        actual = _observation(model, case["symbol"], case["timestamp"], case["side"])
        mismatches = compare_expectation(case["id"], case["expected"], actual)
        results.append(
            ReplayCaseResult(
                case_id=case["id"],
                symbol=case["symbol"],
                timestamp=case["timestamp"].isoformat(),
                side=case["side"],
                passed=not mismatches,
                mismatches=mismatches,
                observation=actual,
            )
        )
    passed = sum(1 for result in results if result.passed)
    return LabelledReplayReport(
        study_id=study_id,
        case_count=len(results),
        passed_count=passed,
        failed_count=len(results) - passed,
        results=tuple(results),
    )


def report_as_dict(report: LabelledReplayReport) -> dict[str, Any]:
    return asdict(report) | {"ok": report.ok}
