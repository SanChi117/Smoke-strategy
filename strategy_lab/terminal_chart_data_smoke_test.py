#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import unittest

from strategy_lab.terminal_chart_data import aggregate_ohlcv, chart_bundle, ema_points


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class TerminalChartDataTest(unittest.TestCase):
    def setUp(self) -> None:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self.rows = [
            Bar(start + timedelta(minutes=15 * i), 100 + i, 102 + i, 99 + i, 101 + i, 10 + i)
            for i in range(8)
        ]

    def test_aggregates_15m_to_1h_in_utc_order(self) -> None:
        rows = aggregate_ohlcv(self.rows, "1h")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["open"], 100.0)
        self.assertEqual(rows[0]["high"], 105.0)
        self.assertEqual(rows[0]["low"], 99.0)
        self.assertEqual(rows[0]["close"], 104.0)
        self.assertEqual(rows[0]["volume"], 46.0)
        self.assertLess(rows[0]["time"], rows[1]["time"])

    def test_ema_is_causal_and_initialized_from_first_close(self) -> None:
        rows = aggregate_ohlcv(self.rows[:3], "15m")
        points = ema_points(rows, 3)
        self.assertEqual(points[0]["value"], 101.0)
        self.assertAlmostEqual(points[1]["value"], 101.5)
        self.assertAlmostEqual(points[2]["value"], 102.25)

    def test_bundle_limits_rows_and_aligns_indicators(self) -> None:
        bundle = chart_bundle(self.rows, "15m", limit=5)
        self.assertEqual(len(bundle["candles"]), 5)
        self.assertEqual(len(bundle["ema20"]), 5)
        self.assertEqual(bundle["candles"][0]["time"], bundle["ema20"][0]["time"])

    def test_unknown_timeframe_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported timeframe"):
            aggregate_ohlcv(self.rows, "5m")


if __name__ == "__main__":
    unittest.main(verbosity=2)
