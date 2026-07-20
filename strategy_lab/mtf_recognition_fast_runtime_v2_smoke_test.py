#!/usr/bin/env python3
"""Equivalence tests for the execution-only SMOKE MTF V2 caches."""
from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.mtf_dealing_range_v2 import MtfDealingRangeEngine
from strategy_lab.mtf_dealing_range_v2_smoke_test import synthetic_history
from strategy_lab.mtf_entry_model_v2 import MtfEntryModelV2
from strategy_lab.mtf_recognition_export_v2 import plan_payload
from strategy_lab.mtf_recognition_fast_runtime_v2 import install_fast_runtime


def test_cached_runtime_is_output_equivalent() -> None:
    history = synthetic_history(45)
    checkpoints = [
        datetime(2025, 2, 5) + timedelta(hours=offset)
        for offset in (0, 6, 12, 18, 30, 42)
    ]

    baseline_engine = MtfDealingRangeEngine(history)
    baseline_model = MtfEntryModelV2(baseline_engine)
    baseline = [
        plan_payload(baseline_model.evaluate("BTCUSDT", timestamp, side))
        for timestamp in checkpoints
        for side in ("long", "short")
    ]

    cached_engine = MtfDealingRangeEngine(history)
    runtime = install_fast_runtime(cached_engine)
    cached_model = MtfEntryModelV2(cached_engine)
    cached = [
        plan_payload(cached_model.evaluate("BTCUSDT", timestamp, side))
        for timestamp in checkpoints
        for side in ("long", "short")
    ]

    assert cached == baseline, "Execution caches changed a recognition decision"
    stats = runtime.stats()
    assert stats["hits"].get("snapshot", 0) >= len(checkpoints)
    assert stats["hits"].get("bars_asof", 0) > 0
    assert stats["hits"].get("pivot_prefix_filter", 0) > 0
    assert stats["hits"].get("imbalance_prefix_filter", 0) > 0
    assert stats["hits"].get("liquidity_map", 0) >= len(checkpoints)


def main() -> int:
    test_cached_runtime_is_output_equivalent()
    print("SMOKE MTF V2 fast runtime equivalence tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
