#!/usr/bin/env python3
"""Segmented causal replay for Candidate 2 C2-P8 with state checkpoints."""
from __future__ import annotations

from pathlib import Path
import pickle
from typing import Any, Sequence

import strategy_lab.p7_full_recognition_runner_v1 as p7
import strategy_lab.candidate_2_full_recognition_runner_v1 as c2
import strategy_lab.candidate_2_checkpoint_transport_v1 as checkpoint_transport
from strategy_lab.context_liquidity_engine_v1 import ContextLiquidityConfig
from strategy_lab.execution_family_policy_v1 import apply_family_policy
from strategy_lab.execution_structure_v1 import evaluate_execution_structure
from strategy_lab.interaction_engine_v1 import InteractionConfig, InteractionEngineV1
from strategy_lab.market_data import Candle
from strategy_lab.mtf_dealing_range_v2 import ClosedBar, MtfDealingRangeEngine
from strategy_lab.poi_imbalance_engine_v1 import POIImbalanceEngine
from strategy_lab.scenario_fusion_v1 import ScenarioFamily
from strategy_lab.candidate_2_outcome_blind_recognition_v1 import Candidate2RecognitionObservation, is_counted

SEGMENT_COUNT = 8
WARMUP_15M_BARS = c2.PENDING_MAX_15M_BARS + 4
CHECKPOINT_VERSION = "C2_CAUSAL_CHECKPOINT_V1"
checkpoint_transport.install(p7)


def _bounds(total: int, index: int, count: int) -> tuple[int, int]:
    if count <= 0 or not 0 <= index < count:
        raise ValueError("invalid segment index/count")
    base, rem = divmod(total, count)
    start = index * base + min(index, rem)
    end = start + base + (1 if index < rem else 0)
    return start, end


def _load_checkpoint(path: Path, *, symbol: str, segment_index: int, engine: Any) -> dict[str, c2.PendingTrendScenario]:
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    if payload.get("version") != CHECKPOINT_VERSION:
        raise ValueError("Candidate 2 checkpoint version mismatch")
    if payload.get("symbol") != symbol:
        raise ValueError("Candidate 2 checkpoint symbol mismatch")
    if int(payload.get("next_segment_index", -1)) != segment_index:
        raise ValueError("Candidate 2 checkpoint segment continuity mismatch")
    checkpoint_transport.restore_provider(engine, payload["poi_provider"])
    return dict(payload.get("pending", {}))


def _save_checkpoint(path: Path, *, symbol: str, segment_index: int, emit_end_time: Any, engine: Any, pending: dict[str, c2.PendingTrendScenario]) -> None:
    payload = {
        "version": CHECKPOINT_VERSION,
        "symbol": symbol,
        "completed_segment_index": segment_index,
        "next_segment_index": segment_index + 1,
        "asof": emit_end_time.isoformat(),
        "poi_provider": checkpoint_transport.get_provider(engine),
        "pending": dict(pending),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)


def scan_symbol_segment(
    symbol: str,
    candles: Sequence[Candle],
    *,
    segment_index: int,
    segment_count: int = SEGMENT_COUNT,
    checkpoint_in: Path | None = None,
    checkpoint_out: Path | None = None,
) -> tuple[list[Candidate2RecognitionObservation], dict[str, Any]]:
    engine = MtfDealingRangeEngine(candles)
    bars_5m_all = [bar for bar in engine.bars["5m"] if bar.symbol == symbol]
    bars_15m_all = [bar for bar in engine.bars["15m"] if bar.symbol == symbol]
    boundaries = [bar.close_time for bar in bars_15m_all]
    folds = p7.assign_folds(boundaries)
    emit_start, emit_end = _bounds(len(bars_15m_all), segment_index, segment_count)
    if emit_start == emit_end:
        return [], {"symbol": symbol, "segment_index": segment_index, "segment_count": segment_count, "empty": True}

    emit_start_time = boundaries[emit_start]
    emit_end_time = boundaries[emit_end - 1]
    if checkpoint_in is not None:
        pending = _load_checkpoint(checkpoint_in, symbol=symbol, segment_index=segment_index, engine=engine)
        process_start = emit_start
        checkpoint_restored = True
    else:
        pending = {}
        process_start = max(0, emit_start - WARMUP_15M_BARS)
        checkpoint_restored = False

    context_cfg = ContextLiquidityConfig()
    interaction_cfg = InteractionConfig()
    interaction_engine = InteractionEngineV1(interaction_cfg)
    poi_engine = POIImbalanceEngine()
    levels_all = p7._precompute_levels(engine, symbol, boundaries, context_cfg)
    context_cache: dict[Any, p7.ContextView] = {}
    poi_cache: dict[Any, tuple[tuple[Any, ...], dict[str, Any]]] = {}
    observations: list[Candidate2RecognitionObservation] = []

    bars_15m: list[ClosedBar] = list(bars_15m_all[:process_start])
    if bars_15m:
        preload_time = bars_15m[-1].close_time
        bars_5m: list[ClosedBar] = [bar for bar in bars_5m_all if bar.close_time <= preload_time]
        cursor_5m = len(bars_5m)
    else:
        bars_5m = []
        cursor_5m = 0

    diagnostics = {
        "symbol": symbol,
        "segment_index": segment_index,
        "segment_count": segment_count,
        "emit_start": emit_start_time.isoformat(),
        "emit_end": emit_end_time.isoformat(),
        "process_start_index": process_start,
        "checkpoint_restored": checkpoint_restored,
        "checkpoint_version": CHECKPOINT_VERSION,
        "trend_triggers": 0,
        "pending_evaluations": 0,
        "entry_ready": 0,
        "cancelled": 0,
    }

    for current_15m in bars_15m_all[process_start:emit_end]:
        timestamp = current_15m.close_time
        while cursor_5m < len(bars_5m_all) and bars_5m_all[cursor_5m].close_time <= timestamp:
            bars_5m.append(bars_5m_all[cursor_5m])
            cursor_5m += 1
        bars_15m.append(current_15m)

        cache_key = timestamp.replace(minute=0, second=0, microsecond=0)
        if cache_key not in context_cache:
            context_cache[cache_key] = p7._context_view(engine, symbol, timestamp, context_cfg)
        view = context_cache[cache_key]

        for pid, item in list(pending.items()):
            age = sum(item.trigger_time < bar.close_time <= timestamp for bar in bars_15m)
            if age > c2.PENDING_MAX_15M_BARS:
                pending.pop(pid, None)
                continue
            obs = c2._evaluate_pending(
                item, symbol=symbol, fold=folds[timestamp], timestamp=timestamp,
                bars_5m=bars_5m, bars_15m=bars_15m, view=view,
            )
            if obs is None:
                continue
            diagnostics["pending_evaluations"] += 1
            if timestamp >= emit_start_time:
                observations.append(obs)
            if is_counted(obs):
                if timestamp >= emit_start_time:
                    diagnostics["entry_ready"] += 1
                pending.pop(pid, None)
            elif obs.lifecycle.startswith("CANCELLED_"):
                if timestamp >= emit_start_time:
                    diagnostics["cancelled"] += 1
                pending.pop(pid, None)

        if cache_key not in poi_cache:
            poi_cache[cache_key] = p7._active_pois(engine, timestamp, poi_engine)
        pois, _evidence_map = poi_cache[cache_key]
        if view.hard_block or not pois:
            continue

        lookback = interaction_cfg.atr_length + max(
            interaction_cfg.inducement_max_age_bars,
            interaction_cfg.anchor_expiry_bars,
            interaction_cfg.acceptance_closes,
            interaction_cfg.invalidation_closes,
        ) + 2
        recent_15m = bars_15m[-lookback:]
        relevant_levels = p7._relevant_levels(levels_all, bars_5m, recent_15m, timestamp, context_cfg)
        relevant_pois = tuple(poi for poi in pois if any(bar.high >= poi.low and bar.low <= poi.high for bar in recent_15m))
        if not relevant_levels and not relevant_pois:
            continue

        interaction = interaction_engine.snapshot(
            symbol=symbol, timeframe="15m", bars=recent_15m,
            pois=relevant_pois, levels=relevant_levels, evaluated_at=timestamp,
        )
        specs = p7._family_specs(
            interaction,
            {poi.poi_id: poi for poi in relevant_pois},
            {level.level_id: level for level in relevant_levels},
            view, recent_15m,
        )
        for spec in specs:
            if spec.family != ScenarioFamily.TREND_PULLBACK_CONTINUATION:
                continue
            structure = evaluate_execution_structure(
                spec.anchor,
                {
                    "5m": [bar for bar in bars_5m if bar.close_time >= spec.anchor.confirmed_at],
                    "15m": [bar for bar in bars_15m if bar.close_time >= spec.anchor.confirmed_at],
                },
                timestamp,
            )
            if not apply_family_policy(structure, spec.policy_family).allowed:
                continue
            geometry = p7._entry_geometry(structure, spec.family, bars_15m, timestamp)
            if geometry is None:
                continue
            trigger_price, trigger_time = geometry
            target, target_level = p7._select_target(
                levels_all, bars_5m, spec.anchor.confirmed_at, trigger_price,
                spec.anchor.direction, context_cfg,
            )
            if target is None or target_level is None:
                continue
            pending_id = p7._stable_id(
                "c2pending", symbol, spec.anchor.anchor_id, structure.structure_id,
                target.target_id, trigger_time.isoformat(),
            )
            if pending_id in pending:
                continue
            pending[pending_id] = c2.PendingTrendScenario(
                pending_id, trigger_time, trigger_price, spec, structure, target, target_level
            )
            if timestamp >= emit_start_time:
                diagnostics["trend_triggers"] += 1

    if checkpoint_out is not None:
        _save_checkpoint(
            checkpoint_out, symbol=symbol, segment_index=segment_index,
            emit_end_time=emit_end_time, engine=engine, pending=pending,
        )
        diagnostics["checkpoint_saved"] = True
    else:
        diagnostics["checkpoint_saved"] = False
    return observations, diagnostics
