#!/usr/bin/env python3
"""Regression test for excluding forming 4h/1d context candles."""

from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.closed_context import resample_closed_candles
from strategy_lab.market_data import Candle


def main() -> None:
    start = datetime(2026, 7, 14, 0, 0)
    rows = [
        Candle("BTCUSDT", start + timedelta(minutes=15 * idx), 100, 101, 99, 100 + idx / 100, 10)
        for idx in range(18)
    ]
    # 16 bars complete 00:00-04:00. Two bars of 04:00-08:00 are forming.
    h4 = resample_closed_candles(rows, 4)
    assert len(h4) == 1, h4
    assert h4[0].time == start + timedelta(hours=3, minutes=45)

    day_rows = [
        Candle("BTCUSDT", start + timedelta(minutes=15 * idx), 100, 101, 99, 100, 10)
        for idx in range(95)
    ]
    assert resample_closed_candles(day_rows, 24) == [], "forming daily context leaked"
    day_rows.append(Candle("BTCUSDT", start + timedelta(hours=23, minutes=45), 100, 101, 99, 100, 10))
    assert len(resample_closed_candles(day_rows, 24)) == 1
    print("CLOSED CONTEXT SMOKE TEST OK")


if __name__ == "__main__":
    main()
