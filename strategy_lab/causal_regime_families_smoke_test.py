#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from strategy_lab.causal_regime_families import (
    POLICIES,
    build_regime_points,
    policy_decision,
    regime_asof,
)


@dataclass(frozen=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float


def main() -> int:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    candles: list[Candle] = []
    price = 100.0
    for idx in range(4 * 24 * 50):
        t = start + timedelta(minutes=15 * idx)
        drift = 0.03 if idx < 4 * 24 * 30 else -0.02
        close = price + drift
        candles.append(Candle(t, price, max(price, close) + 0.1, min(price, close) - 0.1, close))
        price = close

    points = build_regime_points(candles)
    assert points, "expected completed causal regime points"
    probe = points[-1]
    assert regime_asof(points, probe.available_time - timedelta(seconds=1)) is not probe
    assert regime_asof(points, probe.available_time) == probe

    assert policy_decision("LONG_CONTROL_ALL_REGIMES", "long", "bear") == (True, 1.0)
    assert policy_decision("LONG_BULL_TREND_ONLY", "long", "neutral") == (False, 1.0)
    assert policy_decision("LONG_BULL_OR_NEUTRAL_SOFT_RISK", "long", "bear") == (True, 0.40)
    assert policy_decision("SHORT_BEAR_TREND_ONLY", "short", "bear") == (True, 1.0)
    assert policy_decision("SHORT_BEAR_OR_NEUTRAL_SOFT_RISK", "short", "bull") == (True, 0.40)
    assert len(POLICIES) == 6
    print("causal regime family smoke test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
