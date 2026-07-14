#!/usr/bin/env python3
"""Layered decision engine for the validated tagged MTF paper baseline.

This module is the single source of truth for paper decisions. It mirrors the
current research baseline ``TAGGED_MTF_NO_DIRECTION_BLOCK_V1`` and records a
PASS/WATCH/BLOCK result for every decision layer.

Paper/research only. No exchange orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable

from strategy_lab.structure_learning import (
    StructureLearningConfig,
    TradeRow as StructureTradeRow,
    score_structure_trades,
)
from strategy_lab.trade_quality_score import (
    QualityConfig,
    TradeRow as QualityTradeRow,
    score_trades as score_quality_trades,
)


BASELINE_NAME = "TAGGED_MTF_NO_DIRECTION_BLOCK_V1"


@dataclass(frozen=True)
class DecisionEngineConfig:
    min_confidence: float = 43.0
    quality_take_threshold: float = 66.0
    quality_watch_threshold: float = 54.0
    structure_take_threshold: float = 64.0
    structure_watch_threshold: float = 54.0
    min_volume_ratio: float = 0.70
    allowed_setup_types: tuple[str, ...] = ("pullback", "ignition")
    allowed_direction_contexts: tuple[str, ...] = ("down",)
    blocked_setup_types: tuple[str, ...] = ("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim")
    blocked_volatility_regimes: tuple[str, ...] = ("high",)
    blocked_liquidity_states: tuple[str, ...] = ("high_sweep_reject",)
    blocked_candle_types: tuple[str, ...] = ("bear_rejection",)
    min_target_rr: float = 0.80
    max_open_per_symbol: int = 1
    cold_start_policy: str = "block"


@dataclass(frozen=True)
class HistoricalTrade:
    symbol: str
    side: str
    entry_time: datetime
    exit_time: datetime
    entry: float
    stop: float
    exit: float
    r_mult: float
    setup_type: str
    trend_context: str
    volatility_regime: str
    structure_type: str
    kind: str = ""
    source: str = "paper_closed"


@dataclass(frozen=True)
class LayerResult:
    layer: str
    status: str
    reason: str
    value: Any = None


@dataclass(frozen=True)
class DecisionResult:
    baseline: str
    symbol: str
    side: str
    entry_time: str
    final_status: str
    ready: bool
    quality_decision: str
    structure_decision: str
    layers: tuple[LayerResult, ...]

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["layers"] = [asdict(layer) for layer in self.layers]
        return data


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def reason_value(reason: Any, key: str) -> str:
    prefix = f"{key}="
    for part in str(reason or "").split("|"):
        if part.startswith(prefix):
            return part[len(prefix):].strip().lower()
    return ""


def reason_float(reason: Any, key: str, default: float = 0.0) -> float:
    try:
        return float(reason_value(reason, key) or default)
    except (TypeError, ValueError):
        return default


def _layer(name: str, ok: bool, pass_reason: str, block_reason: str, value: Any = None) -> LayerResult:
    return LayerResult(name, "PASS" if ok else "BLOCK", pass_reason if ok else block_reason, value)


def _quality_row(trade: HistoricalTrade) -> QualityTradeRow:
    return QualityTradeRow(
        symbol=trade.symbol,
        side=trade.side,
        entry_time=trade.entry_time,
        exit_time=trade.exit_time,
        entry=trade.entry,
        stop=trade.stop,
        exit=trade.exit,
        r_mult=trade.r_mult,
        kind=trade.kind or trade.setup_type,
        source=trade.source,
        trend_context=trade.trend_context,
        volatility_regime=trade.volatility_regime,
        setup_type=trade.setup_type,
    )


def _structure_row(trade: HistoricalTrade) -> StructureTradeRow:
    risk = abs(trade.entry - trade.stop) / trade.entry * 100.0 if trade.entry > 0 else 0.0
    bucket = "tight" if risk < 1.65 else "normal" if risk <= 2.15 else "wide"
    hour = trade.entry_time.hour
    session = "asia" if hour < 8 else "europe" if hour < 16 else "us"
    return StructureTradeRow(
        symbol=trade.symbol,
        side=trade.side,
        entry_time=trade.entry_time,
        exit_time=trade.exit_time,
        entry=trade.entry,
        stop=trade.stop,
        exit=trade.exit,
        r_mult=trade.r_mult,
        kind=trade.kind or trade.setup_type,
        source=trade.source,
        setup_type=trade.setup_type,
        trend_context=trade.trend_context,
        volatility_regime=trade.volatility_regime,
        structure_type=trade.structure_type,
        risk_bucket=bucket,
        session=session,
    )


def _current_quality_row(plan: Any) -> QualityTradeRow:
    return QualityTradeRow(
        symbol=str(plan.symbol).upper(),
        side=str(plan.side).lower(),
        entry_time=plan.entry_time,
        exit_time=None,
        entry=float(plan.entry),
        stop=float(plan.stop),
        exit=None,
        r_mult=0.0,
        kind=str(plan.setup_type),
        source="live_candidate",
        trend_context=str(plan.trend_context),
        volatility_regime=str(plan.volatility_regime),
        setup_type=str(plan.setup_type),
    )


def _current_structure_row(plan: Any) -> StructureTradeRow:
    entry = float(plan.entry)
    stop = float(plan.stop)
    risk = abs(entry - stop) / entry * 100.0 if entry > 0 else 0.0
    bucket = "tight" if risk < 1.65 else "normal" if risk <= 2.15 else "wide"
    hour = plan.entry_time.hour
    session = "asia" if hour < 8 else "europe" if hour < 16 else "us"
    return StructureTradeRow(
        symbol=str(plan.symbol).upper(),
        side=str(plan.side).lower(),
        entry_time=plan.entry_time,
        exit_time=None,
        entry=entry,
        stop=stop,
        exit=None,
        r_mult=0.0,
        kind=str(plan.setup_type),
        source="live_candidate",
        setup_type=str(plan.setup_type),
        trend_context=str(plan.trend_context),
        volatility_regime=str(plan.volatility_regime),
        structure_type=str(plan.structure_type),
        risk_bucket=bucket,
        session=session,
    )


def _find_quality_result(rows: Iterable[Any], plan: Any) -> Any:
    target_time = plan.entry_time.isoformat()
    for row in reversed(list(rows)):
        if row.symbol == str(plan.symbol).upper() and row.side == str(plan.side).lower() and row.entry_time == target_time:
            return row
    raise RuntimeError("Current candidate missing from quality score output")


def _find_structure_result(rows: Iterable[Any], plan: Any) -> Any:
    target_time = plan.entry_time.isoformat()
    for row in reversed(list(rows)):
        if row.symbol == str(plan.symbol).upper() and row.side == str(plan.side).lower() and row.entry_time == target_time:
            return row
    raise RuntimeError("Current candidate missing from structure score output")


def evaluate_candidate(
    plan: Any,
    closed_history: Iterable[HistoricalTrade],
    *,
    data_fresh: bool,
    candle_closed: bool,
    universe_allowed: bool,
    open_symbol_positions: int = 0,
    kill_switch_blocked: bool = False,
    cfg: DecisionEngineConfig | None = None,
) -> DecisionResult:
    cfg = cfg or DecisionEngineConfig()
    reason = str(getattr(plan, "reason", ""))
    setup = _norm(getattr(plan, "setup_type", ""))
    direction = reason_value(reason, "dir")
    liquidity = reason_value(reason, "liq")
    candle = reason_value(reason, "candle")
    volume_ratio = reason_float(reason, "vr", 0.0)
    volatility = _norm(getattr(plan, "volatility_regime", ""))
    confidence = float(getattr(plan, "confidence_hint", 0.0) or 0.0)
    rr = float(getattr(plan, "target_rr", 0.0) or 0.0)
    entry = float(getattr(plan, "entry", 0.0) or 0.0)
    stop = float(getattr(plan, "stop", 0.0) or 0.0)
    target = float(getattr(plan, "target", 0.0) or 0.0)

    layers: list[LayerResult] = [
        _layer("DATA_FRESHNESS", data_fresh, "market_data_fresh", "market_data_stale"),
        _layer("CLOSED_CANDLE", candle_closed, "closed_candle_only", "forming_candle_blocked"),
        _layer("UNIVERSE", universe_allowed, "symbol_allowed", "symbol_not_allowed"),
        _layer("SETUP", setup in cfg.allowed_setup_types and setup not in cfg.blocked_setup_types, "validated_setup_type", "setup_not_in_validated_baseline", setup),
        _layer("DIRECTION", direction in cfg.allowed_direction_contexts, "validated_direction_context", "direction_not_allowed", direction),
        _layer("VOLATILITY", volatility not in cfg.blocked_volatility_regimes, "volatility_allowed", "volatility_blocked", volatility),
        _layer("LIQUIDITY", liquidity not in cfg.blocked_liquidity_states, "liquidity_allowed", "liquidity_blocked", liquidity),
        _layer("CANDLE_PATTERN", candle not in cfg.blocked_candle_types, "candle_pattern_allowed", "candle_pattern_blocked", candle),
        _layer("VOLUME", volume_ratio >= cfg.min_volume_ratio, "volume_ratio_allowed", "volume_ratio_too_low", round(volume_ratio, 6)),
        _layer("CONFIDENCE", confidence >= cfg.min_confidence, "confidence_allowed", "confidence_too_low", round(confidence, 4)),
    ]

    history = list(closed_history)
    q_rows = score_quality_trades(
        [_quality_row(t) for t in history] + [_current_quality_row(plan)],
        QualityConfig(30, 3, cfg.quality_take_threshold, cfg.quality_watch_threshold),
    )
    q = _find_quality_result(q_rows, plan)
    q_status = "PASS" if q.decision == "TAKE" else "WATCH" if q.decision == "WATCH" else "BLOCK"
    if q.history_trades == 0 and cfg.cold_start_policy == "watch" and q_status == "BLOCK":
        q_status = "WATCH"
    layers.append(LayerResult("QUALITY", q_status, f"quality_{q.decision.lower()}", {"score": q.trade_confidence_score, "history": q.history_trades}))

    s_rows = score_structure_trades(
        [_structure_row(t) for t in history] + [_current_structure_row(plan)],
        StructureLearningConfig(30, 8, 20, cfg.structure_take_threshold, cfg.structure_watch_threshold),
    )
    s = _find_structure_result(s_rows, plan)
    s_status = "PASS" if s.structure_decision == "TAKE" else "WATCH" if s.structure_decision == "WATCH" else "BLOCK"
    if s.history_trades == 0 and cfg.cold_start_policy == "watch" and s_status == "BLOCK":
        s_status = "WATCH"
    layers.append(LayerResult("STRUCTURE_LEARNING", s_status, f"structure_{s.structure_decision.lower()}", {"score": s.structure_score, "history": s.history_trades, "scope": s.learning_scope}))

    risk_ok = entry > 0 and stop > 0 and target > 0 and stop != entry and target != entry and rr >= cfg.min_target_rr
    layers.append(_layer("RISK", risk_ok, "risk_plan_valid", "risk_plan_invalid", {"rr": rr, "entry": entry, "stop": stop, "target": target}))

    portfolio_ok = not kill_switch_blocked and open_symbol_positions < cfg.max_open_per_symbol
    portfolio_reason = "portfolio_limits_ok" if portfolio_ok else "kill_switch_blocked" if kill_switch_blocked else "max_open_per_symbol"
    layers.append(LayerResult("PORTFOLIO", "PASS" if portfolio_ok else "BLOCK", portfolio_reason, open_symbol_positions))

    ready = all(layer.status != "BLOCK" for layer in layers)
    return DecisionResult(
        baseline=BASELINE_NAME,
        symbol=str(plan.symbol).upper(),
        side=str(plan.side).lower(),
        entry_time=plan.entry_time.isoformat(timespec="seconds"),
        final_status="READY" if ready else "BLOCKED",
        ready=ready,
        quality_decision=q.decision,
        structure_decision=s.structure_decision,
        layers=tuple(layers),
    )
