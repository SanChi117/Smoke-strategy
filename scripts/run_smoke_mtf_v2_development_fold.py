#!/usr/bin/env python3
"""Run one frozen SMOKE MTF V2 development symbol/fold/side job."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from strategy_lab.market_data import parse_dt, read_candles_csv, validate_candles
from strategy_lab.mtf_dealing_range_v2 import MtfDealingRangeEngine
from strategy_lab.mtf_development_backtest_v1 import (
    FundingRate,
    TradeCandidate,
    _funding_map,
    candidate_to_dict,
    contiguous_fold_bounds,
    resolve_trade,
)
from strategy_lab.mtf_entry_model_v2 import MtfEntryModelV2
from strategy_lab.mtf_recognition_fast_runtime_v2 import install_fast_runtime


def read_funding_csv(path: str | Path) -> list[FundingRate]:
    source = Path(path)
    if not source.exists() or source.stat().st_size == 0:
        return []
    rows: list[FundingRate] = []
    with source.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"symbol", "time", "rate"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"missing funding columns: {sorted(missing)}")
        for row in reader:
            rows.append(FundingRate(str(row["symbol"]).upper(), parse_dt(str(row["time"])), float(row["rate"])))
    return sorted(rows, key=lambda item: (item.symbol, item.time))


def generate_side_candidates(candles, *, fold: int, side: str, scan_start, scan_end, study_end, funding_rates):
    symbols = {row.symbol.upper() for row in candles}
    if len(symbols) != 1:
        raise ValueError("one symbol per fold job is required")
    if side not in {"long", "short"}:
        raise ValueError("side must be long or short")
    symbol = next(iter(symbols))
    rows = sorted(candles, key=lambda item: item.time)
    funding = _funding_map(funding_rates)
    engine = MtfDealingRangeEngine(rows)
    runtime = install_fast_runtime(engine)
    model = MtfEntryModelV2(engine)
    candidates: list[TradeCandidate] = []
    evaluated = 0
    entry_ready = 0
    for bar in engine.bars["15m"]:
        if bar.symbol != symbol or not (scan_start <= bar.open_time < scan_end):
            continue
        evaluated += 1
        plan = model.evaluate(symbol, bar.open_time, side)
        if not plan.allowed:
            continue
        entry_ready += 1
        if None in (plan.entry, plan.stop, plan.target, plan.entry_time, plan.rr):
            raise AssertionError("allowed plan lacks frozen execution geometry")
        structural_risk = ((plan.entry - plan.stop) / plan.entry if side == "long" else (plan.stop - plan.entry) / plan.entry)
        if structural_risk <= 0:
            raise AssertionError("allowed plan has non-positive structural risk")
        exit_time, exit_price, exit_reason, gross_return, funding_component, net_return = resolve_trade(
            rows, symbol=symbol, side=side, entry_time=plan.entry_time, entry=plan.entry,
            stop=plan.stop, target=plan.target, study_end=study_end, funding=funding,
        )
        candidates.append(TradeCandidate(
            symbol=symbol, side=side, fold=fold, entry_time=plan.entry_time, entry=plan.entry,
            stop=plan.stop, target=plan.target, exit_time=exit_time, exit_price=exit_price,
            exit_reason=exit_reason, gross_return_fraction=round(gross_return, 12),
            funding_return_fraction=round(funding_component, 12), net_return_fraction=round(net_return, 12),
            structural_risk_fraction=round(structural_risk, 12),
            event_risk_multiplier=round(plan.event_risk_multiplier, 6), planned_rr=float(plan.rr),
            quality_score=float(plan.quality_score), target_timeframe=str(plan.target_timeframe or ""),
            target_source=str(plan.target_source or ""),
        ))
    candidates.sort(key=lambda item: (item.entry_time, item.symbol, item.side))
    return candidates, {
        "symbol": symbol, "side": side, "fold": fold,
        "scan_start": scan_start.isoformat(), "scan_end": scan_end.isoformat(),
        "evaluated_15m_bars": evaluated, "evaluated_side_snapshots": evaluated,
        "entry_ready_candidates": entry_ready, "candidate_count": len(candidates),
        "runtime": runtime.stats(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", required=True)
    parser.add_argument("--funding", required=True)
    parser.add_argument("--funding-summary", required=True)
    parser.add_argument("--fold", required=True, type=int)
    parser.add_argument("--side", required=True, choices=("long", "short"))
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--development-start", default="2025-01-01T00:00:00")
    parser.add_argument("--development-end", default="2026-07-01T00:00:00")
    args = parser.parse_args()

    development_start = parse_dt(args.development_start)
    development_end = parse_dt(args.development_end)
    bounds = contiguous_fold_bounds(development_start, development_end, 10)
    scan_start, scan_end = bounds[args.fold]
    candles = read_candles_csv(args.candles)
    validate_candles(candles)
    funding = read_funding_csv(args.funding)
    funding_summary = json.loads(Path(args.funding_summary).read_text(encoding="utf-8"))
    candidates, summary = generate_side_candidates(
        candles, fold=args.fold, side=args.side, scan_start=scan_start, scan_end=scan_end,
        study_end=development_end, funding_rates=funding,
    )
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "study_id": "SMOKE_MTF_V2_DEVELOPMENT_PROFITABILITY_V2",
        "mode": "FROZEN_DEVELOPMENT_TRADE_CANDIDATES_SIDE_PARTITION",
        "recognition_freeze_sha": "492eee9fdba5993b7f518e9a1ff38576e8b14285",
        "event_layer": "excluded_from_primary_development_due_no_causal_historical_point_in_time_snapshot",
        "funding_rows": len(funding),
        "funding_coverage_status": str(funding_summary.get("status") or "UNKNOWN"),
        "funding_summary": funding_summary,
        "summary": summary,
        "candidates": [candidate_to_dict(row) for row in candidates],
    }
    (out / "fold_candidates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps({**summary, "funding_rows": len(funding)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = list(candidate_to_dict(candidates[0]).keys()) if candidates else [
        "symbol", "side", "fold", "entry_time", "entry", "stop", "target", "exit_time",
        "exit_price", "exit_reason", "gross_return_fraction", "funding_return_fraction",
        "net_return_fraction", "structural_risk_fraction", "event_risk_multiplier",
        "planned_rr", "quality_score", "target_timeframe", "target_source",
    ]
    with (out / "fold_candidates.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(candidate_to_dict(row) for row in candidates)
    print(f"fold={args.fold} symbol={summary['symbol']} side={args.side} entry_ready={summary['entry_ready_candidates']} candidates={len(candidates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
