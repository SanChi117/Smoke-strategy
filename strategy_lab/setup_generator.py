#!/usr/bin/env python3
"""Setup generator for candle-feature based strategy research.

Converts MarketFeature rows into candidate trade ideas. This is not a final
live-entry engine; it is the executable skeleton where future strategy rules
will be attached.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Iterable

from strategy_lab.feature_builder import MarketFeature


@dataclass(frozen=True)
class CandidateSetup:
    symbol: str
    side: str
    entry_time: object
    entry: float
    setup_type: str
    trend_context: str
    volatility_regime: str
    structure_type: str
    confidence_hint: float
    reason: str


def side_from_feature(feature: MarketFeature) -> str:
    if feature.trend_context == "countertrend":
        return "short"
    return "long"


def setup_confidence(feature: MarketFeature) -> float:
    score = 45.0
    if feature.structure_type == "continuation":
        score += 16.0
    if feature.setup_bias == "ignition":
        score += 10.0
    if feature.setup_bias == "pullback":
        score += 6.0
    if feature.volatility_regime == "normal":
        score += 5.0
    if feature.volatility_regime == "high":
        score -= 6.0
    if feature.volume_ratio >= 1.4:
        score += 6.0
    if feature.body_pct >= 0.45:
        score += 4.0
    if feature.trend_context == "countertrend":
        score -= 10.0
    return max(0.0, min(100.0, score))


def should_emit_candidate(feature: MarketFeature, min_confidence: float = 50.0) -> bool:
    if feature.setup_bias == "watch":
        return False
    if feature.volatility_regime == "high" and feature.structure_type != "continuation":
        return False
    return setup_confidence(feature) >= min_confidence


def generate_candidate_setups(features: Iterable[MarketFeature], min_confidence: float = 50.0, min_spacing_minutes: int = 60) -> list[CandidateSetup]:
    candidates: list[CandidateSetup] = []
    last_time: dict[tuple[str, str], object] = {}
    for feature in sorted(features, key=lambda f: (f.symbol, f.time)):
        side = side_from_feature(feature)
        key = (feature.symbol, side)
        prev = last_time.get(key)
        if prev is not None and hasattr(feature.time, "__sub__"):
            if feature.time - prev < timedelta(minutes=min_spacing_minutes):
                continue
        if not should_emit_candidate(feature, min_confidence=min_confidence):
            continue
        conf = setup_confidence(feature)
        candidates.append(CandidateSetup(
            symbol=feature.symbol,
            side=side,
            entry_time=feature.time,
            entry=feature.close,
            setup_type=feature.setup_bias,
            trend_context=feature.trend_context,
            volatility_regime=feature.volatility_regime,
            structure_type=feature.structure_type,
            confidence_hint=round(conf, 4),
            reason=f"{feature.setup_bias}|{feature.trend_context}|{feature.structure_type}|vol={feature.volatility_regime}|vr={feature.volume_ratio}",
        ))
        last_time[key] = feature.time
    return candidates


def rows_as_dicts(rows: Iterable[CandidateSetup]) -> list[dict]:
    out = []
    for row in rows:
        item = asdict(row)
        item["entry_time"] = item["entry_time"].isoformat(timespec="seconds") if hasattr(item["entry_time"], "isoformat") else str(item["entry_time"])
        out.append(item)
    return out
