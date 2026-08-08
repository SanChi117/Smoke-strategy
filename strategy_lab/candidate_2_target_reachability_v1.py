#!/usr/bin/env python3
"""SMOKE CORE Candidate 2 C2-P4 causal attainable-target engine."""
from __future__ import annotations

from datetime import datetime
from statistics import mean
from typing import Sequence

from strategy_lab.market_data import Candle
from strategy_lab.candidate_2_hypothesis_contract_v1 import HorizonClass, TargetReachability

ENGINE_ID = "SMOKE_CORE_CANDIDATE_2_TARGET_REACHABILITY_V1"
MAX_MICRO_ATR = 2.0
MAX_INTRADAY_ATR = 4.5
MAX_SWING_ATR = 7.0
MAX_OBSTACLE_COUNT = 2
MIN_NET_RR = 1.35
TOTAL_COST_PCT = 0.15


def _atr(rows: Sequence[Candle], length: int = 14) -> float:
    selected = rows[-max(2, length + 1):]
    trs = []
    for prev, cur in zip(selected[:-1], selected[1:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return mean(trs) if trs else max(1e-12, rows[-1].high - rows[-1].low)


def evaluate_target(
    candles: Sequence[Candle],
    *,
    scenario_id: str,
    direction: str,
    evaluated_at: datetime,
    entry_price: float,
    stop_price: float,
    target_id: str,
    target_price: float,
    structural_reason: str,
) -> TargetReachability:
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    rows = sorted((c for c in candles if c.time <= evaluated_at), key=lambda c: c.time)
    if len(rows) < 20:
        raise ValueError("target engine requires at least 20 causal candles")
    if direction == "LONG" and not stop_price < entry_price < target_price:
        raise ValueError("invalid LONG target geometry")
    if direction == "SHORT" and not target_price < entry_price < stop_price:
        raise ValueError("invalid SHORT target geometry")
    atr = _atr(rows)
    distance = abs(target_price - entry_price)
    vol_distance = distance / max(atr, 1e-12)
    if vol_distance <= MAX_MICRO_ATR:
        horizon = HorizonClass.MICRO
    elif vol_distance <= MAX_INTRADAY_ATR:
        horizon = HorizonClass.INTRADAY
    elif vol_distance <= MAX_SWING_ATR:
        horizon = HorizonClass.SWING
    else:
        horizon = HorizonClass.UNRESOLVED

    lookback = rows[-36:]
    obstacles: list[str] = []
    tolerance = atr * 0.20
    for idx, row in enumerate(lookback[:-2]):
        if direction == "LONG":
            candidate = row.high
            between = entry_price + tolerance < candidate < target_price - tolerance
            local_extreme = row.high >= max(c.high for c in lookback[max(0, idx-2):min(len(lookback), idx+3)])
        else:
            candidate = row.low
            between = target_price + tolerance < candidate < entry_price - tolerance
            local_extreme = row.low <= min(c.low for c in lookback[max(0, idx-2):min(len(lookback), idx+3)])
        if between and local_extreme:
            obstacles.append(f"obstacle:{row.time.isoformat()}")
    obstacles = list(dict.fromkeys(obstacles))

    target_move_pct = abs(target_price - entry_price) / entry_price * 100.0
    stop_move_pct = abs(entry_price - stop_price) / entry_price * 100.0
    net_reward = target_move_pct - TOTAL_COST_PCT
    net_loss = stop_move_pct + TOTAL_COST_PCT
    net_rr = net_reward / max(net_loss, 1e-12)

    rejection: list[str] = []
    if horizon == HorizonClass.UNRESOLVED:
        rejection.append("target_outside_causal_volatility_horizon")
    if len(obstacles) > MAX_OBSTACLE_COUNT:
        rejection.append("too_many_intermediate_obstacles")
    if net_rr < MIN_NET_RR:
        rejection.append("cost_adjusted_rr_below_minimum")
    reachable = not rejection
    evidence_ids = (
        f"{ENGINE_ID}:evaluated:{evaluated_at.isoformat()}",
        f"{ENGINE_ID}:atr:{round(atr,10)}",
        f"{ENGINE_ID}:netrr:{round(net_rr,10)}",
    )
    return TargetReachability(
        scenario_id=scenario_id,
        evaluated_at=evaluated_at,
        target_id=target_id,
        target_price=float(target_price),
        structural_reason=structural_reason,
        path_obstacle_ids=tuple(obstacles),
        volatility_distance=round(vol_distance, 10),
        horizon_class=horizon,
        reachable=reachable,
        rejection_reasons=tuple(rejection),
        evidence_ids=evidence_ids,
        causal_window_start=lookback[0].time,
        causal_window_end=lookback[-1].time,
    )
