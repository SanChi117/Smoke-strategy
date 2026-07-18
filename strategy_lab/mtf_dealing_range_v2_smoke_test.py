#!/usr/bin/env python3
"""Regression tests for the SMOKE MTF V2 recognition core."""
from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.event_risk import (
    EventRiskPolicy,
    ScheduledEvent,
    evaluate_event_risk,
)
from strategy_lab.market_data import Candle
from strategy_lab.mtf_dealing_range_v2 import (
    ClosedBar,
    MtfDealingRangeEngine,
    confirmed_pivots,
    resample_complete_bars,
)


def candle(at: datetime, price: float, high: float | None = None, low: float | None = None) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        time=at,
        open=price,
        high=high if high is not None else price + 0.5,
        low=low if low is not None else price - 0.5,
        close=price + 0.1,
        volume=100.0,
    )


def test_incomplete_bucket_is_not_exposed() -> None:
    start = datetime(2026, 1, 1)
    rows = [candle(start + timedelta(minutes=5 * index), 100 + index) for index in range(7)]
    bars = resample_complete_bars(rows, "15m")
    assert len(bars) == 2, bars
    assert bars[-1].close_time == start + timedelta(minutes=30)


def test_pivot_requires_right_side_confirmation() -> None:
    start = datetime(2026, 1, 1)
    highs = [2.0, 3.0, 8.0, 4.0, 3.0]
    bars = [
        ClosedBar(
            symbol="BTCUSDT",
            timeframe="5m",
            open_time=start + timedelta(minutes=5 * index),
            close_time=start + timedelta(minutes=5 * (index + 1)),
            open=1.0,
            high=value,
            low=0.5,
            close=1.0,
            volume=1.0,
        )
        for index, value in enumerate(highs)
    ]
    pivots = [pivot for pivot in confirmed_pivots(bars, 2, 2) if pivot.kind == "high"]
    assert len(pivots) == 1
    assert pivots[0].price == 8.0
    assert pivots[0].confirmed_at == bars[-1].close_time
    assert not [
        pivot for pivot in confirmed_pivots(bars[:-1], 2, 2) if pivot.kind == "high"
    ], "Pivot leaked before the final right-side candle closed"


def synthetic_history(days: int) -> list[Candle]:
    start = datetime(2025, 1, 1)
    rows: list[Candle] = []
    price = 100.0
    for index in range(days * 24 * 12):
        # Deterministic waves create pivots without random or future-derived data.
        phase = index % 288
        day = index // 288
        drift = 0.015 if (day // 12) % 2 == 0 else -0.012
        wave = 0.08 if phase < 144 else -0.08
        open_price = price
        close_price = max(1.0, open_price + drift + wave)
        rows.append(
            Candle(
                symbol="BTCUSDT",
                time=start + timedelta(minutes=5 * index),
                open=open_price,
                high=max(open_price, close_price) + 0.12,
                low=min(open_price, close_price) - 0.12,
                close=close_price,
                volume=100.0 + float(phase % 20),
            )
        )
        price = close_price
    return rows


def test_future_candles_do_not_change_past_snapshot() -> None:
    history = synthetic_history(70)
    cutoff = datetime(2025, 3, 1)
    before = [row for row in history if row.time < cutoff]
    full_engine = MtfDealingRangeEngine(history)
    short_engine = MtfDealingRangeEngine(before)
    full_snapshot = full_engine.snapshot("BTCUSDT", cutoff)
    short_snapshot = short_engine.snapshot("BTCUSDT", cutoff)
    assert full_snapshot == short_snapshot, "Future candles changed a past context snapshot"


def test_event_risk_is_scoped_and_point_in_time() -> None:
    at = datetime(2026, 7, 18, 12, 0)
    policy = EventRiskPolicy()
    macro = ScheduledEvent(
        event_id="te:nfp",
        title="NFP",
        start=at + timedelta(minutes=20),
        end=at + timedelta(minutes=20),
        importance=3,
        scope="macro",
        provider="trading_economics",
        known_at=at - timedelta(days=1),
    )
    decision = evaluate_event_risk(at, "ETHUSDT", [macro], policy)
    assert decision.block_new_entry
    assert decision.risk_multiplier == 0.0

    future_known = ScheduledEvent(
        event_id="te:future-known",
        title="Not known yet",
        start=at,
        end=at,
        importance=3,
        scope="macro",
        provider="trading_economics",
        known_at=at + timedelta(minutes=1),
    )
    assert not evaluate_event_risk(at, "ETHUSDT", [future_known], policy).block_new_entry

    crypto = ScheduledEvent(
        event_id="cmc:eth",
        title="Ethereum upgrade",
        start=at,
        end=at,
        importance=3,
        scope="crypto",
        provider="coinmarketcal",
        symbols=("ETH",),
        known_at=at - timedelta(days=2),
    )
    assert evaluate_event_risk(at, "ETHUSDT", [crypto], policy).block_new_entry
    assert not evaluate_event_risk(at, "BTCUSDT", [crypto], policy).block_new_entry

    estimated = ScheduledEvent(
        event_id="cmc:estimated",
        title="Estimated release window",
        start=at,
        end=at,
        importance=3,
        scope="crypto",
        provider="coinmarketcal",
        symbols=("ETH",),
        estimated=True,
        known_at=at - timedelta(days=2),
    )
    estimated_decision = evaluate_event_risk(at, "ETHUSDT", [estimated], policy)
    assert not estimated_decision.block_new_entry
    assert 0.0 < estimated_decision.risk_multiplier < 1.0


def main() -> int:
    test_incomplete_bucket_is_not_exposed()
    test_pivot_requires_right_side_confirmation()
    test_future_candles_do_not_change_past_snapshot()
    test_event_risk_is_scoped_and_point_in_time()
    print("SMOKE MTF dealing range V2 smoke tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
