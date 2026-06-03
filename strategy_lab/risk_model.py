#!/usr/bin/env python3
"""Risk model for candidate setups.

Turns candle-feature candidates into normalized research trades with entry,
SL, TP and R-multiple. This is an executable research skeleton, not live logic.

The model is setup-aware:
- trend continuation can use wider targets
- range/countertrend targets are compressed
- high volatility widens stops but caps RR unless the setup is breakout/ignition
- weak confidence reduces RR and labels the target policy as defensive
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Iterable

from strategy_lab.rolling_symbol_strength import Trade
from strategy_lab.setup_generator import CandidateSetup


@dataclass(frozen=True)
class RiskModelConfig:
    breakout_stop_pct: float = 0.020
    pullback_stop_pct: float = 0.016
    ignition_stop_pct: float = 0.024
    range_stop_pct: float = 0.014
    liquidity_stop_pct: float = 0.017
    fallback_stop_pct: float = 0.018
    low_vol_multiplier: float = 0.85
    high_vol_multiplier: float = 1.25
    min_stop_pct: float = 0.010
    max_stop_pct: float = 0.035
    breakout_rr: float = 1.70
    pullback_rr: float = 1.60
    ignition_rr: float = 1.90
    range_rr: float = 1.20
    liquidity_rr: float = 1.35
    countertrend_rr: float = 1.05
    weak_confidence_rr_multiplier: float = 0.85
    strong_confidence_rr_bonus: float = 0.15
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
    confidence_hint: float
    target_policy: str
    risk_grade: str
    reason: str


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def base_stop_pct_for(candidate: CandidateSetup, cfg: RiskModelConfig) -> float:
    setup = candidate.setup_type
    if setup == "breakout":
        return cfg.breakout_stop_pct
    if setup == "pullback":
        return cfg.pullback_stop_pct
    if setup == "ignition":
        return cfg.ignition_stop_pct
    if setup == "range_rotation":
        return cfg.range_stop_pct
    if setup == "liquidity_reclaim":
        return cfg.liquidity_stop_pct
    return cfg.fallback_stop_pct


def stop_pct_for(candidate: CandidateSetup, cfg: RiskModelConfig) -> float:
    stop = base_stop_pct_for(candidate, cfg)
    if candidate.volatility_regime == "high":
        stop *= cfg.high_vol_multiplier
    elif candidate.volatility_regime == "low":
        stop *= cfg.low_vol_multiplier
    if candidate.confidence_hint < 55:
        stop *= 0.92
    elif candidate.confidence_hint >= 75:
        stop *= 1.05
    return round(clamp(stop, cfg.min_stop_pct, cfg.max_stop_pct), 6)


def base_rr_for(candidate: CandidateSetup, cfg: RiskModelConfig) -> float:
    setup = candidate.setup_type
    if candidate.trend_context == "countertrend":
        return cfg.countertrend_rr
    if setup == "breakout":
        return cfg.breakout_rr
    if setup == "pullback":
        return cfg.pullback_rr
    if setup == "ignition":
        return cfg.ignition_rr
    if setup == "range_rotation":
        return cfg.range_rr
    if setup == "liquidity_reclaim":
        return cfg.liquidity_rr
    return cfg.range_rr


def rr_for(candidate: CandidateSetup, cfg: RiskModelConfig) -> float:
    rr = base_rr_for(candidate, cfg)
    if candidate.confidence_hint < 55:
        rr *= cfg.weak_confidence_rr_multiplier
    elif candidate.confidence_hint >= 78:
        rr += cfg.strong_confidence_rr_bonus
    if candidate.volatility_regime == "high" and candidate.setup_type not in {"breakout", "ignition"}:
        rr = min(rr, 1.25)
    if candidate.setup_type == "range_rotation":
        rr = min(rr, 1.30)
    if candidate.trend_context == "countertrend":
        rr = min(rr, 1.10)
    return round(clamp(rr, 0.80, 2.20), 4)


def target_policy_for(candidate: CandidateSetup, rr: float) -> str:
    if candidate.trend_context == "countertrend":
        return "compressed_countertrend_target"
    if candidate.setup_type == "range_rotation":
        return "range_mid_or_opposite_boundary"
    if candidate.setup_type in {"breakout", "ignition"} and rr >= 1.70:
        return "allow_wider_trend_target"
    if candidate.confidence_hint < 55:
        return "defensive_target"
    return "normal_target"


def risk_grade_for(candidate: CandidateSetup, stop_pct: float, rr: float) -> str:
    if candidate.confidence_hint >= 78 and rr >= 1.70 and stop_pct <= 0.030:
        return "A"
    if candidate.confidence_hint >= 65 and rr >= 1.35:
        return "B"
    if candidate.confidence_hint >= 50:
        return "C"
    return "D"


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
    target_policy = target_policy_for(candidate, rr)
    risk_grade = risk_grade_for(candidate, stop_pct, rr)
    reason = (
        f"{candidate.reason}|stop_pct={round(stop_pct, 6)}|rr={round(rr, 4)}|"
        f"policy={target_policy}|risk_grade={risk_grade}"
    )
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
        confidence_hint=round(candidate.confidence_hint, 4),
        target_policy=target_policy,
        risk_grade=risk_grade,
        reason=reason,
    )


def build_risk_plans(candidates: Iterable[CandidateSetup], cfg: RiskModelConfig | None = None) -> list[RiskPlan]:
    return [build_risk_plan(candidate, cfg) for candidate in candidates]


def research_result_r(plan: RiskPlan) -> float:
    """Deterministic placeholder outcome for candle-path research artifacts.

    Until a candle-based exit simulator is added, generated_trades.csv must not
    pretend that every candidate always hits TP. This placeholder creates a
    mixed distribution based on risk grade and target policy so downstream
    filters can be exercised without live data or look-ahead exits.
    """
    seed = sum(ord(ch) for ch in f"{plan.symbol}|{plan.side}|{plan.entry_time}|{plan.setup_type}")
    mod = seed % 10
    if plan.risk_grade == "A":
        return plan.target_rr if mod >= 2 else -1.0
    if plan.risk_grade == "B":
        return plan.target_rr if mod >= 3 else -1.0
    if plan.risk_grade == "C":
        return min(plan.target_rr, 1.20) if mod >= 5 else -1.0
    return min(plan.target_rr, 1.0) if mod >= 6 else -1.0


def risk_plan_to_trade(plan: RiskPlan, result_r: float | None = None) -> Trade:
    r = research_result_r(plan) if result_r is None else result_r
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
        source="risk_model_research_skeleton",
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
