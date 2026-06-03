#!/usr/bin/env python3
"""Feature builder for candle-based strategy research.

Converts OHLCV candles into compact market features used by setup generation,
universe selection, structure scoring and future self-learning.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Iterable

from strategy_lab.market_data import Candle, group_candles_by_symbol


@dataclass(frozen=True)
class MarketFeature:
    symbol: str
    time: object
    close: float
    volume: float
    trend_context: str
    volatility_regime: str
    structure_type: str
    setup_bias: str
    ema_fast: float
    ema_slow: float
    atr_pct: float
    range_pct: float
    volume_ratio: float
    body_pct: float
    upper_wick_pct: float
    lower_wick_pct: float


def ema(values: list[float], length: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (length + 1.0)
    out = values[0]
    for value in values[1:]:
        out = alpha * value + (1.0 - alpha) * out
    return out


def true_range(current: Candle, previous: Candle | None) -> float:
    if previous is None:
        return current.high - current.low
    return max(current.high - current.low, abs(current.high - previous.close), abs(current.low - previous.close))


def classify_trend(close: float, ema_fast_value: float, ema_slow_value: float) -> str:
    if close > ema_fast_value > ema_slow_value:
        return "trend"
    if close < ema_fast_value < ema_slow_value:
        return "countertrend"
    return "range"


def classify_volatility(atr_pct: float) -> str:
    if atr_pct < 1.2:
        return "low"
    if atr_pct > 2.8:
        return "high"
    return "normal"


def classify_structure(trend_context: str, range_pct: float, volume_ratio: float, body_pct: float) -> str:
    if trend_context == "trend" and volume_ratio >= 1.2 and body_pct >= 0.45:
        return "continuation"
    if trend_context == "countertrend":
        return "countertrend_reaction"
    if range_pct <= 4.0:
        return "range_rotation"
    return "wide_risk_structure"


def classify_setup_bias(trend_context: str, structure_type: str, volume_ratio: float) -> str:
    if structure_type == "continuation" and volume_ratio >= 1.4:
        return "ignition"
    if structure_type == "continuation":
        return "pullback"
    if structure_type == "range_rotation":
        return "range_rotation"
    if trend_context == "countertrend":
        return "countertrend_reaction"
    return "watch"


def build_features(candles: Iterable[Candle], fast_len: int = 20, slow_len: int = 50, atr_len: int = 14, volume_len: int = 20) -> list[MarketFeature]:
    features: list[MarketFeature] = []
    by_symbol = group_candles_by_symbol(candles)
    min_history = max(slow_len, atr_len, volume_len) + 1

    for symbol, rows in by_symbol.items():
        closes: list[float] = []
        trs: list[float] = []
        volumes: list[float] = []
        prev: Candle | None = None
        for candle in rows:
            closes.append(candle.close)
            volumes.append(candle.volume)
            trs.append(true_range(candle, prev))
            prev = candle
            if len(closes) < min_history:
                continue

            recent_closes = closes[-slow_len:]
            fast = ema(closes[-fast_len:], fast_len)
            slow = ema(recent_closes, slow_len)
            atr = mean(trs[-atr_len:])
            atr_pct = atr / candle.close * 100.0 if candle.close > 0 else 0.0
            high_n = max(c.high for c in rows[max(0, rows.index(candle) - slow_len + 1): rows.index(candle) + 1])
            low_n = min(c.low for c in rows[max(0, rows.index(candle) - slow_len + 1): rows.index(candle) + 1])
            range_pct = (high_n - low_n) / candle.close * 100.0 if candle.close > 0 else 0.0
            vol_avg = mean(volumes[-volume_len:]) if volumes[-volume_len:] else 0.0
            volume_ratio = candle.volume / vol_avg if vol_avg > 0 else 0.0
            candle_range = max(candle.high - candle.low, 1e-12)
            body_pct = abs(candle.close - candle.open) / candle_range
            upper_wick_pct = (candle.high - max(candle.open, candle.close)) / candle_range
            lower_wick_pct = (min(candle.open, candle.close) - candle.low) / candle_range

            trend = classify_trend(candle.close, fast, slow)
            vol = classify_volatility(atr_pct)
            structure = classify_structure(trend, range_pct, volume_ratio, body_pct)
            setup_bias = classify_setup_bias(trend, structure, volume_ratio)
            features.append(MarketFeature(
                symbol=symbol,
                time=candle.time,
                close=candle.close,
                volume=candle.volume,
                trend_context=trend,
                volatility_regime=vol,
                structure_type=structure,
                setup_bias=setup_bias,
                ema_fast=round(fast, 8),
                ema_slow=round(slow, 8),
                atr_pct=round(atr_pct, 6),
                range_pct=round(range_pct, 6),
                volume_ratio=round(volume_ratio, 6),
                body_pct=round(body_pct, 6),
                upper_wick_pct=round(upper_wick_pct, 6),
                lower_wick_pct=round(lower_wick_pct, 6),
            ))
    return features


def rows_as_dicts(rows: Iterable[MarketFeature]) -> list[dict]:
    out = []
    for row in rows:
        item = asdict(row)
        item["time"] = item["time"].isoformat(timespec="seconds") if hasattr(item["time"], "isoformat") else str(item["time"])
        out.append(item)
    return out
