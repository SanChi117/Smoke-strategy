#!/usr/bin/env python3
"""Smoke tests for closed H1 volume confirmation."""
from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.mtf_dealing_range_v2 import ClosedBar, Level
from strategy_lab.mtf_volume_confirmation_v2 import detect_h1_volume_confirmation


BASE = datetime(2026, 1, 1)


def bar(index: int, open_price: float, high: float, low: float, close: float, volume: float = 100.0) -> ClosedBar:
    start = BASE + timedelta(hours=index)
    return ClosedBar(
        symbol="BTCUSDT",
        timeframe="1h",
        open_time=start,
        close_time=start + timedelta(hours=1),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def poi() -> Level:
    return Level(
        symbol="BTCUSDT",
        timeframe="4h",
        kind="imbalance",
        side="support",
        low=99.0,
        high=100.0,
        formed_at=BASE,
        confirmed_at=BASE,
        strength=75.0,
        source="test",
    )


def rows_with_vc() -> list[ClosedBar]:
    rows: list[ClosedBar] = []
    for index in range(20):
        base = 100.0 + (index % 4) * 0.1
        rows.append(bar(index, base, base + 0.5, base - 0.5, base + 0.05, 100.0))
    rows[-3] = bar(17, 100.0, 100.4, 99.4, 99.8, 100.0)
    rows[-2] = bar(18, 99.8, 100.1, 99.0, 99.5, 100.0)
    rows[-1] = bar(19, 99.5, 102.5, 100.8, 102.2, 180.0)
    return rows


def test_closed_h1_imbalance_vc_is_detected() -> None:
    rows = rows_with_vc()
    signal = detect_h1_volume_confirmation(rows, poi(), "long", rows[-1].close_time)
    assert signal is not None
    assert signal.displacement
    assert signal.imbalance or signal.bos
    assert signal.signal_bar.close_time <= rows[-1].close_time
    assert signal.zone_low <= signal.zone_high


def test_simple_reaction_without_displacement_is_not_vc() -> None:
    rows = rows_with_vc()
    last = rows[-1]
    rows[-1] = bar(19, 99.5, 100.7, 99.2, 100.3, 100.0)
    assert detect_h1_volume_confirmation(rows, poi(), "long", rows[-1].close_time) is None


def test_future_vc_is_invisible() -> None:
    rows = rows_with_vc()
    at = rows[-2].close_time
    assert detect_h1_volume_confirmation(rows, poi(), "long", at) is None


def test_vc_requires_poi_contact() -> None:
    rows = rows_with_vc()
    far = Level(
        symbol="BTCUSDT",
        timeframe="4h",
        kind="imbalance",
        side="support",
        low=80.0,
        high=81.0,
        formed_at=BASE,
        confirmed_at=BASE,
        strength=75.0,
        source="far",
    )
    assert detect_h1_volume_confirmation(rows, far, "long", rows[-1].close_time) is None


def main() -> int:
    test_closed_h1_imbalance_vc_is_detected()
    test_simple_reaction_without_displacement_is_not_vc()
    test_future_vc_is_invisible()
    test_vc_requires_poi_contact()
    print("SMOKE MTF V2 H1 VC tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
