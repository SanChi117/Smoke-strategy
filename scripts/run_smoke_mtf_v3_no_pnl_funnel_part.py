#!/usr/bin/env python3
"""Run one symbol/fold/side no-PnL funnel audit partition."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from strategy_lab.market_data import parse_dt, read_candles_csv, validate_candles
from strategy_lab.mtf_dealing_range_v2 import MtfDealingRangeEngine
from strategy_lab.mtf_entry_model_v2 import MtfEntryModelV2
from strategy_lab.mtf_no_pnl_funnel_v1 import (
    STAGES,
    assert_no_outcome_fields,
    contiguous_fold_bounds,
    geometry_record,
    route_name,
    stage_flags,
    structural_fingerprint,
    transition_rates,
)
from strategy_lab.mtf_recognition_fast_runtime_v2 import install_fast_runtime


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", required=True)
    parser.add_argument("--fold", required=True, type=int)
    parser.add_argument("--side", required=True, choices=("long", "short"))
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--audit-start", default="2025-01-01T00:00:00")
    parser.add_argument("--audit-end", default="2026-07-01T00:00:00")
    args = parser.parse_args()

    audit_start = parse_dt(args.audit_start)
    audit_end = parse_dt(args.audit_end)
    if args.fold not in range(10):
        raise ValueError("fold must be in 0..9")
    scan_start, scan_end = contiguous_fold_bounds(audit_start, audit_end, 10)[args.fold]

    candles = read_candles_csv(args.candles)
    validate_candles(candles)
    symbols = {row.symbol.upper() for row in candles}
    if len(symbols) != 1:
        raise ValueError("one symbol per audit part is required")
    symbol = next(iter(symbols))

    engine = MtfDealingRangeEngine(sorted(candles, key=lambda row: row.time))
    runtime = install_fast_runtime(engine)
    model = MtfEntryModelV2(engine)

    stage_counts: Counter[str] = Counter()
    state_counts: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    context_counts: Counter[str] = Counter()
    poi_timeframe_counts: Counter[str] = Counter()
    poi_source_counts: Counter[str] = Counter()
    monthly_stage_counts: dict[str, Counter[str]] = defaultdict(Counter)
    fingerprint_counts: Counter[str] = Counter()
    state_transition_counts: Counter[str] = Counter()
    state_transition_minutes: dict[str, dict[str, float | int]] = {}
    geometry: list[dict] = []

    previous_state: str | None = None
    previous_time = None
    evaluated = 0

    for bar in engine.bars["15m"]:
        if bar.symbol != symbol or not (scan_start <= bar.open_time < scan_end):
            continue
        evaluated += 1
        plan = model.evaluate(symbol, bar.open_time, args.side)
        flags = stage_flags(plan, args.side, model.config.min_rr)
        month = bar.open_time.strftime("%Y-%m")
        for stage in STAGES:
            if flags[stage]:
                stage_counts[stage] += 1
                monthly_stage_counts[month][stage] += 1

        state = plan.setup_state.value
        state_counts[state] += 1
        context_counts[plan.context.scenario.value] += 1
        route_counts[route_name(plan)] += 1
        reason_counts.update(plan.reasons)
        if plan.poi is not None:
            poi_timeframe_counts[plan.poi.timeframe] += 1
            poi_source_counts[plan.poi.source] += 1

        fingerprint = structural_fingerprint(plan, args.side)
        if fingerprint is not None:
            fingerprint_counts[fingerprint] += 1
        record = geometry_record(plan, args.side)
        if record is not None:
            geometry.append(record)

        if previous_state is not None and state != previous_state:
            key = f"{previous_state}->{state}"
            state_transition_counts[key] += 1
            elapsed = max(0.0, (bar.open_time - previous_time).total_seconds() / 60.0)
            bucket = state_transition_minutes.setdefault(key, {"count": 0, "total_minutes": 0.0, "max_minutes": 0.0})
            bucket["count"] = int(bucket["count"]) + 1
            bucket["total_minutes"] = round(float(bucket["total_minutes"]) + elapsed, 4)
            bucket["max_minutes"] = round(max(float(bucket["max_minutes"]), elapsed), 4)
        previous_state = state
        previous_time = bar.open_time

    for bucket in state_transition_minutes.values():
        count = int(bucket["count"])
        bucket["average_minutes"] = round(float(bucket["total_minutes"]) / count, 4) if count else 0.0

    payload = {
        "study_id": "SMOKE_MTF_V3_NO_PNL_FUNNEL_V1",
        "mode": "OUTCOME_BLIND_FUNNEL_PART",
        "source_recognition_freeze_sha": "492eee9fdba5993b7f518e9a1ff38576e8b14285",
        "symbol": symbol,
        "side": args.side,
        "fold": args.fold,
        "scan_start": scan_start.isoformat(),
        "scan_end": scan_end.isoformat(),
        "evaluated_15m_bars": evaluated,
        "stage_counts": {stage: int(stage_counts.get(stage, 0)) for stage in STAGES},
        "stage_transition_rates": transition_rates(stage_counts),
        "setup_state_counts": dict(sorted(state_counts.items())),
        "route_counts": dict(sorted(route_counts.items())),
        "rejection_reason_counts": dict(sorted(reason_counts.items())),
        "context_scenario_counts": dict(sorted(context_counts.items())),
        "poi_timeframe_counts": dict(sorted(poi_timeframe_counts.items())),
        "poi_source_counts": dict(sorted(poi_source_counts.items())),
        "monthly_stage_counts": {month: {stage: int(values.get(stage, 0)) for stage in STAGES} for month, values in sorted(monthly_stage_counts.items())},
        "setup_state_transition_counts": dict(sorted(state_transition_counts.items())),
        "setup_state_transition_timing": dict(sorted(state_transition_minutes.items())),
        "structural_geometry_records": geometry,
        "structural_fingerprint_counts": dict(sorted(fingerprint_counts.items())),
        "runtime": runtime.stats(),
        "outcome_fields_excluded": True,
    }
    assert_no_outcome_fields(payload)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "funnel_part.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "symbol": symbol,
        "side": args.side,
        "fold": args.fold,
        "evaluated_15m_bars": evaluated,
        "entry_ready": int(stage_counts.get("ENTRY_READY", 0)),
        "m5_bos_confirmed": int(stage_counts.get("M5_BOS_CONFIRMED", 0)),
        "rr_gate_passed": int(stage_counts.get("RR_GATE_PASSED", 0)),
        "outcome_fields_excluded": True,
    }
    assert_no_outcome_fields(summary)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
