#!/usr/bin/env python3
"""Smoke tests for the no-PnL SMOKE MTF V2 review queue builder."""
from __future__ import annotations

import importlib.util
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
        "poi": {"timeframe": "4h", "kind": "imbalance", "source": "test"},
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


def test_packets_are_no_pnl_and_reviewable() -> None:
    payload = {
        "mode": "NO_PNL_NO_FUTURE_OUTCOME",
        "selection_rule": "first N chronologically per symbol, side and setup_state",
        "candidates": [row("2025-02-01T00:00:00", "BTCUSDT", "long", "POI_TESTED", 5)],
    }
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory)
        queue = QUEUE.build_queue(payload, out)
        assert queue["row_count"] == 1
        assert (out / "recognition_review_queue.csv").exists()
        packet_path = out / queue["rows"][0]["packet_file"]
        text = packet_path.read_text(encoding="utf-8").lower()
        assert "unreviewed" in text
        for token in ("pnl", "future_return", "tp_hit", "sl_hit", "mfe", "mae"):
            assert token not in text


def main() -> int:
    test_queue_preserves_rows_and_balances_groups()
    test_packets_are_no_pnl_and_reviewable()
    print("SMOKE MTF V2 review queue tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
