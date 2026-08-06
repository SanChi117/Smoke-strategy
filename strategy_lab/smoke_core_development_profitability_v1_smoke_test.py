#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from strategy_lab.economics_risk_portfolio_v1 import CostModel
from strategy_lab.market_data import Candle
from strategy_lab.smoke_core_development_profitability_v1 import CapturedPlan, _resolve_plan

BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


class DevelopmentProfitabilityV1Test(unittest.TestCase):
    def plan(self, direction="LONG"):
        return CapturedPlan(
            observation={"direction": direction, "fold": 0, "fingerprint": "fp", "symbol": "BTCUSDT", "family": "X"},
            entry_price=100.0,
            stop_price=99.0 if direction == "LONG" else 101.0,
            target_price=102.0 if direction == "LONG" else 98.0,
            entry_start=BASE.isoformat(),
            upstream_score=90.0,
        )

    def test_same_bar_collision_is_stop_first(self):
        candles = [Candle("BTCUSDT", BASE, 100.0, 103.0, 98.0, 101.0, 1.0)]
        result = _resolve_plan(self.plan(), candles, [BASE], CostModel())
        self.assertEqual(result.outcome, "STOP")
        self.assertLess(result.net_move_pct, 0)

    def test_short_target(self):
        candles = [Candle("BTCUSDT", BASE, 100.0, 100.5, 97.5, 98.0, 1.0)]
        result = _resolve_plan(self.plan("SHORT"), candles, [BASE], CostModel())
        self.assertEqual(result.outcome, "TARGET")
        self.assertGreater(result.net_move_pct, 0)

    def test_unresolved_uses_final_close(self):
        candles = [
            Candle("BTCUSDT", BASE, 100.0, 100.5, 99.5, 100.2, 1.0),
            Candle("BTCUSDT", BASE + timedelta(minutes=5), 100.2, 100.7, 99.7, 100.4, 1.0),
        ]
        result = _resolve_plan(self.plan(), candles, [row.time for row in candles], CostModel())
        self.assertEqual(result.outcome, "FORCED_END")
        self.assertEqual(result.exit_time, candles[-1].time)


if __name__ == "__main__":
    unittest.main(verbosity=2)
