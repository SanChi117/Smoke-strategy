#!/usr/bin/env python3
"""Regression tests for JSON-safe no-PnL V3 exports."""
from __future__ import annotations

from datetime import datetime
import json

from strategy_lab.mtf_fta_first_no_pnl_v3 import assert_outcome_blind, json_safe


def main() -> int:
    payload = {
        "evaluated_at": datetime(2026, 1, 1, 12, 30),
        "entry_time": datetime(2026, 1, 1, 12, 45),
        "nested": {"confirmed_at": datetime(2026, 1, 1, 11, 0)},
    }
    safe = json_safe(payload)
    assert safe["entry_time"] == "2026-01-01T12:45:00"
    json.dumps(safe)
    assert_outcome_blind(safe)

    try:
        assert_outcome_blind({"net_return": 0.1})
    except AssertionError:
        pass
    else:
        raise AssertionError("forbidden outcome field was not rejected")

    print("SMOKE MTF FTA-first V3 no-PnL export tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
