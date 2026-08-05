#!/usr/bin/env python3
"""Export real SMOKE MTF V2 recognition states without future outcomes or PnL."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Iterable

from strategy_lab.market_data import Candle
from strategy_lab.mtf_dealing_range_v2 import MtfDealingRangeEngine, SetupState
from strategy_lab.mtf_entry_model_v2 import MtfEntryModelV2
from strategy_lab.mtf_recognition_fast_runtime_v2 import install_fast_runtime


FORBIDDEN_OUTCOME_TOKENS = (
    "pnl",
    "profit",
    "future_return",
    "realized_return",
    "win",
    "loss",
    "tp_hit",
    "sl_hit",
    "mfe",
    "mae",
)

STAGE_RANK = {
    SetupState.NO_CONTEXT.value: 0,
    SetupState.MACRO_SCENARIO_READY.value: 1,
    SetupState.DAILY_RANGE_READY.value: 2,
    SetupState.H4_RANGE_READY.value: 3,
    SetupState.POI_APPROACH.value: 4,
    SetupState.POI_TESTED.value: 5,
    SetupState.H1_REACTION_OR_RAID.value: 6,
    SetupState.WAIT_5M_BOS.value: 7,
    SetupState.M5_BOS_CONFIRMED.value: 8,
    SetupState.M15_ARMED.value: 9,
    SetupState.ENTRY_READY.value: 10,
    SetupState.INVALIDATED_OR_EXPIRED.value: -1,
}


def _contains_outcome_token(field_name: str) -> bool:
    """Reject outcome fields without false positives such as candle_windows."""
    normalized = str(field_name).strip().lower()
    parts = {part for part in re.split(r"[^a-z0-9]+", normalized) if part}
    for token in FORBIDDEN_OUTCOME_TOKENS:
        if token in {"win", "loss"}:
            if token in parts:
                return True
            continue
        if token in normalized:
            return True
    return False


def assert_no_outcome_fields(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _contains_outcome_token(str(key)):
                raise ValueError(f"forbidden outcome field at {path}.{key}")
            assert_no_outcome_fields(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            assert_no_outcome_fields(item, f"{path}[{index}]")


def _level_payload(level) -> dict[str, Any] | None:
    if level is None:
        return None
    return {
        "timeframe": level.timeframe,
        "kind": level.kind,
        "side": level.side,
        "low": level.low,
        "high": level.high,
        "confirmed_at": level.confirmed_at.isoformat(),
        "strength": level.strength,
        "source": level.source,
        "fresh": level.fresh,
        "touches": level.touches,
    }


def plan_payload(plan) -> dict[str, Any]:
    payload = {
        "timestamp": plan.evaluated_at.isoformat(),
        "symbol": plan.symbol,
        "side": plan.side,
        "setup_state": plan.setup_state.value,
        "stage_rank": STAGE_RANK.get(plan.setup_state.value, -1),
        "entry_ready": plan.allowed,
        "scenario": plan.context.scenario.value,
        "scenario_strength": plan.context.scenario_strength,
        "monthly_state": plan.context.monthly.state.value,
        "weekly_state": plan.context.weekly.state.value,
        "daily_state": plan.context.daily.state.value,
        "h4_state": plan.context.h4.state.value,
        "h1_state": plan.context.h1.state.value,
        "long_allowed": plan.context.long_allowed,
        "short_allowed": plan.context.short_allowed,
        "poi": _level_payload(plan.poi),
        "h1_raid": plan.h1_raid,
        "raid_strength": plan.raid.strength if plan.raid else None,
        "h1_reaction": plan.h1_reaction,
        "h1_vc": plan.h1_vc,
        "h1_vc_strength": plan.volume_confirmation.strength if plan.volume_confirmation else None,
        "vc_zone_test": plan.vc_zone_test,
        "vc_zone_test_strength": plan.vc_test.rejection_strength if plan.vc_test else None,
        "m5_bos": plan.bos is not None,
        "m5_bos_strength": plan.bos.strength if plan.bos else None,
        "planned_entry_time": plan.entry_time.isoformat() if plan.entry_time else None,
        "planned_entry": plan.entry,
        "planned_stop": plan.stop,
        "planned_target": plan.target,
        "target_timeframe": plan.target_timeframe,
        "target_source": plan.target_source,
        "planned_rr": plan.rr,
        "quality_score": plan.quality_score,
        "quality_state": plan.quality_state,
        "event_blocked": plan.event_blocked,
        "event_risk_multiplier": plan.event_risk_multiplier,
        "reasons": list(plan.reasons),
    }
    assert_no_outcome_fields(payload)
    return payload


def export_recognition_candidates(
    candles: Iterable[Candle],
    scan_start: datetime,
    scan_end: datetime,
    per_group: int = 4,
) -> dict[str, Any]:
    engine = MtfDealingRangeEngine(candles)
    runtime = install_fast_runtime(engine)
    model = MtfEntryModelV2(engine)
    scanned = 0
    qualifying: list[dict[str, Any]] = []
    state_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()

    for bar in engine.bars["15m"]:
        if not (scan_start <= bar.open_time < scan_end):
            continue
        scanned += 1
        for side in ("long", "short"):
            plan = model.evaluate(bar.symbol, bar.open_time, side)
            state_counts[plan.setup_state.value] += 1
            reason_counts.update(plan.reasons)
            payload = plan_payload(plan)
            if payload["poi"] is not None or plan.h1_raid or plan.h1_vc or plan.bos is not None:
                qualifying.append(payload)

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(qualifying, key=lambda item: (item["timestamp"], item["symbol"], item["side"])):
        key = (row["symbol"], row["side"], row["setup_state"])
        if len(groups[key]) < per_group:
            groups[key].append(row)
    selected = [row for key in sorted(groups) for row in groups[key]]
    selected.sort(key=lambda item: (item["timestamp"], item["symbol"], item["side"]))

    result = {
        "study_id": "SMOKE_MTF_V2_REAL_RECOGNITION_CANDIDATES",
        "mode": "NO_PNL_NO_FUTURE_OUTCOME",
        "scan_start": scan_start.isoformat(),
        "scan_end": scan_end.isoformat(),
        "evaluated_15m_bars": scanned,
        "evaluated_side_snapshots": scanned * 2,
        "qualifying_snapshots": len(qualifying),
        "selected_snapshots": len(selected),
        "selection_rule": "first N chronologically per symbol, side and setup_state",
        "per_group": per_group,
        "state_counts": dict(sorted(state_counts.items())),
        "reason_counts": dict(reason_counts.most_common(30)),
        "execution_cache": runtime.stats(),
        "candidates": selected,
    }
    assert_no_outcome_fields(result)
    return result
