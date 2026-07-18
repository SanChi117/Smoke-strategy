#!/usr/bin/env python3
"""Closed H1 volume-confirmation recognition for SMOKE MTF V2."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from strategy_lab.mtf_dealing_range_v2 import ClosedBar, Level, Pivot, confirmed_pivots


@dataclass(frozen=True)
class VolumeConfirmationSignal:
    symbol: str
    side: str
    signal_bar: ClosedBar
    poi: Level
    displacement: bool
    imbalance: bool
    bos: bool
    broken_pivot: Pivot | None
    zone_low: float
    zone_high: float
    strength: float


def _true_range(rows: Sequence[ClosedBar], index: int) -> float:
    bar = rows[index]
    if index == 0:
        return bar.high - bar.low
    previous = rows[index - 1]
    return max(bar.high - bar.low, abs(bar.high - previous.close), abs(bar.low - previous.close))


def _atr(rows: Sequence[ClosedBar], length: int = 14) -> float | None:
    if len(rows) < length:
        return None
    values = [_true_range(rows, index) for index in range(len(rows) - length, len(rows))]
    return sum(values) / length


def _volume_sma(rows: Sequence[ClosedBar], length: int = 20) -> float | None:
    if len(rows) < length:
        return None
    return sum(bar.volume for bar in rows[-length:]) / length


def _touches(bar: ClosedBar, poi: Level) -> bool:
    return bar.low <= poi.high and bar.high >= poi.low


def detect_h1_volume_confirmation(
    bars: Sequence[ClosedBar],
    poi: Level | None,
    side: str,
    timestamp: datetime,
    lookback_bars: int = 3,
) -> VolumeConfirmationSignal | None:
    """Require a closed directional H1 VC after touching the selected HTF POI.

    VC is directional displacement with elevated volume and either a new
    three-candle imbalance or a body-close BOS of a previously confirmed pivot.
    """
    if poi is None:
        return None
    normalized_side = side.lower()
    if normalized_side not in {"long", "short"}:
        raise ValueError("side must be long or short")
    rows = sorted((bar for bar in bars if bar.close_time <= timestamp), key=lambda bar: bar.close_time)
    if len(rows) < 20:
        return None

    start = max(19, len(rows) - lookback_bars)
    for index in range(len(rows) - 1, start - 1, -1):
        signal = rows[index]
        if signal.open_time < poi.confirmed_at:
            continue
        contact = any(_touches(bar, poi) for bar in rows[max(0, index - 2) : index + 1])
        if not contact:
            continue
        atr = _atr(rows[: index + 1])
        average_volume = _volume_sma(rows[: index + 1])
        if atr is None or atr <= 0 or average_volume is None or average_volume <= 0:
            continue
        full_range = max(1e-12, signal.high - signal.low)
        body = abs(signal.close - signal.open)
        close_location = (signal.close - signal.low) / full_range
        directional = signal.close > signal.open if normalized_side == "long" else signal.close < signal.open
        displacement = directional and body >= atr * 0.55 and signal.volume >= average_volume * 1.10 and (
            close_location >= 0.72 if normalized_side == "long" else close_location <= 0.28
        )
        if not displacement:
            continue

        imbalance = False
        zone_low = signal.low
        zone_high = signal.high
        if index >= 2:
            left = rows[index - 2]
            if normalized_side == "long" and signal.low > left.high:
                imbalance = True
                zone_low, zone_high = left.high, signal.low
            if normalized_side == "short" and signal.high < left.low:
                imbalance = True
                zone_low, zone_high = signal.high, left.low

        pivots = confirmed_pivots(rows[:index], 2, 2)
        desired = "high" if normalized_side == "long" else "low"
        candidates = [
            pivot
            for pivot in pivots
            if pivot.kind == desired and pivot.confirmed_at <= signal.open_time
        ]
        broken: Pivot | None = candidates[-1] if candidates else None
        bos = bool(
            broken
            and (
                signal.close > broken.price
                if normalized_side == "long"
                else signal.close < broken.price
            )
        )
        if not imbalance and not bos:
            continue

        strength = min(
            100.0,
            35.0
            + min(25.0, body / atr * 15.0)
            + min(15.0, signal.volume / average_volume * 7.5)
            + (15.0 if imbalance else 0.0)
            + (10.0 if bos else 0.0),
        )
        return VolumeConfirmationSignal(
            symbol=signal.symbol,
            side=normalized_side,
            signal_bar=signal,
            poi=poi,
            displacement=True,
            imbalance=imbalance,
            bos=bos,
            broken_pivot=broken if bos else None,
            zone_low=zone_low,
            zone_high=zone_high,
            strength=round(strength, 4),
        )
    return None
