#!/usr/bin/env python3
"""Compatibility mappings for pullback-resumption research setups.

The new setup names need their own adaptive-history keys, but their initial stop,
target and deterministic quality priors must remain identical to the established
pullback model. This prevents a renamed setup from receiving an accidental fallback
risk model or an artificial score bonus.
"""

from __future__ import annotations

from dataclasses import replace

from strategy_lab import risk_model as risk
from strategy_lab import trade_quality_score as quality


RESUMPTION_SETUPS = {"pullback_resumption", "pullback_resumption_strict"}

_ORIGINAL_BASE_STOP = risk.base_stop_pct_for
_ORIGINAL_BASE_RR = risk.base_rr_for
_ORIGINAL_QUALITY_TARGET = quality.target_score
_ORIGINAL_QUALITY_ENTRY = quality.entry_score


def base_stop_pct_for(candidate, cfg):
    if str(candidate.setup_type).strip().lower() in RESUMPTION_SETUPS:
        return cfg.pullback_stop_pct
    return _ORIGINAL_BASE_STOP(candidate, cfg)


def base_rr_for(candidate, cfg):
    if str(candidate.setup_type).strip().lower() in RESUMPTION_SETUPS:
        return cfg.pullback_rr
    return _ORIGINAL_BASE_RR(candidate, cfg)


def target_score(trade, stop_risk_pct: float) -> float:
    if str(trade.setup_type).strip().lower() in RESUMPTION_SETUPS:
        return _ORIGINAL_QUALITY_TARGET(replace(trade, setup_type="pullback"), stop_risk_pct)
    return _ORIGINAL_QUALITY_TARGET(trade, stop_risk_pct)


def entry_score(setup: str, stop_risk_pct: float) -> float:
    if str(setup).strip().lower() in RESUMPTION_SETUPS:
        return _ORIGINAL_QUALITY_ENTRY("pullback", stop_risk_pct)
    return _ORIGINAL_QUALITY_ENTRY(setup, stop_risk_pct)


def apply_resumption_compatibility() -> None:
    risk.base_stop_pct_for = base_stop_pct_for
    risk.base_rr_for = base_rr_for
    quality.target_score = target_score
    quality.entry_score = entry_score
