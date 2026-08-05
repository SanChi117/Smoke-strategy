#!/usr/bin/env python3
"""Smoke tests for real-history recognition export without outcomes."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

import strategy_lab.mtf_recognition_export_v2 as export
from strategy_lab.mtf_dealing_range_v2 import ClosedBar, MarketState, SetupState


BASE = datetime(2026, 1, 1)


def bar(index: int) -> ClosedBar:
    start = BASE + timedelta(minutes=15 * index)
    return ClosedBar(
        symbol="BTCUSDT",
        timeframe="15m",
        open_time=start,
        close_time=start + timedelta(minutes=15),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=100.0,
    )


def state(value: str):
    return SimpleNamespace(value=value)


def plan(timestamp: datetime, side: str, setup_state: SetupState):
    context_tf = SimpleNamespace(state=state(MarketState.BULLISH.value))
    context = SimpleNamespace(
        scenario=state(MarketState.BULLISH.value),
        scenario_strength=80.0,
        monthly=context_tf,
        weekly=context_tf,
        daily=context_tf,
        h4=context_tf,
        h1=context_tf,
        long_allowed=True,
        short_allowed=False,
    )
    poi = SimpleNamespace(
        timeframe="4h",
        kind="imbalance",
        side="support",
        low=99.0,
        high=100.0,
        confirmed_at=timestamp - timedelta(hours=4),
        strength=75.0,
        source="test",
        fresh=True,
        touches=0,
    )
    return SimpleNamespace(
        evaluated_at=timestamp,
        symbol="BTCUSDT",
        side=side,
        setup_state=setup_state,
        allowed=False,
        context=context,
        poi=poi,
        h1_raid=False,
        raid=None,
        h1_reaction=True,
        h1_vc=True,
        volume_confirmation=SimpleNamespace(strength=80.0),
        vc_zone_test=False,
        vc_test=None,
        bos=None,
        entry_time=None,
        entry=None,
        stop=None,
        target=None,
        target_timeframe=None,
        target_source=None,
        rr=None,
        quality_score=55.0,
        quality_state="QUALIFIED",
        event_blocked=False,
        event_risk_multiplier=1.0,
        reasons=("h1_vc_zone_not_tested_on_closed_15m",),
    )


class FakeEngine:
    def __init__(self, _candles) -> None:
        self.bars = {"15m": [bar(0), bar(1), bar(2)]}


class FakeModel:
    def __init__(self, _engine) -> None:
        pass

    def evaluate(self, symbol: str, timestamp: datetime, side: str):
        assert symbol == "BTCUSDT"
        return plan(timestamp, side, SetupState.POI_TESTED)


class FakeRuntime:
    def stats(self):
        return {"hits": {}, "misses": {}, "sizes": {}}


@contextmanager
def patched_export():
    old_engine = export.MtfDealingRangeEngine
    old_model = export.MtfEntryModelV2
    old_runtime = export.install_fast_runtime
    export.MtfDealingRangeEngine = FakeEngine
    export.MtfEntryModelV2 = FakeModel
    export.install_fast_runtime = lambda _engine: FakeRuntime()
    try:
        yield
    finally:
        export.MtfDealingRangeEngine = old_engine
        export.MtfEntryModelV2 = old_model
        export.install_fast_runtime = old_runtime


def test_forbidden_outcome_fields_are_rejected() -> None:
    export.assert_no_outcome_fields({"planned_rr": 2.0, "quality": 80})
    for key in ("pnl", "future_return", "tp_hit", "sl_hit", "win_rate"):
        try:
            export.assert_no_outcome_fields({key: 1})
        except ValueError:
            pass
        else:
            raise AssertionError(f"{key} must be rejected")


def test_sampling_is_chronological_and_group_bounded() -> None:
    with patched_export():
        result = export.export_recognition_candidates([], BASE, BASE + timedelta(hours=1), per_group=2)
    assert result["mode"] == "NO_PNL_NO_FUTURE_OUTCOME"
    assert result["evaluated_15m_bars"] == 3
    assert result["evaluated_side_snapshots"] == 6
    assert result["selected_snapshots"] == 4
    assert "execution_cache" in result
    timestamps = [row["timestamp"] for row in result["candidates"]]
    assert timestamps == sorted(timestamps)
    export.assert_no_outcome_fields(result)


def test_plan_payload_contains_only_pre_entry_observations() -> None:
    payload = export.plan_payload(plan(BASE, "long", SetupState.POI_TESTED))
    assert payload["planned_entry"] is None
    assert payload["poi"]["timeframe"] == "4h"
    assert "h1_vc_zone_not_tested_on_closed_15m" in payload["reasons"]
    export.assert_no_outcome_fields(payload)


def main() -> int:
    test_forbidden_outcome_fields_are_rejected()
    test_sampling_is_chronological_and_group_bounded()
    test_plan_payload_contains_only_pre_entry_observations()
    print("SMOKE MTF V2 recognition export tests: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
