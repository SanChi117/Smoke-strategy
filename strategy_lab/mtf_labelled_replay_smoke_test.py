#!/usr/bin/env python3
"""Contract tests for labelled SMOKE MTF V2 replay."""
from __future__ import annotations

from strategy_lab.mtf_labelled_replay import compare_expectation, validate_label_payload


def test_compare_exact_and_reason_tokens() -> None:
    actual = {
        "scenario": "BULLISH",
        "allowed": False,
        "bos_required": True,
        "reasons": ["rr_below_min:1.2<1.7", "high_impact_event_blackout"],
    }
    expected = {
        "scenario": "BULLISH",
        "allowed": False,
        "bos_required": True,
        "required_reasons": ["rr_below_min", "event_blackout"],
        "forbidden_reasons": ["context_blocks"],
    }
    assert compare_expectation("case", expected, actual) == ()


def test_mismatch_is_reported() -> None:
    actual = {"scenario": "RANGE", "allowed": False, "reasons": []}
    expected = {"scenario": "BULLISH", "allowed": True}
    mismatches = compare_expectation("case", expected, actual)
    assert len(mismatches) == 2
    assert {item.field for item in mismatches} == {"scenario", "allowed"}


def test_labels_forbid_pnl_and_require_unique_cases() -> None:
    valid = {
        "study_id": "TEST",
        "pnl_labels_forbidden": True,
        "cases": [
            {
                "id": "a",
                "symbol": "BTCUSDT",
                "timestamp": "2026-01-01T00:00:00",
                "side": "long",
                "expected": {"scenario": "BULLISH"},
            }
        ],
    }
    study_id, cases = validate_label_payload(valid)
    assert study_id == "TEST"
    assert cases[0]["symbol"] == "BTCUSDT"

    invalid = dict(valid)
    invalid["pnl_labels_forbidden"] = False
    try:
        validate_label_payload(invalid)
    except ValueError as exc:
        assert "forbid PnL" in str(exc)
    else:
        raise AssertionError("PnL-enabled labels must be rejected")


def test_unknown_expectation_field_is_rejected() -> None:
    mismatches = compare_expectation("case", {"future_profit": 10}, {"reasons": []})
    assert mismatches
    assert mismatches[0].field == "future_profit"


def main() -> int:
    test_compare_exact_and_reason_tokens()
    test_mismatch_is_reported()
    test_labels_forbid_pnl_and_require_unique_cases()
    test_unknown_expectation_field_is_rejected()
    print("SMOKE MTF V2 labelled replay smoke tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
