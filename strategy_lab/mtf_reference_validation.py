#!/usr/bin/env python3
"""Semantic validation for Drive-derived SMOKE MTF V2 reference scenarios.

This layer checks the meaning and stage order of the strategy before any
profit-based development run. It does not claim to validate chart geometry;
that is handled by the labelled candle replay layer.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ReferenceValidationReport:
    study_id: str
    scenario_count: int
    positive_count: int
    blocked_count: int
    source_count: int
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


def _as_strings(value: Any, field: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        errors.append(f"{field} must be a non-empty string list")
        return []
    return list(value)


def _is_subsequence(values: Iterable[str], canonical: list[str]) -> bool:
    cursor = 0
    for value in values:
        try:
            cursor = canonical.index(value, cursor) + 1
        except ValueError:
            return False
    return True


def validate_reference_payload(payload: dict[str, Any]) -> ReferenceValidationReport:
    errors: list[str] = []
    study_id = str(payload.get("study_id") or "")
    if study_id != "SMOKE_MTF_V2_REFERENCE_SCENARIOS":
        errors.append("unexpected study_id")
    if payload.get("status") != "FROZEN_SEMANTIC_REFERENCE_SET":
        errors.append("reference set must be frozen")
    if payload.get("pnl_usage_forbidden") is not True:
        errors.append("PnL use must be forbidden during semantic validation")

    canonical = _as_strings(payload.get("canonical_stage_order"), "canonical_stage_order", errors)
    expected_canonical = [
        "MACRO_CONTEXT",
        "DAILY_DEALING_RANGE",
        "H4_DEALING_RANGE",
        "HTF_POI",
        "H1_REACTION_OR_RAID",
        "M5_CONFIRMED_BOS",
        "M15_NEXT_OPEN",
        "STRUCTURAL_STOP",
        "HTF_TARGET",
    ]
    if canonical and canonical != expected_canonical:
        errors.append("canonical stage order differs from the frozen MTF contract")

    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("sources must be a non-empty list")
        sources = []
    source_ids: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"sources[{index}] must be an object")
            continue
        source_id = str(source.get("drive_file_id") or "")
        if not source_id:
            errors.append(f"sources[{index}] missing drive_file_id")
        elif source_id in source_ids:
            errors.append(f"duplicate source id: {source_id}")
        source_ids.add(source_id)
        if not str(source.get("title") or ""):
            errors.append(f"sources[{index}] missing title")
        _as_strings(source.get("concepts"), f"sources[{index}].concepts", errors)

    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        errors.append("scenarios must be a non-empty list")
        scenarios = []

    scenario_ids: set[str] = set()
    positive_count = 0
    blocked_count = 0
    for index, scenario in enumerate(scenarios):
        prefix = f"scenarios[{index}]"
        if not isinstance(scenario, dict):
            errors.append(f"{prefix} must be an object")
            continue
        scenario_id = str(scenario.get("id") or "")
        if not scenario_id:
            errors.append(f"{prefix} missing id")
        elif scenario_id in scenario_ids:
            errors.append(f"duplicate scenario id: {scenario_id}")
        scenario_ids.add(scenario_id)

        direction = str(scenario.get("direction") or "")
        if direction not in {"long", "short", "none"}:
            errors.append(f"{prefix}.direction must be long, short or none")
        stages = _as_strings(scenario.get("required_stages"), f"{prefix}.required_stages", errors)
        if stages and not _is_subsequence(stages, canonical):
            errors.append(f"{scenario_id}: required_stages violate canonical order")

        expected_allowed = scenario.get("expected_allowed")
        if direction == "none" or expected_allowed is False:
            blocked_count += 1
            if expected_allowed is not False:
                errors.append(f"{scenario_id}: blocked scenario must set expected_allowed=false")
            if not str(scenario.get("block_reason") or ""):
                errors.append(f"{scenario_id}: blocked scenario missing block_reason")
            continue

        positive_count += 1
        required_full_chain = {
            "MACRO_CONTEXT",
            "DAILY_DEALING_RANGE",
            "H4_DEALING_RANGE",
            "HTF_POI",
            "H1_REACTION_OR_RAID",
            "M5_CONFIRMED_BOS",
            "M15_NEXT_OPEN",
            "STRUCTURAL_STOP",
            "HTF_TARGET",
        }
        if not required_full_chain.issubset(set(stages)):
            errors.append(f"{scenario_id}: positive scenario must contain the full state chain")
        if scenario.get("expected_entry_timeframe") != "15m":
            errors.append(f"{scenario_id}: execution timeframe must be 15m")
        if scenario.get("expected_execution") != "next_open":
            errors.append(f"{scenario_id}: execution must be next_open")

        triggers = " ".join(_as_strings(scenario.get("required_trigger"), f"{prefix}.required_trigger", errors)).lower()
        if "5m" not in triggers or "bos" not in triggers:
            errors.append(f"{scenario_id}: positive scenario must require 5m BOS")
        if "closed" not in triggers:
            errors.append(f"{scenario_id}: trigger must explicitly require closed candles")

        stop_anchor = str(scenario.get("stop_anchor") or "").lower()
        if "strong_" not in stop_anchor and "poi_invalidation" not in stop_anchor:
            errors.append(f"{scenario_id}: stop must use Strong High/Low or POI invalidation")
        target_anchor = str(scenario.get("target_anchor") or "").lower()
        if not any(token in target_anchor for token in ("eql", "eqh", "ssl", "bsl", "weak_", "fta")):
            errors.append(f"{scenario_id}: target must be anchored to HTF liquidity/FTA")

    forbidden = _as_strings(payload.get("forbidden_shortcuts"), "forbidden_shortcuts", errors)
    joined = " ".join(forbidden).lower()
    for required_phrase in ("strong level", "wick", "right-side", "15m open", "pnl"):
        if required_phrase not in joined:
            errors.append(f"forbidden_shortcuts missing concept: {required_phrase}")

    return ReferenceValidationReport(
        study_id=study_id,
        scenario_count=len(scenarios),
        positive_count=positive_count,
        blocked_count=blocked_count,
        source_count=len(sources),
        errors=tuple(errors),
    )


def load_and_validate_reference(path: str | Path) -> ReferenceValidationReport:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return ReferenceValidationReport("", 0, 0, 0, 0, ("root must be an object",))
    return validate_reference_payload(payload)
