#!/usr/bin/env python3
"""Smoke tests for fresh-fractal H1 raid recognition."""
from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.mtf_dealing_range_v2 import ClosedBar
from strategy_lab.mtf_raid_signal_v2 import detect_h1_raid_signal


BASE = datetime(2026, 1, 1)


def bar(index: int, high: float, low: float, close: float, open_price: float | None = None) -> ClosedBar:
    start = BASE + timedelta(hours=index)
    return ClosedBar(
        symbol="BTCUSDT",
        timeframe="1h",
        open_time=start,
        close_time=start + timedelta(hours=1),
        open=close if open_price is None else open_price,
        high=high,
        low=low,
        close=close,
        volume=100.0,
    )


def bullish_raid_rows() -> list[ClosedBar]:
    return [
        bar(0, 104, 101, 103),
        bar(1, 103, 100, 101),
        bar(2, 102, 98, 100),
        bar(3, 103, 99, 102),
        bar(4, 104, 100, 103),
        bar(5, 105, 101, 104),
        bar(6, 104, 97, 101, 103),
    ]


def test_fresh_ssl_raid_is_detected() -> None:
    rows = bullish_raid_rows()
    signal = detect_h1_raid_signal(rows, "long", rows[-1].close_time)
    assert signal is not None
    assert signal.pivot.kind == "low"
    assert signal.pivot.price == 98
    assert signal.raid_bar.low == 97
    assert signal.raid_bar.close > signal.pivot.price
    assert signal.fresh


def test_prior_touch_makes_fractal_stale() -> None:
    rows = bullish_raid_rows()
    rows.insert(6, bar(6, 103, 98, 101))
    last = rows[-1]
    rows[-1] = ClosedBar(
        symbol=last.symbol,
        timeframe=last.timeframe,
        open_time=BASE + timedelta(hours=7),
        close_time=BASE + timedelta(hours=8),
        open=103,
        high=104,
        low=97,
        close=101,
        volume=100,
    )
    assert detect_h1_raid_signal(rows, "long", rows[-1].close_time) is None


def test_wick_without_reclaim_is_not_raid() -> None:
    rows = bullish_raid_rows()
    last = rows[-1]
    rows[-1] = ClosedBar(
        symbol=last.symbol,
        timeframe=last.timeframe,
        open_time=last.open_time,
        close_time=last.close_time,
        open=103,
        high=104,
        low=97,
        close=97.5,
        volume=100,
    )
    assert detect_h1_raid_signal(rows, "long", rows[-1].close_time) is None


def test_future_bar_does_not_change_past_raid() -> None:
    rows = bullish_raid_rows()
    at = rows[-1].close_time
    before = detect_h1_raid_signal(rows, "long", at)
    future = bar(100, 999, 1, 500)
    after = detect_h1_raid_signal(rows + [future], "long", at)
    assert before == after


def main() -> int:
    test_fresh_ssl_raid_is_detected()
    test_prior_touch_makes_fractal_stale()
    test_wick_without_reclaim_is_not_raid()
    test_future_bar_does_not_change_past_raid()
    print("SMOKE MTF V2 H1 raid tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
