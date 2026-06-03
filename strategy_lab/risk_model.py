#!/usr/bin/env python3
"""Risk model for candidate setups.

Turns candle-feature candidates into normalized simulated trades with entry,
SL, TP and R-multiple. This is an executable research skeleton, not live logic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Iterable

from strategy_lab.rolling_symbol_strength import Trade
from strategy_lab.setup_generator import CandidateSetup


@dataclass(frozen=True)
class RiskModelConfig:
    base_stop_pct: float = 0.018
    high_vol_stop_pct: float = 0.026
    low_vol_stop_pct: float = 0.014
    trend_rr: float = 1.80
    range_rr: float = 1.25
    countertrend_rr: float = 1.05
    max_holding_hours: int = 8


@dataclass(frozen=True)
class RiskPlan:
    symbol: str
    side: str
    entry_time: object
    exit_time: object
    entry: float
    stop: float
    target: float
    stop_pct: float
    target_rr: float
    setup_type: str
    trend_context: str
    volatility_regime: str
    structure_type: str
    reason: str


def stop_pct_for(candidate: CandidateSetup, cfg: RiskModelConfig) -> float:
    if candidate.volatility_regime == "high":
        return cfg.high_vol_stop_pct
    if candidate.volatility_regime == "low":
        return cfg.low_vol_stop_pct
    return cfg.base_stop_pct


def rr_for(candidate: CandidateSetup, cfg: RiskModelConfig) -> float:
    if candidate.trend_context == "countertrend":
        return cfg.countertrend_rr
    if candidate.structure_type == "range_rotation":
        return cfg.range_rr
    return cfg.trend_rr


def build_risk_plan(candidate: CandidateSetup, cfg: RiskModelConfig | None = None) -> RiskPlan:
    cfg = cfg or RiskModelConfig()
    stop_pct = stop_pct_for(candidate, cfg)
    rr = rr_for(candidate, cfg)
    risk_abs = candidate.entry * stop_pct
    if candidate.side == "long":
        stop = candidate.entry - risk_abs
        target = candidate.entry + risk_abs * rr
    else:
        stop = candidate.entry + risk_abs
        target = candidate.entry - risk_abs * rr
    exit_time = candidate.entry_time + timedelta(hours=cfg.max_holding_hours) if hasattr(candidate.entry_time, "__add__") else candidate.entry_time
    return RiskPlan(
        symbol=candidate.symbol,
        side=candidate.side,
        entry_time=candidate.entry_time,
        exit_time=exit_time,
        entry=round(candidate.entry, 8),
        stop=round(stop, 8),
        target=round(target, 8),
        stop_pct=round(stop_pct, 6),
        target_rr=round(rr, 4),
        setup_type=candidate.setup_type,
        trend_context=candidate.trend_context,
        volatility_regime=candidate.volatility_regime,
        structure_type=candidate.structure_type,
        reason=candidate.reason,
    )


def build_risk_plans(candidates: Iterable[CandidateSetup], cfg: RiskModelConfig | None = None) -> list[RiskPlan]:
    return [build_risk_plan(candidate, cfg) for candidate in candidates]


def risk_plan_to_trade(plan: RiskPlan, result_r: float | None = None) -> Trade:
    r = plan.target_rr if result_r is None else result_r
    risk = abs(plan.entry - plan.stop)
    if plan.side == "long":
        exit_price = plan.entry + risk * r
    else:
        exit_price = plan.entry - risk * r
    return Trade(
        symbol=plan.symbol,
        side=plan.side,
        entry_time=plan.entry_time,
        exit_time=plan.exit_time,
        entry=plan.entry,
        stop=plan.stop,
        exit=round(exit_price, 8),
        r_mult=round(r, 6),
        source="risk_model_skeleton",
        kind=plan.setup_type,
    )


def rows_as_dicts(rows: Iterable[RiskPlan]) -> list[dict]:
    out = []
    for row in rows:
        item = asdict(row)
        item["entry_time"] = item["entry_time"].isoformat(timespec="seconds") if hasattr(item["entry_time"], "isoformat") else str(item["entry_time"])
        item["exit_time"] = item["exit_time"].isoformat(timespec="seconds") if hasattr(item["exit_time"], "isoformat") else str(item["exit_time"])
        out.append(item)
    return out
