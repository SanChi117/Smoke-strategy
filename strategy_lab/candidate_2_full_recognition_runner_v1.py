#!/usr/bin/env python3
"""SMOKE CORE Candidate 2 C2-P8 full causal recognition replay adapter.

This adapter reuses the frozen P1-P6 opportunity discovery infrastructure, but
replaces Candidate 1's immediate admission with Candidate 2 regime,
acceptance/persistence, attainable-target, family-policy and quality contracts.
Jan-Jun 2024 is used here only for causal replay/debug semantics, never as new
profitability evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import strategy_lab.p7_full_recognition_runner_v1 as p7
from strategy_lab.context_liquidity_engine_v1 import ContextLiquidityConfig
from strategy_lab.economics_risk_portfolio_v1 import AccountState, AdmissionDecision, CostModel, ExecutionCandidate, Side
from strategy_lab.execution_family_policy_v1 import apply_family_policy
from strategy_lab.execution_structure_v1 import LocalStructureV1, evaluate_execution_structure
from strategy_lab.interaction_engine_v1 import InteractionConfig, InteractionEngineV1
from strategy_lab.market_data import Candle
from strategy_lab.mtf_dealing_range_v2 import ClosedBar, MtfDealingRangeEngine
from strategy_lab.poi_imbalance_engine_v1 import Direction, POIImbalanceEngine
from strategy_lab.scenario_fusion_v1 import ScenarioFamily
from strategy_lab.candidate_2_acceptance_engine_v1 import evaluate_persistence
from strategy_lab.candidate_2_family_policy_v1 import evaluate_trend_pullback_policy
from strategy_lab.candidate_2_quality_model_v2 import QualityComponentsV2, score_quality
from strategy_lab.candidate_2_regime_engine_v1 import classify_regime
from strategy_lab.candidate_2_target_reachability_v1 import MAX_SWING_ATR, evaluate_target
from strategy_lab.candidate_2_outcome_blind_recognition_v1 import (
    Candidate2RecognitionObservation,
    assert_clean,
    dedupe_global,
    from_policy,
    is_counted,
    run_recognition,
)

REPLAY_ID = "SMOKE_CORE_CANDIDATE_2_FULL_CAUSAL_REPLAY_V1"
DATA_ROOT = p7.DATA_ROOT
REPORT_PATH = Path("research_outputs/candidate_2_full_causal_replay_v1.json")
PENDING_MAX_15M_BARS = 8


@dataclass(frozen=True)
class PendingTrendScenario:
    pending_id: str
    trigger_time: datetime
    trigger_price: float
    spec: p7.FamilySpec
    structure: LocalStructureV1
    target: Any
    target_level: Any


def _closed_to_candles(rows: Sequence[ClosedBar]) -> list[Candle]:
    return [Candle(r.symbol, r.close_time, r.open, r.high, r.low, r.close, r.volume) for r in rows]


def _direction_sign(direction: str) -> float:
    return 1.0 if direction == "LONG" else -1.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _quality(
    *, scenario_id: str, evaluated_at: datetime, direction: str,
    regime: Any, persistence: Any, target: Any, spec: p7.FamilySpec,
    structure: LocalStructureV1, conflicts: Sequence[str],
):
    sign = _direction_sign(direction)
    regime_coherence = _clamp01((sign * regime.directional_structure_alignment + 1.0) / 2.0)
    location_quality = _clamp01((sign * regime.liquidity_location_context + 1.0) / 2.0)
    interaction_quality = _clamp01(spec.reaction_event.strength_0_100 / 100.0)
    acceptance = _clamp01((persistence.acceptance_measure + 1.0) / 2.0)
    structure_integrity = _clamp01(structure.confidence_0_100 / 100.0)
    target_quality = _clamp01(1.0 - target.volatility_distance / max(MAX_SWING_ATR, 1e-12)) if target.reachable else 0.0
    conflict_penalty = _clamp01(len(tuple(conflicts)) / 3.0)
    provenance = {
        "regime_coherence": (regime.regime_id,),
        "location_quality": (regime.regime_id,),
        "interaction_quality": (spec.reaction_event.event_id,),
        "acceptance_persistence": (persistence.persistence_id,),
        "structure_integrity": (structure.structure_id,),
        "target_reachability": (target.reachability_id,),
        "conflict_penalty": tuple(conflicts) if conflicts else ("no_hard_conflict",),
    }
    return score_quality(QualityComponentsV2(
        scenario_id=scenario_id, evaluated_at=evaluated_at,
        regime_coherence=regime_coherence, location_quality=location_quality,
        interaction_quality=interaction_quality, acceptance_persistence=acceptance,
        structure_integrity=structure_integrity, target_reachability=target_quality,
        conflict_penalty=conflict_penalty, provenance=provenance,
    ))


def _evaluate_pending(
    pending: PendingTrendScenario,
    *, symbol: str, fold: int, timestamp: datetime,
    bars_5m: Sequence[ClosedBar], bars_15m: Sequence[ClosedBar], view: p7.ContextView,
) -> Candidate2RecognitionObservation | None:
    direction = pending.spec.anchor.direction.value
    causal_candles = _closed_to_candles([b for b in bars_5m if b.close_time <= timestamp])
    if len(causal_candles) < 48:
        return None
    age = sum(pending.trigger_time < bar.close_time <= timestamp for bar in bars_15m)
    if age < 1 or age > PENDING_MAX_15M_BARS:
        return None

    regime = classify_regime(causal_candles, timestamp)
    persistence = evaluate_persistence(
        causal_candles,
        scenario_id=pending.pending_id,
        direction=direction,
        trigger_time=pending.trigger_time,
        evaluated_at=timestamp,
        trigger_price=pending.trigger_price,
        protected_price=pending.structure.protected_swing,
    )
    entry_price = bars_15m[-1].close
    costs = CostModel()
    buffer_fraction = costs.cost_buffer_pct / 100.0
    if direction == "LONG":
        stop_price = pending.structure.protected_swing * (1.0 - buffer_fraction)
        if not stop_price < entry_price < pending.target.price:
            return None
        risk_side = Side.LONG
        liquidation_price = entry_price * 0.95
    else:
        stop_price = pending.structure.protected_swing * (1.0 + buffer_fraction)
        if not pending.target.price < entry_price < stop_price:
            return None
        risk_side = Side.SHORT
        liquidation_price = entry_price * 1.05

    reachability = evaluate_target(
        causal_candles,
        scenario_id=pending.pending_id,
        direction=direction,
        evaluated_at=timestamp,
        entry_price=entry_price,
        stop_price=stop_price,
        target_id=pending.target.target_id,
        target_price=pending.target.price,
        structural_reason=f"frozen_p2_target:{pending.target_level.kind.value}",
    )

    closed_15m = [bar for bar in bars_15m if bar.close_time <= timestamp]
    atr_value = p7._atr(closed_15m, 14) or max(1e-12, entry_price * 0.001)
    atr_floor_pct = atr_value / entry_price * 100.0
    width_pct = max(0.0, pending.target_level.high - pending.target_level.low) / entry_price * 100.0
    liquidity_buffer_pct = max(width_pct, ContextLiquidityConfig().level_buffer_atr * atr_floor_pct)
    candidate = ExecutionCandidate(
        candidate_id=pending.pending_id, symbol=symbol, side=risk_side,
        evaluated_at=timestamp.isoformat(), entry_price=entry_price, stop_price=stop_price,
        target_price=pending.target.price, atr_floor_pct=atr_floor_pct,
        liquidity_buffer_pct=liquidity_buffer_pct, upstream_score=50.0,
        dependency_ids=(pending.target.target_id, pending.target_level.level_id, pending.spec.poi.poi_id, pending.spec.anchor.anchor_id, pending.structure.structure_id),
        dependencies_causal=True, leverage=20.0, margin_mode="isolated",
        liquidation_price=liquidation_price, correlation_cluster="CRYPTO_MARKET_BETA",
    )
    admission = p7.evaluate_candidate(candidate, AccountState(equity=10000.0))
    economics_valid = admission.decision in {AdmissionDecision.PASS, AdmissionDecision.CONDITIONAL_PASS}
    risk_valid = economics_valid
    hard_conflicts = tuple(view.conflicts + pending.structure.conflicts)
    policy = evaluate_trend_pullback_policy(
        scenario_id=pending.pending_id, evaluated_at=timestamp, direction=direction,
        regime=regime, persistence=persistence, target=reachability,
        structure_valid=True, economics_pass=economics_valid, risk_pass=risk_valid,
        hard_conflicts=hard_conflicts,
    )
    quality = _quality(
        scenario_id=pending.pending_id, evaluated_at=timestamp, direction=direction,
        regime=regime, persistence=persistence, target=reachability, spec=pending.spec,
        structure=pending.structure, conflicts=hard_conflicts,
    )
    return from_policy(
        symbol=symbol, fold=fold, policy=policy, quality=quality,
        economics_valid=economics_valid, risk_valid=risk_valid,
    )


def scan_symbol(symbol: str, candles: Sequence[Candle]) -> tuple[list[Candidate2RecognitionObservation], dict[str, Any]]:
    engine = MtfDealingRangeEngine(candles)
    bars_5m_all = [bar for bar in engine.bars["5m"] if bar.symbol == symbol]
    bars_15m_all = [bar for bar in engine.bars["15m"] if bar.symbol == symbol]
    boundaries = [bar.close_time for bar in bars_15m_all]
    folds = p7.assign_folds(boundaries)
    context_cfg = ContextLiquidityConfig(); interaction_cfg = InteractionConfig()
    interaction_engine = InteractionEngineV1(interaction_cfg); poi_engine = POIImbalanceEngine()
    levels_all = p7._precompute_levels(engine, symbol, boundaries, context_cfg)
    context_cache: dict[datetime, p7.ContextView] = {}
    poi_cache: dict[datetime, tuple[tuple[Any, ...], dict[str, Any]]] = {}
    pending: dict[str, PendingTrendScenario] = {}
    observations: list[Candidate2RecognitionObservation] = []
    bars_5m: list[ClosedBar] = []; bars_15m: list[ClosedBar] = []; cursor_5m = 0
    diagnostics = {"symbol": symbol, "boundaries": len(boundaries), "trend_triggers": 0, "pending_evaluations": 0, "entry_ready": 0, "cancelled": 0}

    for current_15m in bars_15m_all:
        timestamp = current_15m.close_time
        while cursor_5m < len(bars_5m_all) and bars_5m_all[cursor_5m].close_time <= timestamp:
            bars_5m.append(bars_5m_all[cursor_5m]); cursor_5m += 1
        bars_15m.append(current_15m)
        cache_key = timestamp.replace(minute=0, second=0, microsecond=0)
        if cache_key not in context_cache:
            context_cache[cache_key] = p7._context_view(engine, symbol, timestamp, context_cfg)
        view = context_cache[cache_key]

        for pid, item in list(pending.items()):
            age = sum(item.trigger_time < bar.close_time <= timestamp for bar in bars_15m)
            if age > PENDING_MAX_15M_BARS:
                pending.pop(pid, None); continue
            obs = _evaluate_pending(item, symbol=symbol, fold=folds[timestamp], timestamp=timestamp, bars_5m=bars_5m, bars_15m=bars_15m, view=view)
            if obs is None:
                continue
            diagnostics["pending_evaluations"] += 1
            observations.append(obs)
            if is_counted(obs):
                diagnostics["entry_ready"] += 1
                pending.pop(pid, None)
            elif obs.lifecycle.startswith("CANCELLED_"):
                diagnostics["cancelled"] += 1
                pending.pop(pid, None)

        if cache_key not in poi_cache:
            poi_cache[cache_key] = p7._active_pois(engine, timestamp, poi_engine)
        pois, evidence_map = poi_cache[cache_key]
        if view.hard_block or not pois:
            continue
        lookback = interaction_cfg.atr_length + max(interaction_cfg.inducement_max_age_bars, interaction_cfg.anchor_expiry_bars, interaction_cfg.acceptance_closes, interaction_cfg.invalidation_closes) + 2
        recent_15m = bars_15m[-lookback:]
        relevant_levels = p7._relevant_levels(levels_all, bars_5m, recent_15m, timestamp, context_cfg)
        relevant_pois = tuple(poi for poi in pois if any(bar.high >= poi.low and bar.low <= poi.high for bar in recent_15m))
        if not relevant_levels and not relevant_pois:
            continue
        interaction = interaction_engine.snapshot(symbol=symbol, timeframe="15m", bars=recent_15m, pois=relevant_pois, levels=relevant_levels, evaluated_at=timestamp)
        specs = p7._family_specs(interaction, {poi.poi_id: poi for poi in relevant_pois}, {level.level_id: level for level in relevant_levels}, view, recent_15m)
        for spec in specs:
            if spec.family != ScenarioFamily.TREND_PULLBACK_CONTINUATION:
                continue
            structure = evaluate_execution_structure(
                spec.anchor,
                {"5m": [bar for bar in bars_5m if bar.close_time >= spec.anchor.confirmed_at], "15m": [bar for bar in bars_15m if bar.close_time >= spec.anchor.confirmed_at]},
                timestamp,
            )
            if not apply_family_policy(structure, spec.policy_family).allowed:
                continue
            geometry = p7._entry_geometry(structure, spec.family, bars_15m, timestamp)
            if geometry is None:
                continue
            trigger_price, trigger_time = geometry
            target, target_level = p7._select_target(levels_all, bars_5m, spec.anchor.confirmed_at, trigger_price, spec.anchor.direction, context_cfg)
            if target is None or target_level is None:
                continue
            pending_id = p7._stable_id("c2pending", symbol, spec.anchor.anchor_id, structure.structure_id, target.target_id, trigger_time.isoformat())
            if pending_id in pending:
                continue
            pending[pending_id] = PendingTrendScenario(pending_id, trigger_time, trigger_price, spec, structure, target, target_level)
            diagnostics["trend_triggers"] += 1

    return observations, diagnostics


def execute_full_replay(root: Path = DATA_ROOT, output: Path = REPORT_PATH) -> dict[str, Any]:
    manifest, candles_by_symbol = p7.load_locked_dataset(root)
    all_rows: list[Candidate2RecognitionObservation] = []; diagnostics = []
    for symbol in p7.ALLOWED_SYMBOLS:
        rows, diag = scan_symbol(symbol, candles_by_symbol[symbol])
        all_rows.extend(rows); diagnostics.append(diag)
    report = run_recognition(all_rows)
    assert_clean(report)
    deduped, _ = dedupe_global(all_rows)
    counted = tuple(row for row in deduped if is_counted(row))
    payload = {
        "replay_id": REPLAY_ID,
        "candidate_id": "SMOKE_CORE_1_0_CANDIDATE_2",
        "purpose": "CAUSAL_REPLAY_DEBUG_ONLY_NOT_PROFITABILITY",
        "data_manifest_sha256": hashlib.sha256((root / "p7_full_recognition_data_manifest_v1.json").read_bytes()).hexdigest(),
        "source": manifest["source"], "interval": manifest["interval"],
        "start_inclusive": manifest["start_inclusive"], "end_inclusive": manifest["end_inclusive"],
        "recognition": {
            "total_rows": report.total_rows,
            "independent_entry_ready": report.independent_entry_ready,
            "duplicate_rows": report.duplicate_rows,
            "forbidden_rows": report.forbidden_rows,
            "missing_provenance_rows": report.missing_provenance_rows,
            "invalid_lifecycle_rows": report.invalid_lifecycle_rows,
            "reproducible": report.reproducible,
            "by_symbol": dict(report.by_symbol), "by_direction": dict(report.by_direction), "by_fold": {str(k): v for k, v in report.by_fold.items()},
            "fingerprints": list(report.fingerprints),
        },
        "by_family": {"TREND_PULLBACK_CONTINUATION": len(counted), "LIQUIDITY_RAID_REVERSAL": 0},
        "diagnostics": diagnostics,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def main() -> int:
    payload = execute_full_replay()
    print(json.dumps({"replay_id": REPLAY_ID, "entry_ready": payload["recognition"]["independent_entry_ready"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
