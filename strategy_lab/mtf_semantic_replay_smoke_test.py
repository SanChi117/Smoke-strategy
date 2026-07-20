#!/usr/bin/env python3
"""Smoke tests for frozen causal semantic replay packets."""
from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

from strategy_lab.mtf_dealing_range_v2 import MtfDealingRangeEngine
from strategy_lab.mtf_dealing_range_v2_smoke_test import synthetic_history
from strategy_lab.mtf_entry_model_v2 import MtfEntryModelV2
from strategy_lab.mtf_recognition_export_v2 import assert_no_outcome_fields, plan_payload

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_smoke_mtf_v2_semantic_replay.py"
SPEC = importlib.util.spec_from_file_location("smoke_semantic_replay", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
REPLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPLAY)


def test_exact_replay_and_closed_windows() -> None:
    history = synthetic_history(45)
    engine = MtfDealingRangeEngine(history)
    model = MtfEntryModelV2(engine)
    timestamp = datetime(2025, 2, 5, 12, 0)
    frozen = plan_payload(model.evaluate("BTCUSDT", timestamp, "long"))
    packet = REPLAY.build_packet(engine, model, frozen, 1, 1)
    assert packet["frozen_payload_exact_match"] is True
    assert packet["timestamp"] == timestamp.isoformat()
    for rows in packet["closed_candle_windows"].values():
        assert all(datetime.fromisoformat(row["close_time"]) <= timestamp for row in rows)
    assert_no_outcome_fields(packet)


def test_changed_frozen_payload_is_rejected() -> None:
    history = synthetic_history(45)
    engine = MtfDealingRangeEngine(history)
    model = MtfEntryModelV2(engine)
    timestamp = datetime(2025, 2, 5, 12, 0)
    frozen = plan_payload(model.evaluate("BTCUSDT", timestamp, "short"))
    frozen["setup_state"] = "ENTRY_READY" if frozen["setup_state"] != "ENTRY_READY" else "NO_CONTEXT"
    try:
        REPLAY.build_packet(engine, model, frozen, 1, 1)
    except RuntimeError as exc:
        assert "Frozen replay mismatch" in str(exc)
    else:
        raise AssertionError("changed frozen payload must fail exact replay")


def test_fingerprint_ignores_timestamp_but_not_structure() -> None:
    row = {
        "timestamp": "2025-02-01T00:00:00",
        "symbol": "BTCUSDT",
        "side": "long",
        "setup_state": "WAIT_5M_BOS",
        "scenario": "BULLISH",
        "monthly_state": "BULLISH",
        "weekly_state": "BULLISH",
        "daily_state": "BULLISH",
        "h4_state": "BULLISH",
        "h1_state": "BULLISH",
        "poi": {"timeframe": "4h", "kind": "pivot", "side": "support", "low": 99, "high": 100, "confirmed_at": "2025-01-01T00:00:00", "source": "test"},
        "h1_raid": True,
        "h1_vc": False,
        "vc_zone_test": False,
        "m5_bos": False,
        "entry_ready": False,
        "target_timeframe": None,
        "target_source": None,
    }
    later = dict(row, timestamp="2025-02-01T00:15:00")
    changed = dict(row, h1_raid=False)
    assert REPLAY.case_fingerprint(row) == REPLAY.case_fingerprint(later)
    assert REPLAY.case_fingerprint(row) != REPLAY.case_fingerprint(changed)


def main() -> int:
    test_exact_replay_and_closed_windows()
    test_changed_frozen_payload_is_rejected()
    test_fingerprint_ignores_timestamp_but_not_structure()
    print("SMOKE MTF V2 semantic replay tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
