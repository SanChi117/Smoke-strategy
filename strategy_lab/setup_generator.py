#!/usr/bin/env python3
"""Setup generator for candle-feature based strategy research.

Converts MarketFeature rows into candidate trade ideas.

MTF separation:
- trend_context / trend_direction / volatility_regime come from 1D/4H market context;
- setup_type, entry candle, entry liquidity and entry volume come from the entry timeframe.

The pullback-resumption setups are causal two-bar triggers. They do not enter merely
because price sits in the middle of a range: a prior retracement must be followed by
an observable move back in the trend direction.
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


def _get(feature: MarketFeature, name: str, default):
    return getattr(feature, name, default)


def setup_for_feature(feature: MarketFeature, previous: MarketFeature | None = None) -> tuple[str, str]:
    """Return derived setup type and transparent trigger description.

    Only short resumption is enabled in this research iteration because prior strict
    fold diagnostics did not support the long branch. Long behavior remains unchanged
    for all legacy setup types.
    """

    setup = feature.setup_bias
    if setup != "pullback" or previous is None or previous.symbol != feature.symbol:
        return setup, "legacy"

    market_direction = str(_get(feature, "trend_direction", "neutral"))
    entry_direction = str(_get(feature, "entry_trend_direction", market_direction))
    if market_direction != "down" or entry_direction != "down":
        return setup, "legacy"

    current_position = float(_get(feature, "range_position", 0.5))
    previous_position = float(_get(previous, "range_position", 0.5))
    current_candle = str(_get(feature, "candle_signal", "neutral"))
    previous_candle = str(_get(previous, "candle_signal", "neutral"))
    current_volume = float(_get(feature, "volume_ratio", 0.0))

    # A causal resumption needs an already observed retracement and an already closed
    # candle moving back down. No future candle or future outcome is referenced.
    retracement_present = previous_position >= 0.50
    moved_down = feature.close < previous.close and current_position <= previous_position - 0.025
    valid_trigger_candle = current_candle in {"bear_impulse", "bear_rejection", "neutral", "indecision"}
    enough_participation = current_volume >= 0.65
    if not (retracement_present and moved_down and valid_trigger_candle and enough_participation):
        return setup, "legacy"

    strict_retracement_candle = previous_candle in {"bull_impulse", "bull_rejection", "neutral", "indecision"}
    strict_trigger = (
        previous_position >= 0.52
        and current_position <= 0.52
        and current_candle in {"bear_impulse", "bear_rejection"}
        and strict_retracement_candle
        and current_volume >= 0.80
    )
    if strict_trigger:
        return "pullback_resumption_strict", "two_bar_strict"
    return "pullback_resumption", "two_bar_balanced"


def side_from_feature(feature: MarketFeature, setup_override: str | None = None) -> str:
    setup = setup_override or feature.setup_bias
    market_direction = _get(feature, "trend_direction", "neutral")
    entry_direction = _get(feature, "entry_trend_direction", market_direction)
    range_position = float(_get(feature, "range_position", 0.5))
    liquidity_event = _get(feature, "liquidity_event", "none")
    candle_signal = _get(feature, "candle_signal", "neutral")

    if setup in {"breakout", "pullback", "pullback_resumption", "pullback_resumption_strict", "ignition"}:
        if market_direction == "down" or entry_direction == "down" or feature.structure_type == "breakdown_continuation":
            return "short"
        return "long"
    if setup == "range_rotation":
        return "long" if range_position <= 0.25 else "short"
    if setup == "liquidity_reclaim":
        if liquidity_event == "low_sweep_reclaim" or candle_signal.startswith("bull"):
            return "long"
        return "short"
    if candle_signal.startswith("bear"):
        return "short"
    return "long"


def setup_confidence(feature: MarketFeature, setup_override: str | None = None) -> float:
    setup = setup_override or feature.setup_bias
    market_direction = _get(feature, "trend_direction", "neutral")
    entry_direction = _get(feature, "entry_trend_direction", market_direction)
    volume_state = _get(feature, "volume_state", "normal")
    candle_signal = _get(feature, "candle_signal", "neutral")
    liquidity_event = _get(feature, "liquidity_event", "none")
    range_position = float(_get(feature, "range_position", 0.5))
    setup_quality = float(_get(feature, "setup_quality", 50.0))
    alignment = _get(feature, "context_alignment", "")

    score = setup_quality
    if setup == "breakout":
        score += 6.0
    elif setup == "pullback":
        score += 5.0
    elif setup == "pullback_resumption":
        score += 7.0
    elif setup == "pullback_resumption_strict":
        score += 9.0
    elif setup == "ignition":
        score += 4.0
    elif setup == "liquidity_reclaim":
        score += 4.0
    elif setup == "range_rotation":
        score += 1.0
    elif setup.startswith("watch"):
        score -= 12.0

    if feature.volatility_regime == "normal":
        score += 4.0
    elif feature.volatility_regime == "high" and setup not in {"breakout", "ignition", "liquidity_reclaim"}:
        score -= 10.0
    elif feature.volatility_regime == "low" and setup == "breakout":
        score -= 4.0

    if volume_state == "surge":
        score += 2.0
    elif volume_state == "above_average":
        score += 3.0
    elif volume_state == "dry":
        score -= 10.0

    directional_setups = {"breakout", "pullback", "pullback_resumption", "pullback_resumption_strict", "ignition"}
    if setup in directional_setups and market_direction == "neutral" and entry_direction == "neutral":
        score -= 10.0
    if alignment == "conflict":
        score -= 8.0
    elif alignment == "aligned":
        score += 4.0
    if setup == "range_rotation" and not (range_position <= 0.25 or range_position >= 0.75):
        score -= 12.0
    if liquidity_event != "none":
        score += 5.0
    if candle_signal in {"bull_rejection", "bear_rejection"}:
        score += 3.0
    elif candle_signal in {"bull_impulse", "bear_impulse"} and volume_state == "surge":
        score -= 2.0

    return max(0.0, min(100.0, score))


def should_emit_candidate(feature: MarketFeature, min_confidence: float = 50.0, setup_override: str | None = None) -> bool:
    setup = setup_override or feature.setup_bias
    market_direction = _get(feature, "trend_direction", "neutral")
    entry_direction = _get(feature, "entry_trend_direction", market_direction)
    alignment = _get(feature, "context_alignment", "")

    if setup == "watch":
        return False
    if setup == "watch_impulse" and setup_confidence(feature, setup) < max(70.0, min_confidence):
        return False
    if feature.volatility_regime == "high" and setup not in {"breakout", "ignition", "liquidity_reclaim"}:
        return False
    if _get(feature, "volume_state", "normal") == "dry":
        return False
    if alignment == "conflict" and setup in {"pullback", "pullback_resumption", "pullback_resumption_strict", "ignition"}:
        return False
    if setup in {"pullback", "pullback_resumption", "pullback_resumption_strict", "breakout", "ignition"} and market_direction == "neutral" and entry_direction == "neutral":
        return False
    return setup_confidence(feature, setup) >= min_confidence


def generate_candidate_setups(features: Iterable[MarketFeature], min_confidence: float = 50.0, min_spacing_minutes: int = 15) -> list[CandidateSetup]:
    candidates: list[CandidateSetup] = []
    last_time: dict[tuple[str, str, str], object] = {}
    previous_by_symbol: dict[str, MarketFeature] = {}

    for feature in sorted(features, key=lambda f: (f.symbol, f.time)):
        previous = previous_by_symbol.get(feature.symbol)
        setup, trigger = setup_for_feature(feature, previous)
        side = side_from_feature(feature, setup)
        key = (feature.symbol, side, setup)
        prev_emitted = last_time.get(key)
        previous_by_symbol[feature.symbol] = feature

        if prev_emitted is not None and hasattr(feature.time, "__sub__"):
            if feature.time - prev_emitted < timedelta(minutes=min_spacing_minutes):
                continue
        if not should_emit_candidate(feature, min_confidence=min_confidence, setup_override=setup):
            continue

        conf = setup_confidence(feature, setup)
        previous_position = float(_get(previous, "range_position", 0.5)) if previous is not None else 0.5
        previous_candle = str(_get(previous, "candle_signal", "none")) if previous is not None else "none"
        reason = (
            f"setup={setup}|trigger={trigger}|side={side}|"
            f"trend={feature.trend_context}|dir={_get(feature, 'trend_direction', 'neutral')}|"
            f"structure={feature.structure_type}|vol={feature.volatility_regime}|"
            f"entry_trend={_get(feature, 'entry_trend_context', '')}|entry_dir={_get(feature, 'entry_trend_direction', '')}|"
            f"entry_vol={_get(feature, 'entry_volatility_regime', '')}|"
            f"vr={feature.volume_ratio}|vol_state={_get(feature, 'volume_state', 'normal')}|"
            f"candle={_get(feature, 'candle_signal', 'neutral')}|prev_candle={previous_candle}|"
            f"liq={_get(feature, 'liquidity_event', 'none')}|"
            f"pos={_get(feature, 'range_position', 0.5)}|prev_pos={round(previous_position, 6)}|"
            f"quality={_get(feature, 'setup_quality', 0.0)}|"
            f"ctx4h_trend={_get(feature, 'context_4h_trend_context', '')}|ctx4h_dir={_get(feature, 'context_4h_trend_direction', '')}|"
            f"ctx4h_vol={_get(feature, 'context_4h_volatility_regime', '')}|ctx4h_vol_state={_get(feature, 'context_4h_volume_state', '')}|"
            f"ctx1d_trend={_get(feature, 'context_1d_trend_context', '')}|ctx1d_dir={_get(feature, 'context_1d_trend_direction', '')}|"
            f"ctx1d_vol={_get(feature, 'context_1d_volatility_regime', '')}|ctx1d_vol_state={_get(feature, 'context_1d_volume_state', '')}|"
            f"ctx_align={_get(feature, 'context_alignment', '')}"
        )
        candidates.append(CandidateSetup(
            symbol=feature.symbol,
            side=side,
            entry_time=feature.time,
            entry=feature.close,
            setup_type=setup,
            trend_context=feature.trend_context,
            volatility_regime=feature.volatility_regime,
            structure_type=feature.structure_type,
            confidence_hint=round(conf, 4),
            reason=reason,
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
