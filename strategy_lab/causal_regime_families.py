#!/usr/bin/env python3
"""Causal market-regime features for LONG_SHORT_REGIME_FAMILIES_V1.

All reference values are built from completed BTCUSDT candles only.  A feature
record becomes available at the close of its source candle and is joined to a
candidate with an as-of lookup, never by forward filling from the future.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence


@dataclass(frozen=True)
class RegimePoint:
    available_time: datetime
    state: str
    ema50: float
    ema200: float
    ema50_slope: float
    range_midpoint: float
    atr_percentile: float


def _ema(values: Sequence[float], length: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (length + 1.0)
    out = [float(values[0])]
    for value in values[1:]:
        out.append(alpha * float(value) + (1.0 - alpha) * out[-1])
    return out


def _true_ranges(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> list[float]:
    out: list[float] = []
    for idx, (high, low, close) in enumerate(zip(highs, lows, closes)):
        prev_close = closes[idx - 1] if idx else close
        out.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return out


def _rolling_mean(values: Sequence[float], length: int) -> list[float]:
    out: list[float] = []
    total = 0.0
    for idx, value in enumerate(values):
        total += float(value)
        if idx >= length:
            total -= float(values[idx - length])
        out.append(total / min(idx + 1, length))
    return out


def _percentile_rank(history: Sequence[float], value: float) -> float:
    if not history:
        return 0.5
    return sum(1 for item in history if item <= value) / len(history)


def _completed_buckets(candles: Iterable[object], hours: int) -> list[dict[str, object]]:
    """Aggregate source candles into completed UTC-aligned buckets."""
    seconds = hours * 3600
    buckets: dict[int, list[object]] = {}
    for candle in candles:
        ts = int(candle.time.timestamp())
        key = ts - (ts % seconds)
        buckets.setdefault(key, []).append(candle)
    rows: list[dict[str, object]] = []
    for key in sorted(buckets):
        group = sorted(buckets[key], key=lambda item: item.time)
        start = datetime.fromtimestamp(key, tz=group[0].time.tzinfo)
        end = datetime.fromtimestamp(key + seconds, tz=group[0].time.tzinfo)
        # A bucket is usable only if its final source candle reaches the bucket end.
        last = group[-1]
        source_step = (group[-1].time - group[-2].time) if len(group) >= 2 else None
        if source_step is None or last.time + source_step < end:
            continue
        rows.append({
            "time": end,
            "open": float(group[0].open),
            "high": max(float(item.high) for item in group),
            "low": min(float(item.low) for item in group),
            "close": float(group[-1].close),
        })
    return rows


def build_regime_points(btc_candles: Sequence[object]) -> list[RegimePoint]:
    four_h = _completed_buckets(btc_candles, 4)
    one_h = _completed_buckets(btc_candles, 1)
    if len(four_h) < 220 or len(one_h) < 110:
        return []

    closes4 = [float(row["close"]) for row in four_h]
    highs4 = [float(row["high"]) for row in four_h]
    lows4 = [float(row["low"]) for row in four_h]
    ema50 = _ema(closes4, 50)
    ema200 = _ema(closes4, 200)

    highs1 = [float(row["high"]) for row in one_h]
    lows1 = [float(row["low"]) for row in one_h]
    closes1 = [float(row["close"]) for row in one_h]
    atr1 = _rolling_mean(_true_ranges(highs1, lows1, closes1), 14)
    one_times = [row["time"] for row in one_h]

    points: list[RegimePoint] = []
    for idx in range(200, len(four_h)):
        available = four_h[idx]["time"]
        prior_high = max(highs4[idx - 20:idx])
        prior_low = min(lows4[idx - 20:idx])
        midpoint = (prior_high + prior_low) / 2.0
        slope = ema50[idx] - ema50[idx - 1]
        close = closes4[idx]
        if ema50[idx] > ema200[idx] and slope > 0 and close > midpoint:
            state = "bull"
        elif ema50[idx] < ema200[idx] and slope < 0 and close < midpoint:
            state = "bear"
        else:
            state = "neutral"

        one_idx = bisect_right(one_times, available) - 1
        if one_idx < 90:
            atr_pct = 0.5
        else:
            history = atr1[one_idx - 89:one_idx + 1]
            atr_pct = _percentile_rank(history, atr1[one_idx])
        points.append(RegimePoint(
            available_time=available,
            state=state,
            ema50=ema50[idx],
            ema200=ema200[idx],
            ema50_slope=slope,
            range_midpoint=midpoint,
            atr_percentile=atr_pct,
        ))
    return points


def regime_asof(points: Sequence[RegimePoint], at: datetime) -> RegimePoint | None:
    times = [point.available_time for point in points]
    idx = bisect_right(times, at) - 1
    return points[idx] if idx >= 0 else None


def policy_decision(name: str, side: str, state: str) -> tuple[bool, float]:
    """Return (allowed, risk multiplier) for the six frozen candidates."""
    side = side.lower()
    if name == "LONG_CONTROL_ALL_REGIMES":
        return side == "long", 1.0
    if name == "LONG_BULL_TREND_ONLY":
        return side == "long" and state == "bull", 1.0
    if name == "LONG_BULL_OR_NEUTRAL_SOFT_RISK":
        return side == "long", {"bull": 1.0, "neutral": 0.70, "bear": 0.40}.get(state, 0.70)
    if name == "SHORT_CONTROL_ALL_REGIMES":
        return side == "short", 1.0
    if name == "SHORT_BEAR_TREND_ONLY":
        return side == "short" and state == "bear", 1.0
    if name == "SHORT_BEAR_OR_NEUTRAL_SOFT_RISK":
        return side == "short", {"bear": 1.0, "neutral": 0.70, "bull": 0.40}.get(state, 0.70)
    raise ValueError(f"unknown frozen regime policy: {name}")


POLICIES = (
    "LONG_CONTROL_ALL_REGIMES",
    "LONG_BULL_TREND_ONLY",
    "LONG_BULL_OR_NEUTRAL_SOFT_RISK",
    "SHORT_CONTROL_ALL_REGIMES",
    "SHORT_BEAR_TREND_ONLY",
    "SHORT_BEAR_OR_NEUTRAL_SOFT_RISK",
)
