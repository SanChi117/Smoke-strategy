#!/usr/bin/env python3
"""Causal smoke tests for the SMOKE MTF V2 entry model."""
from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.mtf_dealing_range_v2 import ClosedBar
from strategy_lab.mtf_entry_model_v2 import EntryConfig, detect_5m_bos


def bar(
    index: int,
    open_price: float,
    close_price: float,
    high: float,
    low: float,
) -> ClosedBar:
    start = datetime(2026, 1, 1) + timedelta(minutes=5 * index)
    return ClosedBar(
        symbol="BTCUSDT",
        timeframe="5m",
        open_time=start,
        close_time=start + timedelta(minutes=5),
        open=open_price,
        high=high,
        low=low,
        close=close_price,
        volume=100.0,
    )


def bullish_bos_rows() -> list[ClosedBar]:
    rows: list[ClosedBar] = []
    for index in range(20):
        base = 100.0 + (index % 3) * 0.1
        rows.append(bar(index, base, base + 0.05, base + 0.4, base - 0.4))
    # Confirmed structural high. Two right-side bars close before the signal.
    rows.append(bar(20, 103.0, 104.0, 105.0, 102.5))
    rows.append(bar(21, 102.5, 102.8, 103.5, 102.0))
    rows.append(bar(22, 102.8, 103.0, 103.4, 102.2))
    rows.append(bar(23, 103.0, 104.5, 104.8, 102.9))
    rows.append(bar(24, 104.5, 106.5, 106.8, 104.4))
    return rows


def test_confirmed_close_bos() -> None:
    rows = bullish_bos_rows()
    signal = detect_5m_bos(rows, "long", rows[-1].close_time, EntryConfig())
    assert signal is not None
    assert signal.pivot.price == 105.0
    assert signal.pivot.confirmed_at <= signal.signal_bar.open_time
    assert signal.signal_bar.close > signal.pivot.price
    assert signal.displacement or signal.imbalance


def test_wick_without_close_is_not_bos() -> None:
    rows = bullish_bos_rows()
    last = rows[-1]
    rows[-1] = ClosedBar(
        symbol=last.symbol,
        timeframe=last.timeframe,
        open_time=last.open_time,
        close_time=last.close_time,
        open=104.5,
        high=106.8,
        low=104.0,
        close=104.8,
        volume=100.0,
    )
    assert detect_5m_bos(rows, "long", rows[-1].close_time, EntryConfig()) is None


def test_unconfirmed_pivot_cannot_trigger() -> None:
    rows = bullish_bos_rows()
    # Move the supposed high next to the signal so it has no two closed right bars.
    rows[20] = bar(20, 101.0, 101.2, 101.5, 100.5)
    rows[22] = bar(22, 103.0, 104.0, 105.0, 102.5)
    rows[23] = bar(23, 103.0, 104.5, 104.8, 102.9)
    assert detect_5m_bos(rows, "long", rows[-1].close_time, EntryConfig()) is None


def main() -> int:
    test_confirmed_close_bos()
    test_wick_without_close_is_not_bos()
    test_unconfirmed_pivot_cannot_trigger()
    print("SMOKE MTF entry model V2 smoke tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
