#!/usr/bin/env python3
"""Closed 15m retest of a newly created H1 VC zone for SMOKE MTF V2."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from strategy_lab.mtf_dealing_range_v2 import ClosedBar
from strategy_lab.mtf_volume_confirmation_v2 import VolumeConfirmationSignal


@dataclass(frozen=True)
class VcZoneTestSignal:
    symbol: str
    side: str
    vc: VolumeConfirmationSignal
    test_bar: ClosedBar
    zone_low: float
    zone_high: float
    rejection_strength: float


def detect_15m_vc_zone_test(
    bars: Sequence[ClosedBar],
    vc: VolumeConfirmationSignal | None,
    side: str,
    timestamp: datetime,
    lookback_bars: int = 16,
) -> VcZoneTestSignal | None:
    """Require a later closed 15m touch and directional rejection of the H1 VC zone.

    The test bar must open after the H1 VC has closed. This prevents a 15m bar
    embedded inside the still-forming H1 confirmation candle from being treated
    as a later retest.
    """
    if vc is None:
        return None
    normalized_side = side.lower()
    if normalized_side not in {"long", "short"}:
        raise ValueError("side must be long or short")
    rows = sorted(
        (
            bar
            for bar in bars
            if bar.symbol == vc.symbol
            and bar.timeframe == "15m"
            and bar.close_time <= timestamp
            and bar.open_time >= vc.signal_bar.close_time
        ),
        key=lambda bar: bar.close_time,
    )
    for bar in reversed(rows[-lookback_bars:]):
        touched = bar.low <= vc.zone_high and bar.high >= vc.zone_low
        if not touched:
            continue
        full_range = max(1e-12, bar.high - bar.low)
        close_location = (bar.close - bar.low) / full_range
        midpoint = (vc.zone_low + vc.zone_high) / 2.0
        if normalized_side == "long":
            valid = bar.close > bar.open and bar.close >= midpoint and close_location >= 0.60
            distance = max(0.0, bar.close - midpoint) / full_range
        else:
            valid = bar.close < bar.open and bar.close <= midpoint and close_location <= 0.40
            distance = max(0.0, midpoint - bar.close) / full_range
        if not valid:
            continue
        strength = min(100.0, vc.strength * 0.65 + close_location * 20.0 if normalized_side == "long" else vc.strength * 0.65 + (1.0 - close_location) * 20.0)
        strength = min(100.0, strength + min(15.0, distance * 30.0))
        return VcZoneTestSignal(
            symbol=bar.symbol,
            side=normalized_side,
            vc=vc,
            test_bar=bar,
            zone_low=vc.zone_low,
            zone_high=vc.zone_high,
            rejection_strength=round(strength, 4),
        )
    return None
