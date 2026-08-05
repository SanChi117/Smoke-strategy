#!/usr/bin/env python3
"""Smoke tests for deterministic sharded no-PnL recognition merging."""
from __future__ import annotations

from scripts.merge_smoke_mtf_v2_recognition_parts import merge_parts


def _part(start: str, rows: list[dict]) -> dict:
    return {
        "study_id": "SMOKE_MTF_V2_REAL_RECOGNITION_CANDIDATES",
        "mode": "NO_PNL_NO_FUTURE_OUTCOME",
        "scan_start": start,
        "scan_end": start,
        "evaluated_15m_bars": 10,
        "evaluated_side_snapshots": 20,
        "qualifying_snapshots": len(rows),
        "selected_snapshots": len(rows),
        "selection_rule": "first N chronologically per symbol, side and setup_state",
        "per_group": 2,
        "state_counts": {"WAIT_5M_BOS": 20},
        "reason_counts": {"no_confirmed_5m_bos": 20},
        "candidates": rows,
    }


def _row(timestamp: str, symbol: str = "BTCUSDT") -> dict:
    return {
        "timestamp": timestamp,
        "symbol": symbol,
        "side": "long",
        "setup_state": "WAIT_5M_BOS",
        "entry_ready": False,
        "scenario": "BULLISH",
        "scenario_strength": 60.0,
        "daily_state": "BULLISH",
        "h4_state": "BULLISH",
        "poi": None,
        "h1_raid": True,
        "h1_vc": False,
        "vc_zone_test": False,
        "m5_bos": False,
        "planned_entry": None,
        "planned_stop": None,
        "planned_target": None,
        "target_timeframe": None,
        "target_source": None,
        "planned_rr": None,
        "quality_score": 50.0,
        "quality_state": "WATCH",
        "reasons": ["no_confirmed_5m_bos"],
    }


def test_global_first_n_is_restored_after_day_sharding() -> None:
    day_two = _part("2025-02-02T00:00:00", [_row("2025-02-02T00:15:00"), _row("2025-02-02T00:30:00")])
    day_one = _part("2025-02-01T00:00:00", [_row("2025-02-01T00:15:00"), _row("2025-02-01T00:30:00")])
    result = merge_parts(
        [day_two, day_one],
        "2025-02-01T00:00:00",
        "2025-02-03T00:00:00",
        per_group=2,
        expected_parts=2,
    )
    assert [row["timestamp"] for row in result["candidates"]] == [
        "2025-02-01T00:15:00",
        "2025-02-01T00:30:00",
    ]
    assert result["evaluated_15m_bars"] == 20
    assert result["evaluated_side_snapshots"] == 40
    assert result["qualifying_snapshots"] == 4
    assert result["state_counts"] == {"WAIT_5M_BOS": 40}


def test_expected_shard_count_is_enforced() -> None:
    try:
        merge_parts([], "a", "b", 2, expected_parts=1)
    except RuntimeError as exc:
        assert "expected 1 parts" in str(exc)
    else:
        raise AssertionError("missing shard count must fail")


def main() -> int:
    test_global_first_n_is_restored_after_day_sharding()
    test_expected_shard_count_is_enforced()
    print("SMOKE MTF V2 recognition partition merge smoke tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
