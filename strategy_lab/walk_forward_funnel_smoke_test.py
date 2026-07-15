#!/usr/bin/env python3
"""Regression test for strict-OOS rejection funnel reporting."""

from __future__ import annotations

from strategy_lab.walk_forward_evaluation import build_layer_funnel, trade_key


def main() -> None:
    decisions = [
        {"symbol": "AAAUSDT", "side": "short", "entry_time": "2026-07-01T00:00:00", "setup_type": "pullback_resumption", "reason": "allowed_full_balanced", "allowed": "true"},
        {"symbol": "BBBUSDT", "side": "short", "entry_time": "2026-07-01T00:15:00", "setup_type": "pullback_resumption", "reason": "structure_skip", "allowed": "false"},
        {"symbol": "CCCUSDT", "side": "short", "entry_time": "2026-07-01T00:30:00", "setup_type": "pullback", "reason": "quality_skip", "allowed": "false"},
    ]
    generated = {
        trade_key(row["symbol"], row["side"], row["entry_time"]): {"setup_type": row["setup_type"]}
        for row in decisions
    }
    rows, summary = build_layer_funnel(decisions, generated)
    assert summary["validation_candidates"] == 3
    assert summary["validation_allowed"] == 1
    assert summary["setup_counts"] == {"pullback": 1, "pullback_resumption": 2}
    assert summary["allowed_by_setup"] == {"pullback_resumption": 1}
    assert summary["blocking_reasons"]["structure_skip"] == 1
    assert any(row["setup_type"] == "pullback_resumption" and row["reason"] == "structure_skip" for row in rows)
    print("walk_forward_funnel_smoke_test: PASS")


if __name__ == "__main__":
    main()
