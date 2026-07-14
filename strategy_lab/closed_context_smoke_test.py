#!/usr/bin/env python3
"""Regression test for excluding forming or incomplete 4h/1d context candles."""

from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.closed_context import resample_closed_candles
from strategy_lab.market_data import Candle


def candle_at(start: datetime, index: int) -> Candle:
    return Candle(
        "BTCUSDT",
        start + timedelta(minutes=15 * index),
        100,
        101,
        99,
        100 + index / 100,
        10,
    )


def main() -> None:
    start = datetime(2026, 7, 14, 0, 0)
    rows = [candle_at(start, idx) for idx in range(18)]

    # 16 bars complete 00:00-04:00. Two bars of 04:00-08:00 are forming.
    h4 = resample_closed_candles(rows, 4)
    assert len(h4) == 1, h4
    assert h4[0].time == start + timedelta(hours=3, minutes=45)

    # The final source bar exists, but one internal 15m bar is missing. The 4h
    # context must remain unavailable instead of silently aggregating a gap.
    gapped_h4 = [candle_at(start, idx) for idx in range(16) if idx != 7]
    assert resample_closed_candles(gapped_h4, 4) == [], "gapped 4h context was accepted"

    day_rows = [candle_at(start, idx) for idx in range(95)]
    assert resample_closed_candles(day_rows, 24) == [], "forming daily context leaked"
    day_rows.append(candle_at(start, 95))
    assert len(resample_closed_candles(day_rows, 24)) == 1

    gapped_day = [candle_at(start, idx) for idx in range(96) if idx != 48]
    assert resample_closed_candles(gapped_day, 24) == [], "gapped daily context was accepted"
    print("CLOSED CONTEXT SMOKE TEST OK")


if __name__ == "__main__":
    main()
