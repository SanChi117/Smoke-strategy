#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta
import json
import unittest

from strategy_lab.context_liquidity_engine_v1 import (
    ContextLiquidityConfig,
    ContextLiquiditySnapshotV1,
    ContextRegime,
    LiquidityKind,
    LiquidityLevelV1,
    LiquiditySide,
    LiquidityState,
    SessionSpec,
    TimeframeContextState,
    VolatilityRegime,
    _aggregate_context,
    _session_window,
    build_timeframe_state,
    evaluate_liquidity_state,
    select_primary_target,
    snapshot_to_no_pnl_dict,
    target_candidates,
)
from strategy_lab.mtf_dealing_range_v2 import ClosedBar, DealingRange, MarketState, TimeframeContext
from strategy_lab.poi_imbalance_engine_v1 import Direction

BASE = datetime(2026, 1, 2, 0, 0)


def bar(index: int, open_: float, high: float, low: float, close: float, timeframe: str = "5m") -> ClosedBar:
    step = timedelta(minutes=5 if timeframe == "5m" else 60)
    opened = BASE + index * step
    return ClosedBar("BTCUSDT", timeframe, opened, opened + step, open_, high, low, close, 100.0)


def level(
    *,
    level_id: str = "level-1",
    side: LiquiditySide = LiquiditySide.BUY_SIDE,
    low: float = 101.0,
    high: float = 101.0,
    external: bool = True,
    state: LiquidityState = LiquidityState.FRESH,
    strength: float = 70.0,
) -> LiquidityLevelV1:
    return LiquidityLevelV1(
        level_id=level_id,
        symbol="BTCUSDT",
        timeframe="4h" if external else "1h",
        kind=LiquidityKind.RANGE_HIGH if side == LiquiditySide.BUY_SIDE else LiquidityKind.RANGE_LOW,
        side=side,
        low=low,
        high=high,
        formed_at=BASE,
        confirmed_at=BASE,
        state=state,
        strength_0_100=strength,
        touch_count=0,
        swept_at=None,
        invalidated_at=None,
        source="fixture",
        source_event_ids=("event-1",),
        external=external,
    )


def tf_state(tf: str, direction: Direction, confidence: float, market: str = "BULLISH") -> TimeframeContextState:
    return TimeframeContextState(
        symbol="BTCUSDT",
        timeframe=tf,
        evaluated_at=BASE,
        direction=direction,
        market_state=market,
        confidence_0_100=confidence,
        range_low=90.0,
        range_high=110.0,
        equilibrium=100.0,
        premium_discount_0_1=0.5,
        protected_level=95.0,
        weak_level=110.0,
        range_confirmed_at=BASE,
        atr_pct=1.0,
        volatility_regime=VolatilityRegime.NORMAL,
        pivot_count=4,
        level_count=5,
        valid_until=BASE + timedelta(hours=4),
    )


class ContextLiquidityEngineV1SmokeTest(unittest.TestCase):
    def test_context_conflict_reduces_confidence_without_hard_block(self) -> None:
        cfg = ContextLiquidityConfig()
        states = {
            "1M": tf_state("1M", Direction.LONG, 80),
            "1w": tf_state("1w", Direction.SHORT, 80, "BEARISH"),
            "1d": tf_state("1d", Direction.LONG, 80),
            "4h": tf_state("4h", Direction.LONG, 80),
        }
        direction, regime, confidence, conflicts = _aggregate_context(states, cfg)
        self.assertEqual(direction, Direction.LONG)
        self.assertIn("macro_timeframe_direction_conflict", conflicts)
        self.assertGreater(confidence, 0)
        self.assertNotEqual(regime, ContextRegime.INSUFFICIENT)

    def test_all_missing_context_is_insufficient(self) -> None:
        direction, regime, confidence, conflicts = _aggregate_context({}, ContextLiquidityConfig())
        self.assertEqual(direction, Direction.NEUTRAL)
        self.assertEqual(regime, ContextRegime.INSUFFICIENT)
        self.assertEqual(confidence, 0)
        self.assertIn("insufficient_macro_context", conflicts)

    def test_build_timeframe_state_uses_closed_context(self) -> None:
        dealing = DealingRange("BTCUSDT", "4h", MarketState.BULLISH, 90, 110, 100, 95, 110, 70, BASE, "fixture")
        context = TimeframeContext(
            symbol="BTCUSDT",
            timeframe="4h",
            timestamp=BASE,
            state=MarketState.BULLISH,
            trend_strength=70,
            dealing_range=dealing,
            last_close=102,
            premium_discount=0.6,
            pivot_count=5,
            level_count=8,
            nearest_support=None,
            nearest_resistance=None,
        )
        rows = [bar(i, 100 + i, 101 + i, 99 + i, 100.5 + i, "1h") for i in range(25)]
        result = build_timeframe_state("BTCUSDT", "4h", context, rows, rows[-1].close_time)
        self.assertEqual(result.direction, Direction.LONG)
        self.assertEqual(result.range_low, 90)
        self.assertGreater(result.confidence_0_100, 70)
        self.assertIsNotNone(result.atr_pct)

    def test_session_window_never_uses_incomplete_current_session(self) -> None:
        spec = SessionSpec("LONDON", 480, 780, 60)
        asof = datetime(2026, 1, 2, 10, 0)
        start, end = _session_window(asof, spec)
        self.assertLessEqual(end, asof)
        self.assertEqual(start.date(), datetime(2026, 1, 1).date())

    def test_buy_side_wick_return_is_sweep(self) -> None:
        original = level(low=101.0, high=101.0)
        rows = [bar(1, 100.5, 101.3, 100.4, 100.9)]
        result = evaluate_liquidity_state(original, rows, rows[-1].close_time, atr=1.0)
        self.assertEqual(result.state, LiquidityState.SWEPT)
        self.assertIsNotNone(result.swept_at)

    def test_sell_side_wick_return_is_sweep(self) -> None:
        original = level(side=LiquiditySide.SELL_SIDE, low=99.0, high=99.0)
        rows = [bar(1, 99.5, 99.6, 98.7, 99.1)]
        result = evaluate_liquidity_state(original, rows, rows[-1].close_time, atr=1.0)
        self.assertEqual(result.state, LiquidityState.SWEPT)

    def test_invalidation_requires_two_consecutive_closes(self) -> None:
        original = level(low=101.0, high=101.0)
        one = [bar(1, 101.0, 101.4, 100.9, 101.2)]
        first = evaluate_liquidity_state(original, one, one[-1].close_time, atr=1.0)
        self.assertNotEqual(first.state, LiquidityState.INVALIDATED)
        two = one + [bar(2, 101.2, 101.5, 101.1, 101.3)]
        second = evaluate_liquidity_state(original, two, two[-1].close_time, atr=1.0)
        self.assertEqual(second.state, LiquidityState.INVALIDATED)
        self.assertEqual(second.strength_0_100, 0)

    def test_target_excludes_swept_and_invalidated_levels(self) -> None:
        levels = [
            level(level_id="fresh", low=102, high=102, state=LiquidityState.FRESH),
            level(level_id="swept", low=101, high=101, state=LiquidityState.SWEPT),
            level(level_id="dead", low=103, high=103, state=LiquidityState.INVALIDATED),
        ]
        result = target_candidates(levels, "BTCUSDT", BASE, 100, Direction.LONG)
        self.assertEqual([item.level_id for item in result], ["fresh"])

    def test_external_target_is_ranked_before_internal(self) -> None:
        levels = [
            level(level_id="internal", low=101, high=101, external=False, strength=90),
            level(level_id="external", low=102, high=102, external=True, strength=60),
        ]
        result = target_candidates(levels, "BTCUSDT", BASE, 100, Direction.LONG)
        self.assertEqual(result[0].level_id, "external")
        self.assertEqual(select_primary_target(result).level_id, "external")

    def test_target_selection_uses_no_rr_parameter(self) -> None:
        levels = [level(level_id="a", low=102, high=102), level(level_id="b", low=105, high=105)]
        result = target_candidates(levels, "BTCUSDT", BASE, 100, Direction.LONG)
        self.assertEqual([item.level_id for item in result], ["a", "b"])

    def test_target_ids_are_deterministic(self) -> None:
        levels = [level(level_id="a", low=102, high=102)]
        first = target_candidates(levels, "BTCUSDT", BASE, 100, Direction.LONG)
        second = target_candidates(levels, "BTCUSDT", BASE, 100, Direction.LONG)
        self.assertEqual(first, second)

    def test_no_pnl_export_contains_no_outcome_fields(self) -> None:
        state = tf_state("4h", Direction.LONG, 80)
        snapshot = ContextLiquiditySnapshotV1(
            symbol="BTCUSDT",
            evaluated_at=BASE,
            direction=Direction.LONG,
            regime=ContextRegime.TREND_UP,
            confidence_0_100=80,
            timeframe_states=(state,),
            liquidity_levels=(level(),),
            long_targets=(),
            short_targets=(),
            dependencies=("POI_LAYER",),
            conflicts=(),
            hard_block=False,
            hard_block_reason=None,
            reasons=("fixture",),
            valid_until=BASE + timedelta(hours=1),
        )
        raw = json.dumps(snapshot_to_no_pnl_dict(snapshot), default=str).lower()
        for forbidden in ("pnl", "future_return", "trade_outcome", "mfe", "mae", "profit_factor", "drawdown"):
            self.assertNotIn(f'"{forbidden}"', raw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
