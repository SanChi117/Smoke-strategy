#!/usr/bin/env python3
"""Smoke tests for the closed 15m H1 VC-zone retest."""
from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.mtf_dealing_range_v2 import ClosedBar, Level
from strategy_lab.mtf_vc_zone_test_v2 import detect_15m_vc_zone_test
from strategy_lab.mtf_volume_confirmation_v2 import VolumeConfirmationSignal


BASE = datetime(2026, 1, 1)


def h1_bar() -> ClosedBar:
    return ClosedBar(
        symbol="BTCUSDT",
        timeframe="1h",
        open_time=BASE,
        close_time=BASE + timedelta(hours=1),
        open=99.0,
        high=102.0,
        low=98.5,
        close=101.8,
        volume=200.0,
    )


def vc_signal() -> VolumeConfirmationSignal:
    poi = Level(
        symbol="BTCUSDT",
        timeframe="4h",
        kind="imbalance",
        side="support",
        low=98.0,
        high=99.0,
        formed_at=BASE - timedelta(hours=8),
        confirmed_at=BASE - timedelta(hours=4),
        strength=75.0,
        source="test",
    )
    return VolumeConfirmationSignal(
        symbol="BTCUSDT",
        side="long",
        signal_bar=h1_bar(),
        poi=poi,
        displacement=True,
        imbalance=True,
        bos=False,
        broken_pivot=None,
        zone_low=100.0,
        zone_high=100.8,
        strength=80.0,
    )


def m15(index: int, open_price: float, high: float, low: float, close: float) -> ClosedBar:
    start = BASE + timedelta(hours=1, minutes=15 * index)
    return ClosedBar(
        symbol="BTCUSDT",
        timeframe="15m",
        open_time=start,
        close_time=start + timedelta(minutes=15),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=100.0,
    )


def test_later_closed_directional_retest_is_detected() -> None:
    bars = [
        m15(0, 101.2, 101.4, 100.3, 100.5),
        m15(1, 100.5, 101.5, 100.1, 101.3),
    ]
    signal = detect_15m_vc_zone_test(bars, vc_signal(), "long", bars[-1].close_time)
    assert signal is not None
    assert signal.test_bar == bars[-1]
    assert signal.test_bar.open_time >= signal.vc.signal_bar.close_time


def test_bar_inside_forming_h1_vc_is_not_later_retest() -> None:
    embedded = ClosedBar(
        symbol="BTCUSDT",
        timeframe="15m",
        open_time=BASE + timedelta(minutes=45),
        close_time=BASE + timedelta(hours=1),
        open=100.2,
        high=101.2,
        low=100.0,
        close=101.0,
        volume=100.0,
    )
    assert detect_15m_vc_zone_test([embedded], vc_signal(), "long", embedded.close_time) is None


def test_touch_without_directional_rejection_is_not_valid() -> None:
    weak = m15(0, 101.0, 101.2, 100.1, 100.2)
    assert detect_15m_vc_zone_test([weak], vc_signal(), "long", weak.close_time) is None


def test_future_retest_is_invisible() -> None:
    future = m15(4, 100.5, 101.5, 100.1, 101.3)
    at = BASE + timedelta(hours=1, minutes=30)
    assert detect_15m_vc_zone_test([future], vc_signal(), "long", at) is None


def main() -> int:
    test_later_closed_directional_retest_is_detected()
    test_bar_inside_forming_h1_vc_is_not_later_retest()
    test_touch_without_directional_rejection_is_not_valid()
    test_future_retest_is_invisible()
    print("SMOKE MTF V2 VC-zone test smoke tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
