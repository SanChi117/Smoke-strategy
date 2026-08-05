#!/usr/bin/env python3
"""Regression checks for causal Cleanshot/SMC feature evaluation."""
from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.causal_smc_features import SmcFeatureEngine, feature_as_dict, policy_decision
from strategy_lab.market_data import Candle


def build_rows(count: int = 520) -> list[Candle]:
    start = datetime(2025, 1, 1)
    rows: list[Candle] = []
    price = 100.0
    for index in range(count):
        drift = 0.035
        open_price = price
        close_price = price + drift
        high = close_price + 0.08
        low = open_price - 0.06
        rows.append(
            Candle(
                symbol="TESTUSDT",
                time=start + timedelta(minutes=15 * index),
                open=open_price,
                high=high,
                low=low,
                close=close_price,
                volume=1000.0 + index,
            )
        )
        price = close_price
    return rows


def main() -> int:
    rows = build_rows()
    entry_time = rows[480].time
    before = SmcFeatureEngine(rows).evaluate("TESTUSDT", entry_time, "long")
    assert before.available, "expected sufficient completed history"
    assert before.h4_bias == "bull", before
    allowed, multiplier = policy_decision("SMC_DIRECTION_CONTROL", before)
    assert allowed and multiplier == 1.0

    # A violent candle that occurs after the entry must not alter the feature state.
    future_time = rows[-1].time + timedelta(minutes=15)
    future = Candle(
        symbol="TESTUSDT",
        time=future_time,
        open=rows[-1].close,
        high=rows[-1].close * 4.0,
        low=rows[-1].close * 0.10,
        close=rows[-1].close * 0.20,
        volume=10_000_000.0,
    )
    after = SmcFeatureEngine(rows + [future]).evaluate("TESTUSDT", entry_time, "long")
    assert feature_as_dict(before) == feature_as_dict(after), "future candle changed historical feature"

    short_feature = SmcFeatureEngine(rows).evaluate("TESTUSDT", entry_time, "short")
    short_allowed, _ = policy_decision("SMC_DIRECTION_CONTROL", short_feature)
    assert not short_allowed, "bearish side must not pass bullish 4h bias"

    missing = SmcFeatureEngine(rows).evaluate("UNKNOWN", entry_time, "long")
    assert not missing.available and missing.state == "missing"
    print("causal Cleanshot/SMC feature smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
