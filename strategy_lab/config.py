#!/usr/bin/env python3
"""Central configuration profiles for Smoke Strategy Lab.

Research only. No live trading. No API keys.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskProfile:
    name: str
    initial_cash: float
    leverage: float
    base_risk_pct: float
    max_risk_pct: float
    watch_risk_multiplier: float
    take_risk_multiplier: float
    max_positions: int
    max_margin_pct: float
    max_symbol_positions: int
    daily_loss_limit_pct: float
    weekly_loss_limit_pct: float
    max_loss_streak_halt: int
    reinvest: bool
    notes: str


@dataclass(frozen=True)
class PipelineConfig:
    name: str = "SMOKE_PIPELINE_V1"
    start: str = "2025-01-01"
    end: str = "2026-05-31"
    rolling_lookback_days: int = 30
    rolling_rebalance_days: int = 7
    rolling_top_n: int = 5
    require_rolling_top: bool = True
    require_universe_gate: bool = True
    quality_lookback_days: int = 30
    quality_take_threshold: float = 65.0
    quality_watch_threshold: float = 50.0
    structure_lookback_days: int = 30
    structure_take_threshold: float = 64.0
    structure_watch_threshold: float = 52.0
    allowed_symbols: tuple[str, ...] = ()
    blocked_symbols: tuple[str, ...] = ()
    allowed_setup_types: tuple[str, ...] = ()
    blocked_setup_types: tuple[str, ...] = ()
    allowed_trend_contexts: tuple[str, ...] = ()
    blocked_trend_contexts: tuple[str, ...] = ()
    allowed_volatility_regimes: tuple[str, ...] = ()
    blocked_volatility_regimes: tuple[str, ...] = ()
    allowed_liquidity_states: tuple[str, ...] = ()
    blocked_liquidity_states: tuple[str, ...] = ()
    allowed_candle_types: tuple[str, ...] = ()
    blocked_candle_types: tuple[str, ...] = ()
    allowed_direction_contexts: tuple[str, ...] = ()
    blocked_direction_contexts: tuple[str, ...] = ()
    allowed_context_alignments: tuple[str, ...] = ()
    blocked_context_alignments: tuple[str, ...] = ()
    min_volume_ratio: float = 0.0
    fee_rate: float = 0.0010
    slippage_rate: float = 0.0002
    default_profile: str = "growth_100_20x"


RISK_PROFILES: dict[str, RiskProfile] = {
    "research_500": RiskProfile(
        name="research_500",
        initial_cash=500.0,
        leverage=20.0,
        base_risk_pct=0.005,
        max_risk_pct=0.005,
        watch_risk_multiplier=1.0,
        take_risk_multiplier=1.0,
        max_positions=2,
        max_margin_pct=0.20,
        max_symbol_positions=1,
        daily_loss_limit_pct=0.02,
        weekly_loss_limit_pct=0.05,
        max_loss_streak_halt=4,
        reinvest=False,
        notes="Stable research comparison profile. No reinvest.",
    ),
    "growth_100_20x": RiskProfile(
        name="growth_100_20x",
        initial_cash=100.0,
        leverage=20.0,
        base_risk_pct=0.0075,
        max_risk_pct=0.0100,
        watch_risk_multiplier=0.50,
        take_risk_multiplier=1.00,
        max_positions=2,
        max_margin_pct=0.35,
        max_symbol_positions=1,
        daily_loss_limit_pct=0.03,
        weekly_loss_limit_pct=0.08,
        max_loss_streak_halt=3,
        reinvest=False,
        notes=(
            "Small-balance growth profile: $100 balance, 20x leverage, "
            "0.75% base risk and max 1% only for strongest signals. "
            "Designed for growth testing, not conservative capital preservation."
        ),
    ),
}


def get_risk_profile(name: str) -> RiskProfile:
    try:
        return RISK_PROFILES[name]
    except KeyError as exc:
        allowed = ", ".join(sorted(RISK_PROFILES))
        raise ValueError(f"Unknown risk profile: {name}. Allowed: {allowed}") from exc


def default_pipeline_config() -> PipelineConfig:
    return PipelineConfig()
