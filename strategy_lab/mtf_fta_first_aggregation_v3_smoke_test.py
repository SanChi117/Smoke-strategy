#!/usr/bin/env python3
"""Regression tests for FTA-first V3 outcome-blind aggregation."""
from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location(
    "aggregate_smoke_mtf_fta_first_v3_recognition",
    ROOT / "scripts" / "aggregate_smoke_mtf_fta_first_v3_recognition.py",
)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def part(symbol: str, side: str, fold: int, record: dict | None) -> dict:
    records = [] if record is None else [record]
    return {
        "symbol": symbol,
        "side": side,
        "fold": fold,
        "evaluated_15m_snapshots": 10,
        "allowed_snapshots": len(records),
        "state_counts": {"ENTRY_READY": len(records), "WAIT_5M_BOS": 9},
        "reason_counts": {"no_confirmed_5m_bos_after_route": 9},
        "route_counts": {"fresh_h1_raid": 1},
        "target_timeframe_counts": {"4h": 10},
        "stop_source_counts": {"5m:post_bos_protected_swing": len(records)},
        "independent_entry_ready": records,
    }


def main() -> int:
    record = {
        "independent_fingerprint": "abc123",
        "fold": 0,
        "partition_key": "0:BTCUSDT:long",
        "symbol": "BTCUSDT",
        "side": "long",
        "evaluated_at": "2025-01-10T12:00:00",
        "entry_time": "2025-01-10T12:00:00",
        "entry": 100.0,
        "stop": 99.0,
        "target": 102.0,
        "rr": 2.0,
        "quality_score": 70.0,
    }
    payload = MODULE.aggregate([
        part("BTCUSDT", "long", 0, record),
        part("BTCUSDT", "short", 0, record.copy()),
    ])
    assert payload["evaluated_15m_snapshots"] == 20
    assert payload["allowed_snapshots_before_global_dedup"] == 2
    assert payload["independent_entry_ready_count"] == 1
    assert payload["duplicate_allowed_snapshots"] == 1
    assert payload["recognition_gate_passed"] is False
    assert payload["decision"] == "CLOSE_V3_WITHOUT_PROFITABILITY_TEST"

    try:
        MODULE.assert_outcome_blind({"profit_factor": 1.5})
    except AssertionError:
        pass
    else:
        raise AssertionError("aggregator accepted a forbidden outcome field")

    print("SMOKE MTF FTA-first V3 aggregation tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
