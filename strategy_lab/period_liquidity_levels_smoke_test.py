#!/usr/bin/env python3
"""Causal tests for PDH/PDL, PWH/PWL and PMH/PML."""
from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.mtf_dealing_range_v2 import ClosedBar
from strategy_lab.period_liquidity_levels import previous_period_liquidity_levels


def closed_bar(
    timeframe: str,
    start: datetime,
    end: datetime,
    high: float,
    low: float,
) -> ClosedBar:
    return ClosedBar(
        symbol="BTCUSDT",
        timeframe=timeframe,
        open_time=start,
        close_time=end,
        open=(high + low) / 2,
        high=high,
        low=low,
        close=(high + low) / 2,
        volume=100.0,
    )


def test_only_completed_period_is_visible() -> None:
    at = datetime(2026, 2, 2, 12)
    prior_day = closed_bar("1d", datetime(2026, 2, 1), datetime(2026, 2, 2), 110.0, 90.0)
    future_day = closed_bar("1d", datetime(2026, 2, 2), datetime(2026, 2, 3), 999.0, 1.0)
    levels = previous_period_liquidity_levels(
        {"1d": [prior_day, future_day], "1w": [], "1M": [], "5m": []},
        "BTCUSDT",
        at,
    )
    values = {level.source: level.low for level in levels}
    assert values == {"PDH": 110.0, "PDL": 90.0}


def test_week_and_month_strength_exceed_daily() -> None:
    at = datetime(2026, 2, 2)
    daily = closed_bar("1d", datetime(2026, 2, 1), at, 110.0, 90.0)
    weekly = closed_bar("1w", datetime(2026, 1, 26), at, 120.0, 80.0)
    monthly = closed_bar("1M", datetime(2026, 1, 1), datetime(2026, 2, 1), 130.0, 70.0)
    levels = previous_period_liquidity_levels(
        {"1d": [daily], "1w": [weekly], "1M": [monthly], "5m": []},
        "BTCUSDT",
        at,
    )
    strength = {level.source: level.strength for level in levels}
    assert strength["PMH"] > strength["PWH"] > strength["PDH"]
    assert strength["PML"] > strength["PWL"] > strength["PDL"]


def test_touch_decays_but_does_not_rewrite_history() -> None:
    start = datetime(2026, 2, 1)
    close = datetime(2026, 2, 2)
    daily = closed_bar("1d", start, close, 110.0, 90.0)
    touch = ClosedBar(
        symbol="BTCUSDT",
        timeframe="5m",
        open_time=close + timedelta(minutes=5),
        close_time=close + timedelta(minutes=10),
        open=109.0,
        high=111.0,
        low=108.0,
        close=109.5,
        volume=100.0,
    )
    before = previous_period_liquidity_levels(
        {"1d": [daily], "1w": [], "1M": [], "5m": [touch]},
        "BTCUSDT",
        close,
    )
    after = previous_period_liquidity_levels(
        {"1d": [daily], "1w": [], "1M": [], "5m": [touch]},
        "BTCUSDT",
        touch.close_time,
    )
    before_pdh = next(level for level in before if level.source == "PDH")
    after_pdh = next(level for level in after if level.source == "PDH")
    assert before_pdh.fresh and before_pdh.touches == 0
    assert not after_pdh.fresh and after_pdh.touches == 1
    assert after_pdh.strength < before_pdh.strength


def main() -> int:
    test_only_completed_period_is_visible()
    test_week_and_month_strength_exceed_daily()
    test_touch_decays_but_does_not_rewrite_history()
    print("SMOKE MTF prior-period liquidity tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
