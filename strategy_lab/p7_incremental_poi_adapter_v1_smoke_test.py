#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

import strategy_lab.poi_imbalance_engine_v1 as p1
from strategy_lab.mtf_dealing_range_v2 import ClosedBar
from strategy_lab.p7_incremental_poi_adapter_v1 import (
    IncrementalPOITimeframeStream,
)


START = datetime(2024, 1, 1, tzinfo=timezone.utc)


def bar(index: int, open_: float, high: float, low: float, close: float) -> ClosedBar:
    opened = START + timedelta(hours=index)
    return ClosedBar(
        symbol="TESTUSDT",
        timeframe="1h",
        open_time=opened,
        close_time=opened + timedelta(hours=1),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100.0 + index,
    )


def fixture_bars() -> list[ClosedBar]:
    rows: list[ClosedBar] = []
    for index in range(44):
        center = 100.0 if index < 20 else 98.5
        drift = 0.08 if index % 2 == 0 else -0.08
        open_ = center
        close = center + drift
        rows.append(
            bar(
                index,
                open_,
                max(open_, close) + 0.35,
                min(open_, close) - 0.35,
                close,
            )
        )

    rows[14] = bar(14, 100.0, 100.2, 99.4, 99.6)
    rows[15] = bar(15, 99.6, 102.2, 99.5, 102.0)
    rows[16] = bar(16, 102.0, 102.4, 100.4, 102.1)
    rows[17] = bar(17, 102.1, 102.2, 99.8, 100.0)
    rows[18] = bar(18, 100.0, 100.1, 98.8, 99.0)
    rows[19] = bar(19, 99.0, 99.1, 98.2, 98.4)

    rows[30] = bar(30, 98.5, 99.2, 98.3, 99.0)
    rows[31] = bar(31, 99.0, 99.1, 96.3, 96.5)
    rows[32] = bar(32, 96.5, 98.0, 96.1, 96.4)
    rows[33] = bar(33, 96.4, 98.6, 96.2, 98.4)
    rows[34] = bar(34, 98.4, 99.7, 98.3, 99.5)
    rows[35] = bar(35, 99.5, 100.2, 99.4, 100.0)
    return rows


class P7IncrementalPOIAdapterV1Test(unittest.TestCase):
    def test_incremental_stream_matches_frozen_p1_at_every_close(self) -> None:
        rows = fixture_bars()
        stream = IncrementalPOITimeframeStream(rows)
        frozen = p1.POIImbalanceEngine()
        saw_zone = False
        saw_fvg = False
        saw_invalidated = False

        for current in rows:
            expected = frozen.detect(rows, current.close_time)
            expected_active = tuple(
                zone
                for zone in expected.zones
                if zone.state != p1.POIState.INVALIDATED
            )
            actual_active, evidence_map = stream.advance(current.close_time)
            actual_evidence = tuple(
                sorted(
                    evidence_map.values(),
                    key=lambda item: (item.confirmed_at, item.evidence_id),
                )
            )

            self.assertEqual(
                actual_active,
                expected_active,
                f"zone mismatch at {current.close_time.isoformat()}",
            )
            self.assertEqual(
                actual_evidence,
                expected.evidence,
                f"evidence mismatch at {current.close_time.isoformat()}",
            )
            saw_zone = saw_zone or bool(expected.zones)
            saw_fvg = saw_fvg or any(
                zone.source_type == p1.POISourceType.FVG_IMBALANCE
                for zone in expected.zones
            )
            saw_invalidated = saw_invalidated or any(
                zone.state == p1.POIState.INVALIDATED
                for zone in expected.zones
            )

        self.assertTrue(saw_zone)
        self.assertTrue(saw_fvg)
        self.assertTrue(saw_invalidated)

    def test_stream_rejects_time_reversal(self) -> None:
        rows = fixture_bars()
        stream = IncrementalPOITimeframeStream(rows)
        stream.advance(rows[20].close_time)
        with self.assertRaisesRegex(ValueError, "monotonic"):
            stream.advance(rows[10].close_time)


if __name__ == "__main__":
    unittest.main(verbosity=2)
