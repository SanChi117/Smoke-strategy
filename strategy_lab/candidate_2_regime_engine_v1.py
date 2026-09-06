#!/usr/bin/env python3
"""SMOKE CORE Candidate 2 C2-P2 deterministic causal regime engine.

The classifier uses only candles with time <= evaluated_at. Thresholds are
structural research constants fixed before any Candidate 2 profitability run.
"""
from __future__ import annotations

from datetime import datetime
from math import sqrt
from statistics import mean, pstdev
from typing import Sequence

from strategy_lab.market_data import Candle
from strategy_lab.candidate_2_hypothesis_contract_v1 import RegimeEvidence, RegimeState

ENGINE_ID = "SMOKE_CORE_CANDIDATE_2_REGIME_ENGINE_V1"
LOOKBACK = 48
FAST = 12
SLOW = 36
TREND_ALIGNMENT_MIN = 0.30
EFFICIENCY_TREND_MIN = 0.34
EFFICIENCY_RANGE_MAX = 0.20
EXPANSION_VOL_RATIO = 1.18
TRANSITION_VOL_RATIO = 1.45
PULLBACK_DEPTH_MIN = 0.18
PULLBACK_DEPTH_MAX = 0.62


def _clip(value: float) -> float:
    return max(-1.0, min(1.0, float(value)))


def _visible(candles: Sequence[Candle], evaluated_at: datetime) -> list[Candle]:
    rows = [c for c in candles if c.time <= evaluated_at]
    rows.sort(key=lambda c: c.time)
    if len(rows) < LOOKBACK:
        raise ValueError(f"regime engine requires at least {LOOKBACK} causal candles")
    return rows[-LOOKBACK:]


def _atr(rows: Sequence[Candle], length: int = 14) -> float:
    selected = rows[-max(2, length + 1):]
    trs: list[float] = []
    for prev, cur in zip(selected[:-1], selected[1:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return mean(trs) if trs else max(1e-12, rows[-1].high - rows[-1].low)


def _efficiency(rows: Sequence[Candle]) -> float:
    net = rows[-1].close - rows[0].close
    travel = sum(abs(b.close - a.close) for a, b in zip(rows[:-1], rows[1:]))
    return 0.0 if travel <= 0 else _clip(net / travel)


def _slope_norm(rows: Sequence[Candle], atr: float) -> float:
    n = len(rows)
    xs = list(range(n))
    xbar = (n - 1) / 2.0
    ybar = mean(c.close for c in rows)
    denom = sum((x - xbar) ** 2 for x in xs)
    slope = sum((x - xbar) * (c.close - ybar) for x, c in zip(xs, rows)) / max(denom, 1e-12)
    return _clip(slope * n / max(atr, 1e-12) / 4.0)


def _overlap_score(rows: Sequence[Candle]) -> float:
    overlaps = []
    for a, b in zip(rows[:-1], rows[1:]):
        inter = max(0.0, min(a.high, b.high) - max(a.low, b.low))
        union = max(a.high, b.high) - min(a.low, b.low)
        overlaps.append(inter / union if union > 0 else 1.0)
    return _clip(1.0 - 2.0 * (mean(overlaps) if overlaps else 1.0))


def _vol_ratio(rows: Sequence[Candle]) -> float:
    returns = [(b.close / a.close - 1.0) for a, b in zip(rows[:-1], rows[1:]) if a.close > 0]
    if len(returns) < 20:
        return 1.0
    recent = returns[-12:]
    prior = returns[:-12]
    recent_sd = pstdev(recent) if len(recent) > 1 else 0.0
    prior_sd = pstdev(prior) if len(prior) > 1 else 0.0
    return recent_sd / max(prior_sd, 1e-12)


def _liquidity_location(rows: Sequence[Candle]) -> float:
    hi = max(c.high for c in rows)
    lo = min(c.low for c in rows)
    if hi <= lo:
        return 0.0
    pos = (rows[-1].close - lo) / (hi - lo)
    return _clip((pos - 0.5) * 2.0)


def classify_regime(candles: Sequence[Candle], evaluated_at: datetime) -> RegimeEvidence:
    rows = _visible(candles, evaluated_at)
    atr = _atr(rows)
    fast = rows[-FAST:]
    slow = rows[-SLOW:]
    fast_eff = _efficiency(fast)
    slow_eff = _efficiency(slow)
    fast_slope = _slope_norm(fast, atr)
    slow_slope = _slope_norm(slow, atr)
    alignment = _clip((fast_slope + slow_slope) / 2.0)
    persistence = _clip((fast_eff + slow_eff) / 2.0)
    efficiency = _clip(slow_eff)
    overlap = _overlap_score(rows[-24:])
    displacement = _clip((rows[-1].close - rows[-6].close) / max(atr * 2.5, 1e-12))
    location = _liquidity_location(rows)
    vol_ratio = _vol_ratio(rows)
    vol_state = _clip((vol_ratio - 1.0) / 0.75)
    compression_expansion = _clip((vol_ratio - 1.0) / 0.45)

    recent_high = max(c.high for c in rows[-18:-3])
    recent_low = min(c.low for c in rows[-18:-3])
    span = max(recent_high - recent_low, 1e-12)
    last = rows[-1].close
    if slow_slope >= TREND_ALIGNMENT_MIN:
        pullback_depth = max(0.0, (recent_high - last) / span)
    elif slow_slope <= -TREND_ALIGNMENT_MIN:
        pullback_depth = max(0.0, (last - recent_low) / span)
    else:
        pullback_depth = 0.0

    if vol_ratio >= TRANSITION_VOL_RATIO and abs(fast_eff) < EFFICIENCY_TREND_MIN:
        regime = RegimeState.VOLATILITY_TRANSITION
    elif alignment >= TREND_ALIGNMENT_MIN and efficiency >= EFFICIENCY_TREND_MIN:
        regime = RegimeState.TREND_EXPANSION_UP
    elif alignment <= -TREND_ALIGNMENT_MIN and efficiency <= -EFFICIENCY_TREND_MIN:
        regime = RegimeState.TREND_EXPANSION_DOWN
    elif slow_slope >= TREND_ALIGNMENT_MIN and PULLBACK_DEPTH_MIN <= pullback_depth <= PULLBACK_DEPTH_MAX:
        regime = RegimeState.TREND_PULLBACK_UP
    elif slow_slope <= -TREND_ALIGNMENT_MIN and PULLBACK_DEPTH_MIN <= pullback_depth <= PULLBACK_DEPTH_MAX:
        regime = RegimeState.TREND_PULLBACK_DOWN
    elif abs(efficiency) <= EFFICIENCY_RANGE_MAX and overlap < 0.0 and vol_ratio < TRANSITION_VOL_RATIO:
        regime = RegimeState.BALANCED_RANGE
    else:
        regime = RegimeState.DISORDERED

    ids = (
        f"{ENGINE_ID}:lookback:{LOOKBACK}",
        f"bar:{rows[0].time.isoformat()}",
        f"bar:{rows[-1].time.isoformat()}",
    )
    return RegimeEvidence(
        evaluated_at=evaluated_at,
        regime=regime,
        directional_structure_alignment=round(alignment, 10),
        structure_persistence=round(persistence, 10),
        realized_volatility_state=round(vol_state, 10),
        directional_efficiency=round(efficiency, 10),
        displacement_persistence=round(displacement, 10),
        liquidity_location_context=round(location, 10),
        compression_expansion_state=round(compression_expansion, 10),
        evidence_ids=ids,
        causal_window_start=rows[0].time,
        causal_window_end=rows[-1].time,
    )
