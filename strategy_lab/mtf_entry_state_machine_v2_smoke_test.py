#!/usr/bin/env python3
"""End-to-end orchestration tests for both SMOKE MTF V2 entry branches."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta

import strategy_lab.mtf_entry_model_v2 as model
from strategy_lab.event_risk import EventRiskDecision
from strategy_lab.mtf_dealing_range_v2 import (
    ClosedBar,
    Level,
    MarketState,
    MtfContextSnapshot,
    Pivot,
    SetupState,
    TimeframeContext,
)
from strategy_lab.mtf_raid_signal_v2 import RaidSignal
from strategy_lab.mtf_target_selection_v2 import TargetSelection
from strategy_lab.mtf_vc_zone_test_v2 import VcZoneTestSignal
from strategy_lab.mtf_volume_confirmation_v2 import VolumeConfirmationSignal


NOW = datetime(2026, 1, 2, 12, 15)


def closed_bar(timeframe: str, start: datetime, minutes: int, open_price: float, close: float) -> ClosedBar:
    high = max(open_price, close) + 0.5
    low = min(open_price, close) - 0.5
    return ClosedBar(
        symbol="BTCUSDT",
        timeframe=timeframe,
        open_time=start,
        close_time=start + timedelta(minutes=minutes),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=100.0,
    )


ENTRY_BAR = closed_bar("15m", NOW, 15, 100.0, 100.2)
H1_RAID_BAR = closed_bar("1h", NOW - timedelta(hours=2), 60, 101.0, 100.0)
H1_VC_BAR = closed_bar("1h", NOW - timedelta(hours=3), 60, 99.0, 101.0)
VC_TEST_BAR = closed_bar("15m", NOW - timedelta(minutes=30), 15, 100.5, 101.0)
M5_BOS_BAR = closed_bar("5m", NOW - timedelta(minutes=5), 5, 100.0, 101.5)


POI = Level(
    symbol="BTCUSDT",
    timeframe="4h",
    kind="imbalance",
    side="support",
    low=98.5,
    high=99.5,
    formed_at=NOW - timedelta(days=2),
    confirmed_at=NOW - timedelta(days=1),
    strength=75.0,
    source="test_poi",
)

RAID_PIVOT = Pivot(
    symbol="BTCUSDT",
    timeframe="1h",
    kind="low",
    bar_open_time=NOW - timedelta(hours=6),
    bar_close_time=NOW - timedelta(hours=5),
    confirmed_at=NOW - timedelta(hours=3),
    price=98.0,
    left_bars=2,
    right_bars=2,
    prominence_pct=1.0,
    displacement_pct=1.0,
    strength=75.0,
)

BOS_PIVOT = Pivot(
    symbol="BTCUSDT",
    timeframe="5m",
    kind="high",
    bar_open_time=NOW - timedelta(minutes=40),
    bar_close_time=NOW - timedelta(minutes=35),
    confirmed_at=NOW - timedelta(minutes=25),
    price=101.0,
    left_bars=2,
    right_bars=2,
    prominence_pct=0.5,
    displacement_pct=0.8,
    strength=75.0,
)

RAID = RaidSignal("BTCUSDT", "long", RAID_PIVOT, H1_RAID_BAR, True, 80.0)
VC = VolumeConfirmationSignal(
    symbol="BTCUSDT",
    side="long",
    signal_bar=H1_VC_BAR,
    poi=POI,
    displacement=True,
    imbalance=True,
    bos=False,
    broken_pivot=None,
    zone_low=99.5,
    zone_high=100.5,
    strength=80.0,
)
VC_TEST = VcZoneTestSignal("BTCUSDT", "long", VC, VC_TEST_BAR, 99.5, 100.5, 80.0)
BOS = model.BosSignal("BTCUSDT", "long", BOS_PIVOT, M5_BOS_BAR, True, True, 80.0)


def context(timeframe: str) -> TimeframeContext:
    return TimeframeContext(
        symbol="BTCUSDT",
        timeframe=timeframe,
        timestamp=NOW,
        state=MarketState.BULLISH,
        trend_strength=80.0,
        dealing_range=None,
        last_close=100.0,
        premium_discount=0.35,
        pivot_count=6,
        level_count=8,
        nearest_support=POI,
        nearest_resistance=None,
    )


SNAPSHOT = MtfContextSnapshot(
    symbol="BTCUSDT",
    timestamp=NOW,
    monthly=context("1M"),
    weekly=context("1w"),
    daily=context("1d"),
    h4=context("4h"),
    h1=context("1h"),
    m15=context("15m"),
    m5=context("5m"),
    scenario=MarketState.BULLISH,
    scenario_strength=80.0,
    setup_state=SetupState.H4_RANGE_READY,
    long_allowed=True,
    short_allowed=False,
    reasons=(),
)


class FakeEngine:
    def __init__(self) -> None:
        self.bars = {
            "5m": [M5_BOS_BAR],
            "15m": [ENTRY_BAR, VC_TEST_BAR],
            "1h": [H1_RAID_BAR, H1_VC_BAR],
            "4h": [],
            "1d": [],
            "1w": [],
            "1M": [],
        }

    def snapshot(self, symbol: str, timestamp: datetime) -> MtfContextSnapshot:
        assert symbol == "BTCUSDT"
        assert timestamp == NOW
        return SNAPSHOT


@contextmanager
def patched(**replacements):
    originals = {name: getattr(model, name) for name in replacements}
    for name, replacement in replacements.items():
        setattr(model, name, replacement)
    try:
        yield
    finally:
        for name, original in originals.items():
            setattr(model, name, original)


def common_patches() -> dict:
    return {
        "find_active_poi": lambda *args, **kwargs: POI,
        "detect_h1_reaction": lambda *args, **kwargs: True,
        "detect_5m_bos": lambda *args, **kwargs: BOS,
        "find_next_15m_entry_bar": lambda *args, **kwargs: ENTRY_BAR,
        "_select_stop": lambda *args, **kwargs: 98.0,
        "select_timeframe_matched_target": lambda *args, **kwargs: TargetSelection(
            "BTCUSDT", "long", 104.0, "4h", "4h_fta", 80.0
        ),
    }


def test_fresh_raid_path_reaches_entry_ready() -> None:
    replacements = common_patches() | {
        "detect_h1_raid_signal": lambda *args, **kwargs: RAID,
        "detect_h1_volume_confirmation": lambda *args, **kwargs: None,
        "detect_15m_vc_zone_test": lambda *args, **kwargs: None,
    }
    with patched(**replacements):
        plan = model.MtfEntryModelV2(FakeEngine()).evaluate("BTCUSDT", NOW, "long")
    assert plan.allowed
    assert plan.setup_state is SetupState.ENTRY_READY
    assert plan.h1_raid and not plan.h1_vc and not plan.vc_zone_test
    assert plan.target_timeframe == "4h"
    assert plan.rr == 2.0


def test_untested_vc_cannot_reach_entry_ready() -> None:
    replacements = common_patches() | {
        "detect_h1_raid_signal": lambda *args, **kwargs: None,
        "detect_h1_volume_confirmation": lambda *args, **kwargs: VC,
        "detect_15m_vc_zone_test": lambda *args, **kwargs: None,
    }
    with patched(**replacements):
        plan = model.MtfEntryModelV2(FakeEngine()).evaluate("BTCUSDT", NOW, "long")
    assert not plan.allowed
    assert plan.h1_vc and not plan.vc_zone_test
    assert "h1_vc_zone_not_tested_on_closed_15m" in plan.reasons


def test_tested_vc_path_reaches_entry_ready() -> None:
    replacements = common_patches() | {
        "detect_h1_raid_signal": lambda *args, **kwargs: None,
        "detect_h1_volume_confirmation": lambda *args, **kwargs: VC,
        "detect_15m_vc_zone_test": lambda *args, **kwargs: VC_TEST,
    }
    with patched(**replacements):
        plan = model.MtfEntryModelV2(FakeEngine()).evaluate("BTCUSDT", NOW, "long")
    assert plan.allowed
    assert plan.h1_vc and plan.vc_zone_test and not plan.h1_raid
    assert plan.setup_state is SetupState.ENTRY_READY


def test_high_impact_event_blocks_otherwise_valid_path() -> None:
    replacements = common_patches() | {
        "detect_h1_raid_signal": lambda *args, **kwargs: RAID,
        "detect_h1_volume_confirmation": lambda *args, **kwargs: None,
        "detect_15m_vc_zone_test": lambda *args, **kwargs: None,
    }
    decision = EventRiskDecision(NOW, "BTCUSDT", True, 0.0, ("event",), ("high impact",))
    with patched(**replacements):
        plan = model.MtfEntryModelV2(FakeEngine()).evaluate(
            "BTCUSDT", NOW, "long", event_decision=decision
        )
    assert not plan.allowed
    assert plan.event_blocked
    assert "high_impact_event_blackout" in plan.reasons


def main() -> int:
    test_fresh_raid_path_reaches_entry_ready()
    test_untested_vc_cannot_reach_entry_ready()
    test_tested_vc_path_reaches_entry_ready()
    test_high_impact_event_blocks_otherwise_valid_path()
    print("SMOKE MTF V2 entry state-machine tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
