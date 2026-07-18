#!/usr/bin/env python3
"""Smoke tests for the frozen SMOKE MTF V2 semantic reference set."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from strategy_lab.mtf_reference_validation import validate_reference_payload


REFERENCE = Path("research/smoke_mtf_v2_reference_scenarios.json")


def payload() -> dict:
    return json.loads(REFERENCE.read_text(encoding="utf-8"))


def test_committed_reference_set_is_valid() -> None:
    report = validate_reference_payload(payload())
    assert report.ok, report.errors
    assert report.scenario_count == 8
    assert report.positive_count == 4
    assert report.blocked_count == 4
    assert report.source_count == 4


def test_stage_shortcut_is_rejected() -> None:
    broken = deepcopy(payload())
    scenario = broken["scenarios"][0]
    scenario["required_stages"] = [
        "MACRO_CONTEXT",
        "M5_CONFIRMED_BOS",
        "M15_NEXT_OPEN",
        "HTF_POI",
    ]
    report = validate_reference_payload(broken)
    assert not report.ok
    assert any("canonical order" in error for error in report.errors)


def test_strong_level_cannot_replace_h1_and_5m_trigger() -> None:
    broken = deepcopy(payload())
    scenario = broken["scenarios"][1]
    scenario["required_stages"] = [
        "MACRO_CONTEXT",
        "DAILY_DEALING_RANGE",
        "H4_DEALING_RANGE",
        "HTF_POI",
        "M15_NEXT_OPEN",
        "STRUCTURAL_STOP",
        "HTF_TARGET",
    ]
    scenario["required_trigger"] = ["strong_level_only"]
    report = validate_reference_payload(broken)
    assert not report.ok
    assert any("full state chain" in error or "5m BOS" in error for error in report.errors)


def test_pnl_mutability_is_rejected() -> None:
    broken = deepcopy(payload())
    broken["pnl_usage_forbidden"] = False
    report = validate_reference_payload(broken)
    assert not report.ok
    assert any("PnL" in error for error in report.errors)


def main() -> int:
    test_committed_reference_set_is_valid()
    test_stage_shortcut_is_rejected()
    test_strong_level_cannot_replace_h1_and_5m_trigger()
    test_pnl_mutability_is_rejected()
    print("SMOKE MTF V2 reference validation smoke tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
