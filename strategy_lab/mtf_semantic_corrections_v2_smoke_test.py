#!/usr/bin/env python3
"""Regression tests for definition-only SMOKE MTF V2 semantic corrections."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from strategy_lab.mtf_dealing_range_v2 import ClosedBar, Level, Pivot, _nearest_levels
from strategy_lab.mtf_entry_model_v2 import EntryConfig, _select_stop
from strategy_lab.mtf_raid_signal_v2 import RaidSignal
from strategy_lab.mtf_target_selection_v2 import directional_target_levels


BASE = datetime(2025, 2, 1)


def _bar(index: int, low: float = 99.0, high: float = 101.0) -> ClosedBar:
    start = BASE + timedelta(hours=index)
    return ClosedBar(
        symbol="BTCUSDT",
        timeframe="1h",
        open_time=start,
        close_time=start + timedelta(hours=1),
        open=100.0,
        high=high,
        low=low,
        close=100.0,
        volume=100.0,
    )


def _pivot(kind: str, price: float) -> Pivot:
    return Pivot(
        symbol="BTCUSDT",
        timeframe="1h",
        kind=kind,
        bar_open_time=BASE,
        bar_close_time=BASE + timedelta(hours=1),
        confirmed_at=BASE + timedelta(hours=3),
        price=price,
        left_bars=2,
        right_bars=2,
        prominence_pct=1.0,
        displacement_pct=1.0,
        strength=80.0,
    )


def _level(side: str, low: float, high: float, *, fresh: bool, touches: int, source: str) -> Level:
    return Level(
        symbol="BTCUSDT",
        timeframe="1h",
        kind="pivot_fractal",
        side=side,
        low=low,
        high=high,
        formed_at=BASE,
        confirmed_at=BASE + timedelta(hours=3),
        strength=70.0,
        source=source,
        fresh=fresh,
        touches=touches,
    )


def test_raid_stop_is_beyond_actual_sweep_extreme() -> None:
    rows = [_bar(index) for index in range(14)]
    raid_bar = _bar(13, low=90.0, high=110.0)
    rows[-1] = raid_bar
    engine = SimpleNamespace(bars={"1h": rows})
    config = EntryConfig(stop_buffer_atr=0.10)

    long_raid = RaidSignal(
        symbol="BTCUSDT",
        side="long",
        pivot=_pivot("low", 100.0),
        raid_bar=raid_bar,
        fresh=True,
        strength=80.0,
    )
    short_raid = RaidSignal(
        symbol="BTCUSDT",
        side="short",
        pivot=_pivot("high", 100.0),
        raid_bar=raid_bar,
        fresh=True,
        strength=80.0,
    )

    long_stop = _select_stop(engine, "BTCUSDT", raid_bar.close_time, "long", 120.0, None, long_raid, config)
    short_stop = _select_stop(engine, "BTCUSDT", raid_bar.close_time, "short", 80.0, None, short_raid, config)
    assert long_stop is not None and long_stop < raid_bar.low
    assert short_stop is not None and short_stop > raid_bar.high


def test_target_map_excludes_mitigated_levels() -> None:
    stale = _level("resistance", 101.0, 102.0, fresh=False, touches=9, source="stale_fvg")
    active = _level("resistance", 110.0, 111.0, fresh=True, touches=0, source="fresh_liquidity")
    selected = directional_target_levels([stale, active], "long", 100.0, "1h")
    assert selected == [active]


def test_context_nearest_levels_respect_level_side() -> None:
    support = _level("support", 95.0, 96.0, fresh=True, touches=0, source="support")
    wrong_side_below = _level("resistance", 99.0, 99.5, fresh=True, touches=0, source="wrong_below")
    resistance = _level("resistance", 104.0, 105.0, fresh=True, touches=0, source="resistance")
    wrong_side_above = _level("support", 100.5, 101.0, fresh=True, touches=0, source="wrong_above")
    nearest_support, nearest_resistance = _nearest_levels(
        [support, wrong_side_below, resistance, wrong_side_above], 100.0
    )
    assert nearest_support == support
    assert nearest_resistance == resistance


def main() -> int:
    test_raid_stop_is_beyond_actual_sweep_extreme()
    test_target_map_excludes_mitigated_levels()
    test_context_nearest_levels_respect_level_side()
    print("SMOKE MTF V2 semantic correction tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
