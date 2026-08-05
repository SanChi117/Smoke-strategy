#!/usr/bin/env python3
"""Causal, deterministic Cleanshot/SMC feature formalization.

The module translates selected concepts from the user's manual framework into
explicit closed-candle features. It is a research proxy, not a claim that a
human discretionary process has been reproduced exactly.

Research only. No API keys. No paper/live order execution.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import Iterable

from strategy_lab.closed_context import resample_closed_candles
from strategy_lab.market_data import Candle, group_candles_by_symbol


POLICIES = (
    "SMC_DIRECTION_CONTROL",
    "SMC_RAID_BOS_CHAIN",
    "SMC_POI_VC_CHAIN",
    "SMC_IDM_BOS_CHAIN",
    "SMC_HYBRID_SCORE_7",
    "SMC_SOFT_SCORE",
)


@dataclass(frozen=True)
class SmcFeature:
    symbol: str
    side: str
    entry_time: datetime
    available: bool
    h4_bias: str
    bias_match: bool
    dealing_range_position: float | None
    premium_discount_match: bool
    h4_poi: bool
    h1_liquidity_raid: bool
    m15_bos: bool
    m15_displacement: bool
    m15_imbalance: bool
    m15_idm: bool
    volume_confirmation: bool
    score: int
    state: str


@dataclass
class _SymbolBook:
    m15: list[Candle]
    m15_times: list[datetime]
    atr14: list[float | None]
    volume_sma20: list[float | None]
    h1: list[Candle]
    h1_times: list[datetime]
    h4: list[Candle]
    h4_times: list[datetime]


def _rma(values: list[float], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if length <= 0 or len(values) < length:
        return out
    current = mean(values[:length])
    out[length - 1] = current
    for index in range(length, len(values)):
        current = (current * (length - 1) + values[index]) / length
        out[index] = current
    return out


def _atr(rows: list[Candle], length: int = 14) -> list[float | None]:
    values: list[float] = []
    previous_close: float | None = None
    for candle in rows:
        if previous_close is None:
            tr = candle.high - candle.low
        else:
            tr = max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        values.append(max(0.0, tr))
        previous_close = candle.close
    return _rma(values, length)


def _sma(values: list[float], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if length <= 0:
        return out
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= length:
            running -= values[index - length]
        if index >= length - 1:
            out[index] = running / length
    return out


def _intersects(candle: Candle, low: float, high: float) -> bool:
    return candle.low <= high and candle.high >= low


def _h4_bias(rows: list[Candle], index: int) -> str:
    if index < 11:
        return "missing"
    previous = rows[index - 11 : index - 5]
    recent = rows[index - 5 : index + 1]
    previous_high = max(row.high for row in previous)
    previous_low = min(row.low for row in previous)
    recent_high = max(row.high for row in recent)
    recent_low = min(row.low for row in recent)
    if recent_high > previous_high and recent_low > previous_low:
        return "bull"
    if recent_high < previous_high and recent_low < previous_low:
        return "bear"
    return "neutral"


def _dealing_range_position(rows: list[Candle], index: int, price: float) -> float | None:
    if index < 19:
        return None
    sample = rows[index - 19 : index + 1]
    low = min(row.low for row in sample)
    high = max(row.high for row in sample)
    if high <= low:
        return None
    return max(0.0, min(1.0, (price - low) / (high - low)))


def _recent_h4_poi(rows: list[Candle], index: int, signal: Candle, side: str) -> bool:
    if index < 2:
        return False
    start = max(2, index - 7)
    for current in range(start, index + 1):
        left = rows[current - 2]
        right = rows[current]
        if side == "long" and right.low > left.high:
            if _intersects(signal, left.high, right.low):
                return True
        if side == "short" and right.high < left.low:
            if _intersects(signal, right.high, left.low):
                return True

    # Rejection/origin-block proxy: the opposite candle directly before a
    # directional 4h displacement bar. Only completed 4h candles are inspected.
    for current in range(max(1, index - 7), index + 1):
        origin = rows[current - 1]
        impulse = rows[current]
        full_range = max(1e-12, impulse.high - impulse.low)
        body_ratio = abs(impulse.close - impulse.open) / full_range
        if body_ratio < 0.65:
            continue
        if (
            side == "long"
            and impulse.close > impulse.open
            and origin.close < origin.open
            and _intersects(signal, origin.low, origin.high)
        ):
            return True
        if (
            side == "short"
            and impulse.close < impulse.open
            and origin.close > origin.open
            and _intersects(signal, origin.low, origin.high)
        ):
            return True
    return False


def _recent_h1_raid(rows: list[Candle], index: int, side: str) -> bool:
    if index < 12:
        return False
    for current in range(max(12, index - 3), index + 1):
        prior = rows[current - 12 : current]
        candle = rows[current]
        prior_low = min(row.low for row in prior)
        prior_high = max(row.high for row in prior)
        if side == "long" and candle.low < prior_low and candle.close > prior_low:
            return True
        if side == "short" and candle.high > prior_high and candle.close < prior_high:
            return True
    return False


def _m15_bos(rows: list[Candle], index: int, side: str) -> bool:
    if index < 8:
        return False
    prior = rows[index - 8 : index]
    signal = rows[index]
    if side == "long":
        return signal.close > max(row.high for row in prior)
    return signal.close < min(row.low for row in prior)


def _m15_displacement(
    rows: list[Candle],
    atr_values: list[float | None],
    volume_sma: list[float | None],
    index: int,
    side: str,
) -> bool:
    atr = atr_values[index]
    average_volume = volume_sma[index]
    if atr is None or atr <= 0 or average_volume is None or average_volume <= 0:
        return False
    signal = rows[index]
    full_range = signal.high - signal.low
    if full_range <= 0:
        return False
    body = abs(signal.close - signal.open)
    close_location = (signal.close - signal.low) / full_range
    volume_ok = signal.volume >= average_volume * 1.20
    body_ok = body >= atr * 0.60
    if side == "long":
        return signal.close > signal.open and body_ok and volume_ok and close_location >= 0.75
    return signal.close < signal.open and body_ok and volume_ok and close_location <= 0.25


def _m15_imbalance(rows: list[Candle], index: int, side: str) -> bool:
    if index < 2:
        return False
    left = rows[index - 2]
    signal = rows[index]
    if side == "long":
        return signal.low > left.high
    return signal.high < left.low


def _m15_idm(rows: list[Candle], index: int, side: str) -> bool:
    if index < 5:
        return False
    for current in range(max(5, index - 3), index + 1):
        prior = rows[current - 5 : current]
        candle = rows[current]
        prior_low = min(row.low for row in prior)
        prior_high = max(row.high for row in prior)
        if side == "long" and candle.low < prior_low and candle.close > prior_low:
            return True
        if side == "short" and candle.high > prior_high and candle.close < prior_high:
            return True
    return False


class SmcFeatureEngine:
    """Evaluate SMC features as known immediately before a candidate entry."""

    def __init__(self, candles: Iterable[Candle]):
        self.books: dict[str, _SymbolBook] = {}
        for symbol, rows in group_candles_by_symbol(candles).items():
            ordered = sorted(rows, key=lambda row: row.time)
            h1 = resample_closed_candles(ordered, 1)
            h4 = resample_closed_candles(ordered, 4)
            self.books[symbol] = _SymbolBook(
                m15=ordered,
                m15_times=[row.time for row in ordered],
                atr14=_atr(ordered, 14),
                volume_sma20=_sma([row.volume for row in ordered], 20),
                h1=h1,
                h1_times=[row.time for row in h1],
                h4=h4,
                h4_times=[row.time for row in h4],
            )

    def evaluate(self, symbol: str, entry_time: datetime, side: str) -> SmcFeature:
        normalized_symbol = str(symbol).strip().upper()
        normalized_side = str(side).strip().lower()
        book = self.books.get(normalized_symbol)
        missing = SmcFeature(
            symbol=normalized_symbol,
            side=normalized_side,
            entry_time=entry_time,
            available=False,
            h4_bias="missing",
            bias_match=False,
            dealing_range_position=None,
            premium_discount_match=False,
            h4_poi=False,
            h1_liquidity_raid=False,
            m15_bos=False,
            m15_displacement=False,
            m15_imbalance=False,
            m15_idm=False,
            volume_confirmation=False,
            score=0,
            state="missing",
        )
        if book is None or normalized_side not in {"long", "short"}:
            return missing

        m15_index = bisect_left(book.m15_times, entry_time) - 1
        # A completed HTF candle is represented by the open time of its final
        # 15m source bar and becomes known 15 minutes later.
        htf_cutoff = entry_time - timedelta(minutes=15)
        h1_index = bisect_right(book.h1_times, htf_cutoff) - 1
        h4_index = bisect_right(book.h4_times, htf_cutoff) - 1
        if m15_index < 20 or h1_index < 12 or h4_index < 19:
            return missing

        signal = book.m15[m15_index]
        bias = _h4_bias(book.h4, h4_index)
        bias_match = (normalized_side == "long" and bias == "bull") or (
            normalized_side == "short" and bias == "bear"
        )
        position = _dealing_range_position(book.h4, h4_index, signal.close)
        premium_discount_match = position is not None and (
            (normalized_side == "long" and position <= 0.50)
            or (normalized_side == "short" and position >= 0.50)
        )
        poi = _recent_h4_poi(book.h4, h4_index, signal, normalized_side)
        raid = _recent_h1_raid(book.h1, h1_index, normalized_side)
        bos = _m15_bos(book.m15, m15_index, normalized_side)
        displacement = _m15_displacement(
            book.m15, book.atr14, book.volume_sma20, m15_index, normalized_side
        )
        imbalance = _m15_imbalance(book.m15, m15_index, normalized_side)
        idm = _m15_idm(book.m15, m15_index, normalized_side)
        volume_confirmation = bos and (displacement or imbalance)
        score = (
            2 * int(bias_match)
            + int(premium_discount_match)
            + 2 * int(poi)
            + 2 * int(raid)
            + 2 * int(bos)
            + int(displacement)
            + int(imbalance)
            + int(idm)
        )
        state = "strong" if score >= 8 else "qualified" if score >= 6 else "weak" if score >= 4 else "poor"
        return SmcFeature(
            symbol=normalized_symbol,
            side=normalized_side,
            entry_time=entry_time,
            available=True,
            h4_bias=bias,
            bias_match=bias_match,
            dealing_range_position=round(position, 6) if position is not None else None,
            premium_discount_match=premium_discount_match,
            h4_poi=poi,
            h1_liquidity_raid=raid,
            m15_bos=bos,
            m15_displacement=displacement,
            m15_imbalance=imbalance,
            m15_idm=idm,
            volume_confirmation=volume_confirmation,
            score=score,
            state=state,
        )


def policy_decision(policy: str, feature: SmcFeature) -> tuple[bool, float]:
    if policy not in POLICIES:
        raise ValueError(f"Unknown SMC policy: {policy}")
    if not feature.available:
        return False, 0.0
    if policy == "SMC_DIRECTION_CONTROL":
        return feature.bias_match, 1.0
    if policy == "SMC_RAID_BOS_CHAIN":
        return (
            feature.bias_match
            and feature.premium_discount_match
            and feature.h1_liquidity_raid
            and feature.m15_bos,
            1.0,
        )
    if policy == "SMC_POI_VC_CHAIN":
        return (
            feature.bias_match
            and feature.premium_discount_match
            and feature.h4_poi
            and feature.volume_confirmation,
            1.0,
        )
    if policy == "SMC_IDM_BOS_CHAIN":
        return (
            feature.bias_match
            and feature.premium_discount_match
            and feature.m15_idm
            and feature.m15_bos
            and feature.m15_displacement,
            1.0,
        )
    if policy == "SMC_HYBRID_SCORE_7":
        return (
            feature.bias_match
            and feature.score >= 7
            and (feature.h4_poi or feature.h1_liquidity_raid)
            and feature.volume_confirmation,
            1.0,
        )
    if not feature.bias_match:
        return False, 0.0
    if feature.score >= 8:
        return True, 1.0
    if feature.score >= 6:
        return True, 0.80
    if feature.score >= 4:
        return True, 0.50
    return True, 0.25


def feature_as_dict(feature: SmcFeature) -> dict[str, object]:
    return asdict(feature)
