#!/usr/bin/env python3
"""Shared schemas for the Smoke Strategy Lab research pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PipelineDecision:
    symbol: str
    side: str
    entry_time: datetime
    allowed: bool
    reason: str
    universe_state: str
    quality_decision: str
    structure_decision: str
    risk_pct: float
    leverage: float
    target_policy: str
    setup_type: str = "unknown"
    trend_context: str = "unknown"
    volatility_regime: str = "unknown"


@dataclass(frozen=True)
class CoinUniverseRow:
    symbol: str
    trades: int
    winrate: float
    avg_r: float
    pf: float
    total_r: float
    score: float
    coin_class: str
    allowed_setups: str
    risk_multiplier: float
    reason: str


@dataclass(frozen=True)
class PipelineSummary:
    profile: str
    initial_cash: float
    leverage: float
    base_risk_pct: float
    max_risk_pct: float
    candidates: int
    allowed_candidates: int
    executed_trades: int
    skipped: int
    skipped_no_risk: int
    skipped_max_positions: int
    skipped_symbol_limit: int
    skipped_cash: int
    skipped_daily_halt: int
    skipped_weekly_halt: int
    final_cash: float
    ret_pct: float
    max_dd_pct: float
    pf: float
    winrate: float
    max_loss_streak: int
    symbols_traded: int
    symbols_positive: int
    total_fees: float
    avg_risk_pct: float
