#!/usr/bin/env python3
"""Feature builder for candle-based strategy research.

Converts OHLCV candles into compact market features used by setup generation,
universe selection, structure scoring and future self-learning.

The goal is not indicator complexity. The goal is a stable research feature set
that can classify trend/range/volatility/volume/structure conditions across a
wide coin universe.
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
    trend_direction: str
    trend_strength: float
    ema_fast_slope_pct: float
    range_position: float
    donchian_high: float
    donchian_low: float
    distance_to_high_pct: float
    distance_to_low_pct: float
    volume_state: str
    candle_signal: str
    liquidity_event: str
    setup_quality: float


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


def clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def classify_volatility(atr_pct: float) -> str:
    if atr_pct < 0.9:
        return "low"
    if atr_pct > 3.2:
        return "high"
    return "normal"


def classify_volume(volume_ratio: float) -> str:
    if volume_ratio >= 1.8:
        return "surge"
    if volume_ratio >= 1.25:
        return "above_average"
    if volume_ratio <= 0.65:
        return "dry"
    return "normal"


def classify_candle(body_pct: float, upper_wick_pct: float, lower_wick_pct: float, close: float, open_price: float) -> str:
    bullish = close >= open_price
    if body_pct >= 0.58 and bullish:
        return "bull_impulse"
    if body_pct >= 0.58 and not bullish:
        return "bear_impulse"
    if lower_wick_pct >= 0.45 and bullish:
        return "bull_rejection"
    if upper_wick_pct >= 0.45 and not bullish:
        return "bear_rejection"
    if body_pct <= 0.22:
        return "indecision"
    return "neutral"


def classify_trend(close: float, ema_fast_value: float, ema_slow_value: float, ema_fast_slope_pct: float, trend_strength: float) -> tuple[str, str]:
    if close > ema_fast_value > ema_slow_value and ema_fast_slope_pct >= 0 and trend_strength >= 0.12:
        return "trend", "up"
    if close < ema_fast_value < ema_slow_value and ema_fast_slope_pct <= 0 and trend_strength >= 0.12:
        return "trend", "down"
    return "range", "neutral"


def classify_liquidity_event(range_position: float, lower_wick_pct: float, upper_wick_pct: float, candle_signal: str) -> str:
    if range_position <= 0.12 and lower_wick_pct >= 0.35 and candle_signal in {"bull_rejection", "bull_impulse"}:
        return "low_sweep_reclaim"
    if range_position >= 0.88 and upper_wick_pct >= 0.35 and candle_signal in {"bear_rejection", "bear_impulse"}:
        return "high_sweep_reject"
    return "none"


def classify_structure(
    trend_context: str,
    trend_direction: str,
    range_pct: float,
    range_position: float,
    volume_state: str,
    candle_signal: str,
    liquidity_event: str,
) -> str:
    if liquidity_event != "none":
        return "liquidity_reclaim"
    if trend_context == "trend" and trend_direction == "up" and range_position >= 0.78 and volume_state in {"above_average", "surge"}:
        return "breakout_continuation"
    if trend_context == "trend" and trend_direction == "down" and range_position <= 0.22 and volume_state in {"above_average", "surge"}:
        return "breakdown_continuation"
    if trend_context == "trend" and 0.35 <= range_position <= 0.68:
        return "trend_pullback"
    if trend_context == "range" and range_pct <= 5.5 and (range_position <= 0.20 or range_position >= 0.80):
        return "range_rotation"
    if candle_signal in {"bull_impulse", "bear_impulse"} and volume_state == "surge":
        return "ignition"
    return "watch_structure"


def classify_setup_bias(structure_type: str, trend_direction: str, candle_signal: str) -> str:
    if structure_type in {"breakout_continuation", "breakdown_continuation"}:
        return "breakout"
    if structure_type == "trend_pullback":
        return "pullback"
    if structure_type == "range_rotation":
        return "range_rotation"
    if structure_type == "liquidity_reclaim":
        return "liquidity_reclaim"
    if structure_type == "ignition" and trend_direction != "neutral":
        return "ignition"
    if candle_signal in {"bull_impulse", "bear_impulse"}:
        return "watch_impulse"
    return "watch"


def feature_quality(
    trend_context: str,
    setup_bias: str,
    volatility_regime: str,
    volume_state: str,
    body_pct: float,
    liquidity_event: str,
    range_position: float,
) -> float:
    score = 45.0
    if setup_bias in {"breakout", "pullback", "ignition"}:
        score += 14.0
    if setup_bias in {"range_rotation", "liquidity_reclaim"}:
        score += 8.0
    if trend_context == "trend":
        score += 7.0
    if volatility_regime == "normal":
        score += 6.0
    if volatility_regime == "high":
        score -= 8.0
    if volume_state == "surge":
        score += 8.0
    elif volume_state == "above_average":
        score += 4.0
    elif volume_state == "dry":
        score -= 8.0
    if body_pct >= 0.50:
        score += 4.0
    if liquidity_event != "none":
        score += 5.0
    if 0.43 <= range_position <= 0.57 and setup_bias != "pullback":
        score -= 6.0
    return round(clamp(score), 4)


def build_features(candles: Iterable[Candle], fast_len: int = 20, slow_len: int = 50, atr_len: int = 14, volume_len: int = 20, range_len: int = 50) -> list[MarketFeature]:
    features: list[MarketFeature] = []
    by_symbol = group_candles_by_symbol(candles)
    min_history = max(slow_len, atr_len, volume_len, range_len) + 2

    for symbol, rows in by_symbol.items():
        closes: list[float] = []
        trs: list[float] = []
        volumes: list[float] = []
        prev: Candle | None = None
        for idx, candle in enumerate(rows):
            closes.append(candle.close)
            volumes.append(candle.volume)
            trs.append(true_range(candle, prev))
            prev = candle
            if len(closes) < min_history:
                continue

            fast = ema(closes[-fast_len:], fast_len)
            slow = ema(closes[-slow_len:], slow_len)
            prev_fast_window = closes[-fast_len - 5:-5]
            prev_fast = ema(prev_fast_window, fast_len) if len(prev_fast_window) >= fast_len else fast
            ema_fast_slope_pct = (fast - prev_fast) / candle.close * 100.0 if candle.close > 0 else 0.0
            trend_strength = abs(fast - slow) / candle.close * 100.0 if candle.close > 0 else 0.0

            atr = mean(trs[-atr_len:])
            atr_pct = atr / candle.close * 100.0 if candle.close > 0 else 0.0
            lookback_rows = rows[max(0, idx - range_len + 1): idx + 1]
            high_n = max(c.high for c in lookback_rows)
            low_n = min(c.low for c in lookback_rows)
            range_width = max(high_n - low_n, 1e-12)
            range_pct = range_width / candle.close * 100.0 if candle.close > 0 else 0.0
            range_position = (candle.close - low_n) / range_width
            distance_to_high_pct = (high_n - candle.close) / candle.close * 100.0 if candle.close > 0 else 0.0
            distance_to_low_pct = (candle.close - low_n) / candle.close * 100.0 if candle.close > 0 else 0.0

            vol_avg = mean(volumes[-volume_len:]) if volumes[-volume_len:] else 0.0
            volume_ratio = candle.volume / vol_avg if vol_avg > 0 else 0.0
            volume_state = classify_volume(volume_ratio)
            candle_range = max(candle.high - candle.low, 1e-12)
            body_pct = abs(candle.close - candle.open) / candle_range
            upper_wick_pct = (candle.high - max(candle.open, candle.close)) / candle_range
            lower_wick_pct = (min(candle.open, candle.close) - candle.low) / candle_range
            candle_signal = classify_candle(body_pct, upper_wick_pct, lower_wick_pct, candle.close, candle.open)

            trend, trend_direction = classify_trend(candle.close, fast, slow, ema_fast_slope_pct, trend_strength)
            vol = classify_volatility(atr_pct)
            liquidity_event = classify_liquidity_event(range_position, lower_wick_pct, upper_wick_pct, candle_signal)
            structure = classify_structure(trend, trend_direction, range_pct, range_position, volume_state, candle_signal, liquidity_event)
            setup_bias = classify_setup_bias(structure, trend_direction, candle_signal)
            quality = feature_quality(trend, setup_bias, vol, volume_state, body_pct, liquidity_event, range_position)

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
                trend_direction=trend_direction,
                trend_strength=round(trend_strength, 6),
                ema_fast_slope_pct=round(ema_fast_slope_pct, 6),
                range_position=round(range_position, 6),
                donchian_high=round(high_n, 8),
                donchian_low=round(low_n, 8),
                distance_to_high_pct=round(distance_to_high_pct, 6),
                distance_to_low_pct=round(distance_to_low_pct, 6),
                volume_state=volume_state,
                candle_signal=candle_signal,
                liquidity_event=liquidity_event,
                setup_quality=quality,
            ))
    return features


def rows_as_dicts(rows: Iterable[MarketFeature]) -> list[dict]:
    out = []
    for row in rows:
        item = asdict(row)
        item["time"] = item["time"].isoformat(timespec="seconds") if hasattr(item["time"], "isoformat") else str(item["time"])
        out.append(item)
    return out
