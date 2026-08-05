#!/usr/bin/env python3
"""Regression test for the two-bar pullback-resumption entry."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from strategy_lab.feature_builder import MarketFeature
from strategy_lab.risk_model import build_risk_plan
from strategy_lab.setup_generator import CandidateSetup, generate_candidate_setups
from strategy_lab.trade_quality_score import entry_score


def feature(time: datetime, close: float, position: float, candle: str, volume_ratio: float) -> MarketFeature:
    return MarketFeature(
        symbol="TESTUSDT",
        time=time,
        close=close,
        volume=1000.0,
        trend_context="trend",
        volatility_regime="normal",
        structure_type="trend_pullback",
        setup_bias="pullback",
        ema_fast=101.0,
        ema_slow=103.0,
        atr_pct=1.2,
        range_pct=5.0,
        volume_ratio=volume_ratio,
        body_pct=0.45,
        upper_wick_pct=0.20,
        lower_wick_pct=0.15,
        trend_direction="down",
        trend_strength=0.8,
        ema_fast_slope_pct=-0.2,
        range_position=position,
        donchian_high=110.0,
        donchian_low=90.0,
        distance_to_high_pct=8.0,
        distance_to_low_pct=6.0,
        volume_state="normal",
        candle_signal=candle,
        liquidity_event="none",
        setup_quality=78.0,
        entry_trend_context="trend",
        entry_trend_direction="down",
        entry_volatility_regime="normal",
        entry_volume_state="normal",
        entry_candle_signal=candle,
        entry_liquidity_event="none",
        entry_range_position=position,
        context_4h_trend_context="trend",
        context_4h_trend_direction="down",
        context_4h_volatility_regime="normal",
        context_4h_volume_state="normal",
        context_1d_trend_context="trend",
        context_1d_trend_direction="down",
        context_1d_volatility_regime="normal",
        context_1d_volume_state="normal",
        context_alignment="aligned",
    )


def main() -> int:
    t0 = datetime(2026, 1, 1, 12, 0)
    previous = feature(t0, close=100.5, position=0.60, candle="neutral", volume_ratio=0.9)
    trigger = feature(t0 + timedelta(minutes=15), close=99.5, position=0.48, candle="bear_impulse", volume_ratio=1.1)
    rows = generate_candidate_setups([previous, trigger], min_confidence=40.0)
    resumption = [row for row in rows if row.entry_time == trigger.time]
    assert len(resumption) == 1, rows
    candidate = resumption[0]
    assert candidate.side == "short", candidate
    assert candidate.setup_type == "pullback_resumption_strict", candidate
    assert "trigger=two_bar_strict" in candidate.reason
    assert "prev_pos=0.6" in candidate.reason

    legacy = replace(candidate, setup_type="pullback")
    new_plan = build_risk_plan(candidate)
    legacy_plan = build_risk_plan(legacy)
    assert new_plan.stop_pct == legacy_plan.stop_pct
    assert new_plan.target_rr == legacy_plan.target_rr
    assert entry_score(candidate.setup_type, new_plan.stop_pct * 100) == entry_score("pullback", legacy_plan.stop_pct * 100)

    # A bullish continuation candle must not be relabelled as resumption.
    bullish = feature(t0 + timedelta(minutes=30), close=100.0, position=0.47, candle="bull_impulse", volume_ratio=1.1)
    bullish_rows = generate_candidate_setups([previous, bullish], min_confidence=40.0)
    assert all(row.setup_type not in {"pullback_resumption", "pullback_resumption_strict"} for row in bullish_rows)

    print("pullback_resumption_smoke_test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
