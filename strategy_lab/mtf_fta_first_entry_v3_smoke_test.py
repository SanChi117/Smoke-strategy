#!/usr/bin/env python3
"""Regression tests for the preregistered SMOKE MTF FTA-first V3 core."""
from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.mtf_dealing_range_v2 import ClosedBar, Level, Pivot
from strategy_lab.mtf_entry_model_v2 import BosSignal
from strategy_lab.mtf_fta_first_entry_v3 import (
    FtaFirstConfig,
    _structural_rr,
    directional_external_levels,
    find_closed_m15_pullback_v3,
    select_post_bos_stop_v3,
)


BASE = datetime(2026, 1, 1, 0, 0)
SYMBOL = "BTCUSDT"


def bar(timeframe: str, minutes: int, duration: int, o: float, h: float, l: float, c: float) -> ClosedBar:
    opened = BASE + timedelta(minutes=minutes)
    return ClosedBar(
        symbol=SYMBOL,
        timeframe=timeframe,
        open_time=opened,
        close_time=opened + timedelta(minutes=duration),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=100.0,
    )


def level(side: str, low: float, high: float, timeframe: str, fresh: bool, strength: float) -> Level:
    return Level(
        symbol=SYMBOL,
        timeframe=timeframe,
        kind="pivot",
        side=side,
        low=low,
        high=high,
        formed_at=BASE - timedelta(days=2),
        confirmed_at=BASE - timedelta(days=1),
        strength=strength,
        source=f"test_{timeframe}_{side}_{low}",
        fresh=fresh,
        touches=0,
    )


def make_bos() -> BosSignal:
    pivot = Pivot(
        symbol=SYMBOL,
        timeframe="5m",
        kind="high",
        bar_open_time=BASE - timedelta(minutes=15),
        bar_close_time=BASE - timedelta(minutes=10),
        confirmed_at=BASE - timedelta(minutes=5),
        price=100.0,
        left_bars=2,
        right_bars=2,
        prominence_pct=0.01,
        displacement_pct=0.01,
        strength=70.0,
    )
    signal = bar("5m", 0, 5, 99.0, 103.0, 98.5, 102.5)
    return BosSignal(
        symbol=SYMBOL,
        side="long",
        pivot=pivot,
        signal_bar=signal,
        displacement=True,
        imbalance=False,
        strength=75.0,
    )


def test_external_fta_is_directional_fresh_and_external() -> None:
    rows = [
        level("resistance", 101.0, 101.5, "1h", True, 99.0),
        level("resistance", 110.0, 111.0, "4h", False, 99.0),
        level("resistance", 108.0, 109.0, "4h", True, 60.0),
        level("resistance", 106.0, 107.0, "1d", True, 70.0),
        level("support", 90.0, 91.0, "4h", True, 80.0),
    ]
    candidates = directional_external_levels(
        rows,
        side="long",
        reference_price=100.0,
        timeframes=("4h", "1d", "1w", "1M"),
    )
    assert [item.price for item in candidates] == [108.0, 106.0]
    assert all(item.timeframe != "1h" for item in candidates)
    assert all(item.price > 100.0 for item in candidates)


def test_pullback_must_be_closed_after_bos_and_directional() -> None:
    bos = make_bos()
    rows = [
        bar("15m", -15, 15, 101.0, 102.0, 99.5, 100.5),  # closes before BOS
        bar("15m", 5, 15, 102.0, 103.0, 99.5, 99.8),     # touches but bearish
        bar("15m", 20, 15, 100.5, 102.0, 99.2, 101.5),   # qualifying closed pullback
    ]
    signal = find_closed_m15_pullback_v3(
        rows,
        symbol=SYMBOL,
        side="long",
        timestamp=BASE + timedelta(minutes=35),
        bos=bos,
        h1_atr=10.0,
        config=FtaFirstConfig(),
    )
    assert signal is not None
    assert signal.bar.open_time == BASE + timedelta(minutes=20)
    assert signal.bar.close_time == BASE + timedelta(minutes=35)
    assert signal.reference_price == 100.0
    assert signal.tolerance == 1.0


def test_post_bos_swing_has_priority_over_pullback_wick() -> None:
    bos = make_bos()
    five_minute = [
        bos.signal_bar,
        bar("5m", 5, 5, 102.0, 103.0, 99.0, 101.0),
        bar("5m", 10, 5, 101.0, 102.0, 98.0, 100.0),
        bar("5m", 15, 5, 100.0, 101.0, 95.0, 99.0),
        bar("5m", 20, 5, 99.0, 102.0, 98.0, 101.0),
        bar("5m", 25, 5, 101.0, 103.0, 99.0, 102.0),
    ]
    pullback_bar = bar("15m", 15, 15, 101.0, 103.0, 96.0, 102.0)

    class FakeEngine:
        bars = {"5m": five_minute, "15m": [pullback_bar]}

    from strategy_lab.mtf_fta_first_entry_v3 import PullbackSignalV3

    pullback = PullbackSignalV3(pullback_bar, 100.0, 1.0)
    stop = select_post_bos_stop_v3(
        FakeEngine(),
        symbol=SYMBOL,
        side="long",
        entry=102.0,
        bos=bos,
        pullback=pullback,
        h1_atr=10.0,
        config=FtaFirstConfig(),
    )
    assert stop is not None
    assert stop.source == "post_bos_protected_swing"
    assert stop.timeframe == "5m"
    assert stop.anchor_price == 95.0
    assert stop.price == 94.0
    assert stop.price < pullback_bar.low


def test_structural_rr_does_not_move_target() -> None:
    assert _structural_rr("long", 100.0, 98.0, 104.0) == 2.0
    assert _structural_rr("short", 100.0, 102.0, 96.0) == 2.0
    assert _structural_rr("long", 100.0, 101.0, 110.0) is None
    assert _structural_rr("short", 100.0, 99.0, 90.0) is None


def main() -> int:
    test_external_fta_is_directional_fresh_and_external()
    test_pullback_must_be_closed_after_bos_and_directional()
    test_post_bos_swing_has_priority_over_pullback_wick()
    test_structural_rr_does_not_move_target()
    print("SMOKE MTF FTA-first V3 smoke tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
