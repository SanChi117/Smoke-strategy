#!/usr/bin/env python3
"""Causal SHORT refinement around the frozen twelve-month dual-direction leader.

LONG rules are intentionally unchanged. Only SHORT entry-time guards and an
optional additional SHORT-only cooldown are compared. This is development
screening, not a promotion test. The selected candidate must later pass a
single frozen external holdout.

Research only. No API keys and no order execution.
"""
from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

import run_binance_walk_forward as wfo
import run_causal_long_history_calibration_v3 as v3
import run_causal_long_history_sweep as base
import run_twelve_month_dual_direction_screening as dev
from strategy_lab.pipeline import run_pipeline
from strategy_lab.research_metrics import aggregate_oos, pnl_totals
from strategy_lab.walk_forward_evaluation import (
    bool_value,
    evaluate_validation_window,
    parse_dt,
    reason_values,
    trade_key,
)

VARIANTS = [
    {"name": "SHORT_REF_BASELINE", "guard": "baseline", "short_cooldown_hours": 12.0},
    {"name": "SHORT_REF_CONTEXT_ALL", "guard": "context_all", "short_cooldown_hours": 12.0},
    {"name": "SHORT_REF_NO_NEUTRAL", "guard": "no_neutral", "short_cooldown_hours": 12.0},
    {"name": "SHORT_REF_NO_STRICT", "guard": "no_strict", "short_cooldown_hours": 12.0},
    {"name": "SHORT_REF_CONTEXT_NO_NEUTRAL", "guard": "context_no_neutral", "short_cooldown_hours": 12.0},
    {"name": "SHORT_REF_CONTEXT_NO_STRICT", "guard": "context_no_strict", "short_cooldown_hours": 12.0},
    {"name": "SHORT_REF_CONTEXT_ADVERSE_ALL", "guard": "context_adverse_all", "short_cooldown_hours": 12.0},
    {"name": "SHORT_REF_CONTEXT_CD24", "guard": "context_all", "short_cooldown_hours": 24.0},
    {"name": "SHORT_REF_CONTEXT_NO_NEUTRAL_CD24", "guard": "context_no_neutral", "short_cooldown_hours": 24.0},
    {"name": "SHORT_REF_CONTEXT_NO_STRICT_CD24", "guard": "context_no_strict", "short_cooldown_hours": 24.0},
]


def apply_short_guard(
    run_dir: Path,
    validation_start,
    validation_end,
    guard: str,
) -> int:
    """Apply only additional SHORT guards; LONG decisions remain untouched."""
    decisions_path = run_dir / "pipeline_decisions.csv"
    generated_path = run_dir / "generated_trades.csv"
    decisions, fields = v3.read_csv(decisions_path)
    generated, _ = v3.read_csv(generated_path)
    generated_by_key = {
        trade_key(row.get("symbol"), row.get("side"), row.get("entry_time")): row
        for row in generated
    }

    blocked = 0
    for row in decisions:
        entry_time = parse_dt(row.get("entry_time"))
        if not (validation_start <= entry_time < validation_end):
            continue
        if not bool_value(row.get("allowed")):
            continue

        side = str(row.get("side") or "").lower()
        if side != "short":
            continue

        key = trade_key(row.get("symbol"), row.get("side"), row.get("entry_time"))
        source = generated_by_key.get(key, {})
        meta = reason_values(source.get("risk_plan_reason"))
        setup = str(source.get("setup_type") or row.get("setup_type") or "").lower()
        candle = meta.get("candle", "")
        alignment = meta.get("ctx_align", "")
        weak_context = alignment not in {"aligned", "h4_only"}
        adverse_impulse = candle == "bull_impulse"
        neutral_candle = candle == "neutral"
        strict_resumption = setup == "pullback_resumption_strict"

        should_block = False
        if guard == "baseline":
            should_block = False
        elif guard == "context_all":
            should_block = weak_context
        elif guard == "no_neutral":
            should_block = neutral_candle
        elif guard == "no_strict":
            should_block = strict_resumption
        elif guard == "context_no_neutral":
            should_block = weak_context or neutral_candle
        elif guard == "context_no_strict":
            should_block = weak_context or strict_resumption
        elif guard == "context_adverse_all":
            should_block = weak_context or adverse_impulse
        else:
            raise ValueError(f"unknown short guard: {guard}")

        if should_block:
            row["allowed"] = "False"
            row["risk_pct"] = "0"
            row["reason"] = f"short_refinement_{guard}"
            blocked += 1

    v3.write_csv(decisions_path, decisions, fields)
    return blocked


def apply_short_extra_cooldown(
    run_dir: Path,
    validation_start,
    validation_end,
    cooldown_hours: float,
) -> int:
    """Extend cooldown for SHORT only after the frozen 12-hour global cooldown."""
    if cooldown_hours <= 12.0:
        return 0

    decisions_path = run_dir / "pipeline_decisions.csv"
    decisions, fields = v3.read_csv(decisions_path)
    ordered = sorted(
        enumerate(decisions),
        key=lambda item: (
            parse_dt(item[1].get("entry_time")),
            str(item[1].get("symbol") or ""),
            item[0],
        ),
    )
    last_short_by_symbol = {}
    blocked = 0
    cooldown = timedelta(hours=float(cooldown_hours))

    for _, row in ordered:
        entry_time = parse_dt(row.get("entry_time"))
        if not (validation_start <= entry_time < validation_end):
            continue
        if not bool_value(row.get("allowed")):
            continue
        if str(row.get("side") or "").lower() != "short":
            continue

        symbol = str(row.get("symbol") or "").upper()
        previous = last_short_by_symbol.get(symbol)
        if previous is not None and entry_time - previous < cooldown:
            row["allowed"] = "False"
            row["risk_pct"] = "0"
            row["reason"] = f"short_refinement_cooldown_{int(cooldown_hours)}h"
            blocked += 1
            continue
        last_short_by_symbol[symbol] = entry_time

    v3.write_csv(decisions_path, decisions, fields)
    return blocked


def short_gate(aggregate: dict[str, object], sides: dict[str, dict[str, object]]) -> str:
    long_stats = sides.get("long", {})
    short_stats = sides.get("short", {})
    pooled_pf_raw = aggregate.get("pooled_pf", 0.0)
    pooled_pf = 10.0 if pooled_pf_raw == "inf" else float(pooled_pf_raw)
    short_pf_raw = short_stats.get("pf", 0.0)
    short_pf = 10.0 if short_pf_raw == "inf" else float(short_pf_raw)
    long_pf_raw = long_stats.get("pf", 0.0)
    long_pf = 10.0 if long_pf_raw == "inf" else float(long_pf_raw)

    if (
        int(short_stats.get("trades", 0)) >= 25
        and float(short_stats.get("net_pnl", 0.0)) > 0
        and short_pf >= 1.25
        and int(long_stats.get("trades", 0)) >= 40
        and long_pf >= 1.70
        and int(aggregate.get("positive_folds", 0)) >= 5
        and pooled_pf >= 1.40
        and float(aggregate.get("worst_fold_return_pct", 0.0)) > -1.5
        and float(aggregate.get("worst_dd_pct", 99.0)) <= 5.0
    ):
        return "PASS_SHORT_DEVELOPMENT"
    if (
        int(short_stats.get("trades", 0)) >= 20
        and float(short_stats.get("net_pnl", 0.0)) > 0
        and short_pf >= 1.15
        and int(aggregate.get("positive_folds", 0)) >= 5
        and pooled_pf >= 1.30
    ):
        return "WATCH_SHORT_DEVELOPMENT"
    return "BLOCK_SHORT_DEVELOPMENT"


def main() -> int:
    parser = argparse.ArgumentParser(description="Causal SHORT refinement with frozen LONG rules")
    parser.add_argument("--candles", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--windows", type=int, default=8)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--profile", default="research_500")
    parser.add_argument("--pool-min-confidence", type=float, default=40.0)
    args = parser.parse_args()

    source = Path(args.candles)
    root = Path(args.out_dir)
    candle_rows, candle_fields = base.read_csv(source)
    if not candle_rows:
        raise RuntimeError("SHORT refinement candle source is empty")

    times = [parse_dt(row["time"]) for row in candle_rows]
    windows = wfo.make_windows(min(times), max(times), args.lookback_days, args.windows)
    if len(windows) != args.windows:
        raise RuntimeError(f"expected {args.windows} folds, got {len(windows)}")

    fold_rows = {item["name"]: [] for item in VARIANTS}
    events = {item["name"]: [] for item in VARIANTS}

    for fold_no, (warmup_start, validation_start, validation_end) in enumerate(windows, start=1):
        fold = f"fold_{fold_no:02d}"
        fold_root = root / "folds" / fold
        fold_candles = [
            row for row in candle_rows
            if warmup_start <= parse_dt(row["time"]) < validation_end
        ]
        candles_path = fold_root / "candles.csv"
        base.write_csv(candles_path, fold_candles, candle_fields)

        pool_path = fold_root / "pool" / "generated_trades.csv"
        base.generate_trade_pool(candles_path, pool_path, args.pool_min_confidence)
        pool_rows, pool_fields = base.read_csv(pool_path)

        template_spec = dev.threshold_spec("SHORT_REFINEMENT_TEMPLATE", "moderate")
        template_dir = fold_root / "template"
        selected = base.filtered_pool(pool_rows, float(template_spec["min_confidence"]))
        generated_path = template_dir / "generated_trades.csv"
        base.write_csv(generated_path, selected, pool_fields)
        template_cfg = base.config_for(template_spec, warmup_start, validation_end)
        run_pipeline(generated_path, template_dir, cfg=template_cfg, profile_name=args.profile)

        for item in VARIANTS:
            name = str(item["name"])
            run_dir = fold_root / "candidates" / name
            run_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template_dir / "generated_trades.csv", run_dir / "generated_trades.csv")
            shutil.copy2(template_dir / "pipeline_decisions.csv", run_dir / "pipeline_decisions.csv")

            variant_spec = dict(template_spec)
            variant_spec["name"] = name
            cfg = base.config_for(variant_spec, warmup_start, validation_end)
            row: dict[str, object] = {
                "fold": fold,
                "validation_start": validation_start.isoformat(),
                "validation_end": validation_end.isoformat(),
                "guard": item["guard"],
                "short_cooldown_hours": item["short_cooldown_hours"],
                "status": "OK",
            }

            try:
                frozen_blocked = dev.apply_variant_filter(
                    run_dir,
                    validation_start,
                    validation_end,
                    "dual",
                    "legacy_full",
                )
                short_guard_blocked = apply_short_guard(
                    run_dir,
                    validation_start,
                    validation_end,
                    str(item["guard"]),
                )
                global_cooldown_blocked = v3.apply_symbol_cooldown(
                    run_dir,
                    validation_start,
                    validation_end,
                    12.0,
                )
                short_cooldown_blocked = apply_short_extra_cooldown(
                    run_dir,
                    validation_start,
                    validation_end,
                    float(item["short_cooldown_hours"]),
                )
                summary = evaluate_validation_window(
                    run_dir,
                    validation_start,
                    validation_end,
                    args.profile,
                    cfg,
                )
                close_rows = v3.close_events(run_dir)
                row.update(asdict(summary))
                row.update(pnl_totals(close_rows))
                row["frozen_leader_blocked"] = frozen_blocked
                row["short_guard_blocked"] = short_guard_blocked
                row["global_cooldown_blocked"] = global_cooldown_blocked
                row["short_cooldown_blocked"] = short_cooldown_blocked
                events[name].extend(close_rows)
            except Exception as exc:
                row.update({
                    "status": "ERROR",
                    "error": f"{type(exc).__name__}: {exc}",
                    "executed_trades": 0,
                    "ret_pct": 0.0,
                    "max_dd_pct": 0.0,
                    "gross_profit": 0.0,
                    "gross_loss": 0.0,
                    "net_pnl": 0.0,
                    "pooled_pf": 0.0,
                })

            fold_rows[name].append(row)
            print(
                f"{name} {fold}: trades={row.get('executed_trades', 0)} "
                f"ret={row.get('ret_pct', 0)}",
                flush=True,
            )

    candidates = []
    diagnostics = {}
    for name, rows in fold_rows.items():
        aggregate = aggregate_oos(name, rows)
        sides = dev.side_summary(events[name])
        aggregate["short_gate"] = short_gate(aggregate, sides)
        aggregate["side_summary"] = sides
        candidates.append(aggregate)

        short_events = [
            row for row in events[name]
            if str(row.get("side") or "").lower() == "short"
        ]
        diagnostics[name] = {
            "sides": sides,
            "short_categories": v3.category_summary(short_events),
            "all_categories": v3.category_summary(events[name]),
        }
        if short_events:
            base.write_csv(root / "short_trades" / f"{name}.csv", short_events)

    gate_rank = {
        "PASS_SHORT_DEVELOPMENT": 2,
        "WATCH_SHORT_DEVELOPMENT": 1,
        "BLOCK_SHORT_DEVELOPMENT": 0,
    }

    def sort_key(row: dict[str, object]):
        short_stats = row.get("side_summary", {}).get("short", {})
        short_pf_raw = short_stats.get("pf", 0.0)
        short_pf = 10.0 if short_pf_raw == "inf" else float(short_pf_raw)
        return (
            gate_rank.get(str(row.get("short_gate")), 0),
            min(short_pf, 5.0),
            float(row.get("score", 0.0)),
        )

    candidates.sort(key=sort_key, reverse=True)
    leader_name = str(candidates[0]["name"]) if candidates else ""
    result = {
        "mode": "TWELVE_MONTH_CAUSAL_SHORT_REFINEMENT",
        "period_start": min(times).isoformat(),
        "period_end": max(times).isoformat(),
        "windows": args.windows,
        "lookback_days": args.lookback_days,
        "variants": len(VARIANTS),
        "pipeline_runs": len(windows),
        "long_rules_frozen": True,
        "leader": candidates[0] if candidates else {},
        "candidates": candidates,
        "leader_diagnostics": diagnostics.get(leader_name, {}),
        "promotion_allowed": False,
        "next_required_step": (
            "Freeze one SHORT refinement leader and test the combined LONG/SHORT "
            "baseline on an untouched external period."
        ),
    }

    root.mkdir(parents=True, exist_ok=True)
    base.write_csv(root / "candidate_summary.csv", candidates)
    for name, rows in fold_rows.items():
        base.write_csv(root / "candidate_folds" / f"{name}.csv", rows)
    (root / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
