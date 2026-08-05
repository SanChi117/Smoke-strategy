#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_smoke_mtf_v2_review_queue.py"
SPEC = importlib.util.spec_from_file_location("smoke_review_queue", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
QUEUE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUEUE)


def row(timestamp: str, symbol: str, side: str, state: str, rank: int) -> dict:
    return {
        "timestamp": timestamp,
        "symbol": symbol,
        "side": side,
        "setup_state": state,
        "stage_rank": rank,
        "entry_ready": state == "ENTRY_READY",
        "scenario": "BULLISH" if side == "long" else "BEARISH",
        "daily_state": "BULLISH",
        "h4_state": "BULLISH",
        "poi": {
            "timeframe": "4h",
            "kind": "imbalance",
            "side": "support" if side == "long" else "resistance",
            "low": 99.0,
            "high": 100.0,
            "confirmed_at": "2025-01-31T20:00:00",
            "source": "test",
        },
        "h1_raid": False,
        "h1_vc": True,
        "vc_zone_test": rank >= 7,
        "m5_bos": rank >= 8,
        "quality_state": "QUALIFIED",
        "reasons": ["test_reason"],
    }


def test_queue_preserves_rows_and_balances_groups() -> None:
    rows = [
        row("2025-02-01T00:00:00", "BTCUSDT", "long", "POI_TESTED", 5),
        row("2025-02-01T00:15:00", "BTCUSDT", "long", "POI_TESTED", 5),
        row("2025-02-01T00:30:00", "ETHUSDT", "short", "WAIT_5M_BOS", 7),
        row("2025-02-01T00:45:00", "SOLUSDT", "long", "ENTRY_READY", 10),
    ]
    ordered = QUEUE.balanced_review_order(rows)
    assert len(ordered) == len(rows)
    assert ordered[0]["setup_state"] == "ENTRY_READY"
    assert {id(item) for item in ordered} == {id(item) for item in rows}
    assert ordered[-1]["timestamp"] == "2025-02-01T00:15:00"
    assert QUEUE.case_fingerprint(rows[0]) == QUEUE.case_fingerprint(rows[1])


def test_packets_are_reviewable_and_repetition_is_visible() -> None:
    payload = {
        "mode": "NO_PNL_NO_FUTURE_OUTCOME",
        "selection_rule": "first N chronologically per symbol, side and setup_state",
        "candidates": [
            row("2025-02-01T00:00:00", "BTCUSDT", "long", "POI_TESTED", 5),
            row("2025-02-01T00:15:00", "BTCUSDT", "long", "POI_TESTED", 5),
        ],
    }
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory)
        queue = QUEUE.build_queue(payload, out)
        assert queue["row_count"] == 2
        assert queue["unique_case_fingerprints"] == 1
        assert queue["repeated_snapshot_rows"] == 1
        assert queue["rows"][0]["cluster_size"] == 2
        assert queue["rows"][1]["cluster_occurrence"] == 2
        packet_path = out / queue["rows"][0]["packet_file"]
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        assert packet["mode"] == "NO_PNL_NO_FUTURE_OUTCOME"
        assert packet["human_review"]["verdict"] == "UNREVIEWED"
        assert packet["cluster_size"] == 2
        QUEUE.assert_no_outcome_fields(packet)
        QUEUE.assert_no_outcome_fields(queue)


def main() -> int:
    test_queue_preserves_rows_and_balances_groups()
    test_packets_are_reviewable_and_repetition_is_visible()
    print("SMOKE MTF V2 review queue tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
