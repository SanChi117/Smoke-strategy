#!/usr/bin/env python3
"""Smoke tests for timeframe-matched SMOKE MTF V2 targets."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from strategy_lab.mtf_dealing_range_v2 import ClosedBar, Level, Pivot
from strategy_lab.mtf_raid_signal_v2 import RaidSignal
from strategy_lab.mtf_target_selection_v2 import (
    _context_range_candidates,
    directional_target_levels,
    preferred_target_timeframe,
)


BASE = datetime(2026, 1, 1)


def level(timeframe: str, side: str, price: float, source: str) -> Level:
    return Level(
        symbol="BTCUSDT",
        timeframe=timeframe,
        kind="pivot",
        side=side,
        low=price,
        high=price,
        formed_at=BASE,
        confirmed_at=BASE,
        strength=70.0,
        source=source,
    )


def raid() -> RaidSignal:
    pivot = Pivot(
        symbol="BTCUSDT",
        timeframe="1h",
        kind="low",
        bar_open_time=BASE,
        bar_close_time=BASE + timedelta(hours=1),
        confirmed_at=BASE + timedelta(hours=3),
        price=98.0,
        left_bars=2,
        right_bars=2,
        prominence_pct=1.0,
        displacement_pct=1.0,
        strength=75.0,
    )
    bar = ClosedBar(
        symbol="BTCUSDT",
        timeframe="1h",
        open_time=BASE + timedelta(hours=4),
        close_time=BASE + timedelta(hours=5),
        open=99.0,
        high=101.0,
        low=97.0,
        close=100.0,
        volume=100.0,
    )
    return RaidSignal("BTCUSDT", "long", pivot, bar, True, 80.0)


def test_raid_uses_raid_timeframe() -> None:
    assert preferred_target_timeframe(None, raid()) == "1h"


def test_poi_uses_its_tradable_timeframe() -> None:
    assert preferred_target_timeframe(level("4h", "support", 100.0, "poi"), None) == "4h"
    assert preferred_target_timeframe(level("1d", "support", 100.0, "poi"), None) == "1d"
    assert preferred_target_timeframe(level("1w", "support", 100.0, "poi"), None) == "1d"
    assert preferred_target_timeframe(level("1M", "support", 100.0, "poi"), None) == "1d"


def test_closer_wrong_timeframe_target_is_ignored() -> None:
    levels = [
        level("1h", "resistance", 101.0, "wrong_near"),
        level("4h", "resistance", 104.0, "correct_far"),
        level("4h", "support", 95.0, "wrong_side"),
    ]
    selected = directional_target_levels(levels, "long", 100.0, "4h")
    assert [item.source for item in selected] == ["correct_far"]


def test_directional_filter_rejects_levels_behind_entry() -> None:
    levels = [
        level("1h", "resistance", 99.0, "behind_long"),
        level("1h", "support", 101.0, "behind_short"),
    ]
    assert directional_target_levels(levels, "long", 100.0, "1h") == []
    assert directional_target_levels(levels, "short", 100.0, "1h") == []


def test_context_range_target_uses_direction_strength_field() -> None:
    dealing_range = SimpleNamespace(
        symbol="BTCUSDT",
        weak_level=104.0,
        high=106.0,
        low=94.0,
        direction_strength=63.5,
    )
    context = SimpleNamespace(dealing_range=dealing_range)
    snapshot = SimpleNamespace(
        h1=context,
        h4=context,
        daily=context,
        weekly=context,
        monthly=context,
    )
    candidates = _context_range_candidates(snapshot, "4h", "long", 100.0)
    assert [item.source for item in candidates] == ["weak_high", "range_high"]
    assert all(item.strength == 63.5 for item in candidates)


def main() -> int:
    test_raid_uses_raid_timeframe()
    test_poi_uses_its_tradable_timeframe()
    test_closer_wrong_timeframe_target_is_ignored()
    test_directional_filter_rejects_levels_behind_entry()
    test_context_range_target_uses_direction_strength_field()
    print("SMOKE MTF V2 target selection tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
