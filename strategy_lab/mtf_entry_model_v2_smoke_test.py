#!/usr/bin/env python3
"""Causal smoke tests for the SMOKE MTF V2 entry model."""
from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.mtf_dealing_range_v2 import ClosedBar, Level
from strategy_lab.mtf_entry_model_v2 import (
    EntryConfig,
    detect_5m_bos,
    detect_h1_reaction,
    find_next_15m_entry_bar,
)


BASE = datetime(2026, 1, 1)


def bar(
    index: int,
    open_price: float,
    close_price: float,
    high: float,
    low: float,
    *,
    timeframe: str = "5m",
    minutes: int = 5,
    symbol: str = "BTCUSDT",
) -> ClosedBar:
    start = BASE + timedelta(minutes=minutes * index)
    return ClosedBar(
        symbol=symbol,
        timeframe=timeframe,
        open_time=start,
        close_time=start + timedelta(minutes=minutes),
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


def test_execution_uses_next_15m_open_not_5m_open() -> None:
    rows = bullish_bos_rows()
    signal = detect_5m_bos(rows, "long", rows[-1].close_time, EntryConfig())
    assert signal is not None
    execution_time = datetime(2026, 1, 1, 2, 15)
    m15 = ClosedBar(
        symbol="BTCUSDT",
        timeframe="15m",
        open_time=execution_time,
        close_time=execution_time + timedelta(minutes=15),
        open=111.0,
        high=999.0,
        low=1.0,
        close=500.0,
        volume=9999.0,
    )
    selected = find_next_15m_entry_bar([m15], "BTCUSDT", execution_time, signal)
    assert selected is not None
    assert selected.timeframe == "15m"
    assert selected.open == 111.0


def test_execution_rejects_non_15m_boundary() -> None:
    rows = bullish_bos_rows()
    signal = detect_5m_bos(rows, "long", rows[-1].close_time, EntryConfig())
    assert signal is not None
    timestamp = datetime(2026, 1, 1, 2, 10)
    candidate = ClosedBar(
        symbol="BTCUSDT",
        timeframe="15m",
        open_time=timestamp,
        close_time=timestamp + timedelta(minutes=15),
        open=111.0,
        high=112.0,
        low=110.0,
        close=111.5,
        volume=100.0,
    )
    assert find_next_15m_entry_bar([candidate], "BTCUSDT", timestamp, signal) is None


def test_h1_reaction_requires_closed_touch_and_rejection() -> None:
    poi = Level(
        symbol="BTCUSDT",
        timeframe="4h",
        kind="imbalance",
        side="support",
        low=99.0,
        high=100.0,
        formed_at=BASE,
        confirmed_at=BASE,
        strength=75.0,
        source="reference",
    )
    closed = ClosedBar(
        symbol="BTCUSDT",
        timeframe="1h",
        open_time=BASE,
        close_time=BASE + timedelta(hours=1),
        open=99.4,
        high=101.2,
        low=98.8,
        close=100.9,
        volume=100.0,
    )
    future = ClosedBar(
        symbol="BTCUSDT",
        timeframe="1h",
        open_time=BASE + timedelta(hours=1),
        close_time=BASE + timedelta(hours=2),
        open=100.9,
        high=105.0,
        low=90.0,
        close=91.0,
        volume=100.0,
    )
    asof = BASE + timedelta(hours=1)
    assert detect_h1_reaction([closed, future], poi, "long", asof)
    assert not detect_h1_reaction([future], poi, "long", asof)


def main() -> int:
    test_confirmed_close_bos()
    test_wick_without_close_is_not_bos()
    test_unconfirmed_pivot_cannot_trigger()
    test_execution_uses_next_15m_open_not_5m_open()
    test_execution_rejects_non_15m_boundary()
    test_h1_reaction_requires_closed_touch_and_rejection()
    print("SMOKE MTF entry model V2 smoke tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
