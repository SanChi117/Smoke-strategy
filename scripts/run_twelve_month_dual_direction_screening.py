#!/usr/bin/env python3
"""Twelve-month causal development screening for regime-aligned LONG and SHORT pullbacks.

This is a development screen, not a promotion test. It combines rising and falling
market regimes and compares a small set of symmetric entry-time guards. A selected
candidate must later pass one frozen external holdout that is not used here.

Research only. No API keys and no order execution.
"""
from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import run_binance_walk_forward as wfo
import run_causal_long_history_calibration_v3 as v3
import run_causal_long_history_sweep as base
from strategy_lab.pipeline import run_pipeline
from strategy_lab.research_metrics import aggregate_oos, pnl_totals, safe_float
from strategy_lab.walk_forward_evaluation import bool_value, evaluate_validation_window, parse_dt, reason_values, trade_key

PULLBACK_FAMILY = ("pullback", "pullback_resumption", "pullback_resumption_strict")


def threshold_spec(name: str, mode: str) -> dict[str, object]:
    if mode == "moderate":
        quality_take, quality_watch = 57.0, 44.0
        structure_take, structure_watch = 56.0, 44.0
        min_volume = 0.50
    elif mode == "expanded":
        quality_take, quality_watch = 55.0, 42.0
        structure_take, structure_watch = 54.0, 42.0
        min_volume = 0.45
    else:
        raise ValueError(f"unknown threshold mode: {mode}")
    return {
        "name": name,
        "rolling_top_n": 8,
        "require_rolling_top": False,
        "require_universe_gate": False,
        "min_confidence": 40.0,
        "quality_take_threshold": quality_take,
        "quality_watch_threshold": quality_watch,
        "structure_take_threshold": structure_take,
        "structure_watch_threshold": structure_watch,
        "allowed_setup_types": PULLBACK_FAMILY,
        "blocked_setup_types": ("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim", "ignition"),
        "blocked_volatility_regimes": ("high",),
        "blocked_liquidity_states": ("high_sweep_reject",),
        "blocked_candle_types": (),
        "allowed_direction_contexts": ("up", "down"),
        "min_volume_ratio": min_volume,
    }


VARIANTS = [
    {"name": "DEV12_MOD_SHORT_CONTEXT", "threshold": "moderate", "mode": "short", "guard": "legacy_context"},
    {"name": "DEV12_MOD_LONG_CONTEXT", "threshold": "moderate", "mode": "long", "guard": "legacy_context"},
    {"name": "DEV12_MOD_DUAL_BASIC", "threshold": "moderate", "mode": "dual", "guard": "none"},
    {"name": "DEV12_MOD_DUAL_CONTEXT", "threshold": "moderate", "mode": "dual", "guard": "legacy_context"},
    {"name": "DEV12_MOD_DUAL_SYM_IMPULSE", "threshold": "moderate", "mode": "dual", "guard": "legacy_symmetric_impulse"},
    {"name": "DEV12_MOD_DUAL_FULL", "threshold": "moderate", "mode": "dual", "guard": "legacy_full"},
    {"name": "DEV12_EXP_DUAL_BASIC", "threshold": "expanded", "mode": "dual", "guard": "none"},
    {"name": "DEV12_EXP_DUAL_CONTEXT", "threshold": "expanded", "mode": "dual", "guard": "legacy_context"},
    {"name": "DEV12_EXP_DUAL_FULL", "threshold": "expanded", "mode": "dual", "guard": "legacy_full"},
    {"name": "DEV12_EXP_DUAL_ALL_CONTEXT", "threshold": "expanded", "mode": "dual", "guard": "all_context"},
    {"name": "DEV12_EXP_DUAL_RESUMPTION_ONLY", "threshold": "expanded", "mode": "dual", "guard": "resumption_only"},
]


def apply_variant_filter(run_dir: Path, validation_start, validation_end, mode: str, guard: str) -> int:
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
        key = trade_key(row.get("symbol"), row.get("side"), row.get("entry_time"))
        source = generated_by_key.get(key, {})
        meta = reason_values(source.get("risk_plan_reason"))
        side = str(source.get("side") or row.get("side") or "").lower()
        direction = meta.get("dir", "")
        setup = str(source.get("setup_type") or row.get("setup_type") or "").lower()
        candle = meta.get("candle", "")
        alignment = meta.get("ctx_align", "")
        legacy = setup == "pullback"
        weak_context = alignment not in {"aligned", "h4_only"}
        adverse_impulse = (side == "short" and candle == "bull_impulse") or (side == "long" and candle == "bear_impulse")
        side_context_mismatch = (side == "short" and direction != "down") or (side == "long" and direction != "up")

        should_block = side_context_mismatch
        if mode == "short" and side != "short":
            should_block = True
        elif mode == "long" and side != "long":
            should_block = True
        elif mode not in {"short", "long", "dual"}:
            raise ValueError(f"unknown mode: {mode}")

        if guard == "legacy_context":
            should_block = should_block or (legacy and weak_context)
        elif guard == "legacy_symmetric_impulse":
            should_block = should_block or (legacy and adverse_impulse)
        elif guard == "legacy_full":
            should_block = should_block or (legacy and (weak_context or adverse_impulse))
        elif guard == "all_context":
            should_block = should_block or weak_context
        elif guard == "resumption_only":
            should_block = should_block or legacy
        elif guard != "none":
            raise ValueError(f"unknown guard: {guard}")

        if should_block:
            row["allowed"] = "False"
            row["risk_pct"] = "0"
            row["reason"] = f"dev12_{mode}_{guard}"
            blocked += 1
    v3.write_csv(decisions_path, decisions, fields)
    return blocked


def side_summary(events: list[dict[str, str]]) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in events:
        grouped[str(row.get("side") or "unknown").lower()].append(safe_float(row.get("net_pnl"), 0.0))
    result: dict[str, dict[str, object]] = {}
    for side, values in sorted(grouped.items()):
        profit = sum(value for value in values if value > 0)
        loss = abs(sum(value for value in values if value < 0))
        result[side] = {
            "trades": len(values),
            "wins": sum(1 for value in values if value > 0),
            "losses": sum(1 for value in values if value < 0),
            "gross_profit": round(profit, 6),
            "gross_loss": round(loss, 6),
            "net_pnl": round(sum(values), 6),
            "pf": round(profit / loss, 4) if loss > 0 else ("inf" if profit > 0 else 0.0),
        }
    return result


def development_gate(aggregate: dict[str, object], sides: dict[str, dict[str, object]]) -> str:
    long_stats = sides.get("long", {})
    short_stats = sides.get("short", {})
    both_sides = (
        int(long_stats.get("trades", 0)) >= 10
        and int(short_stats.get("trades", 0)) >= 10
        and float(long_stats.get("net_pnl", 0.0)) > 0
        and float(short_stats.get("net_pnl", 0.0)) > 0
    )
    pf = aggregate.get("pooled_pf", 0.0)
    pooled_pf = 10.0 if pf == "inf" else float(pf)
    if (
        int(aggregate.get("total_trades", 0)) >= 60
        and int(aggregate.get("positive_folds", 0)) >= 6
        and pooled_pf >= 1.20
        and float(aggregate.get("avg_return_pct", 0.0)) > 0
        and float(aggregate.get("worst_fold_return_pct", 0.0)) > -2.5
        and float(aggregate.get("worst_dd_pct", 99.0)) <= 8.0
        and both_sides
    ):
        return "PASS_DEVELOPMENT_SCREEN"
    if (
        int(aggregate.get("total_trades", 0)) >= 40
        and int(aggregate.get("positive_folds", 0)) >= 5
        and pooled_pf >= 1.10
        and float(aggregate.get("avg_return_pct", 0.0)) > 0
    ):
        return "WATCH_DEVELOPMENT"
    return "BLOCK_DEVELOPMENT"


def main() -> int:
    parser = argparse.ArgumentParser(description="Twelve-month dual-direction causal screening")
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
        raise RuntimeError("development candle source is empty")
    times = [parse_dt(row["time"]) for row in candle_rows]
    windows = wfo.make_windows(min(times), max(times), args.lookback_days, args.windows)
    if len(windows) != args.windows:
        raise RuntimeError(f"expected {args.windows} folds, got {len(windows)}")

    by_threshold: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in VARIANTS:
        by_threshold[str(item["threshold"])].append(item)
    fold_rows: dict[str, list[dict[str, object]]] = {str(item["name"]): [] for item in VARIANTS}
    events: dict[str, list[dict[str, str]]] = {str(item["name"]): [] for item in VARIANTS}

    for fold_no, (warmup_start, validation_start, validation_end) in enumerate(windows, start=1):
        fold = f"fold_{fold_no:02d}"
        fold_root = root / "folds" / fold
        fold_candles = [row for row in candle_rows if warmup_start <= parse_dt(row["time"]) < validation_end]
        candles_path = fold_root / "candles.csv"
        base.write_csv(candles_path, fold_candles, candle_fields)
        pool_path = fold_root / "pool" / "generated_trades.csv"
        base.generate_trade_pool(candles_path, pool_path, args.pool_min_confidence)
        pool_rows, pool_fields = base.read_csv(pool_path)

        for threshold, variants in by_threshold.items():
            template_spec = threshold_spec(f"DEV12_{threshold.upper()}_TEMPLATE", threshold)
            template_dir = fold_root / "templates" / threshold
            selected = base.filtered_pool(pool_rows, float(template_spec["min_confidence"]))
            generated_path = template_dir / "generated_trades.csv"
            base.write_csv(generated_path, selected, pool_fields)
            template_cfg = base.config_for(template_spec, warmup_start, validation_end)
            run_pipeline(generated_path, template_dir, cfg=template_cfg, profile_name=args.profile)

            for item in variants:
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
                    "threshold": threshold,
                    "mode": item["mode"],
                    "guard": item["guard"],
                    "status": "OK",
                }
                try:
                    filter_blocked = apply_variant_filter(
                        run_dir, validation_start, validation_end, str(item["mode"]), str(item["guard"])
                    )
                    cooldown_blocked = v3.apply_symbol_cooldown(run_dir, validation_start, validation_end, 12.0)
                    summary = evaluate_validation_window(
                        run_dir, validation_start, validation_end, args.profile, cfg
                    )
                    close_rows = v3.close_events(run_dir)
                    row.update(asdict(summary))
                    row.update(pnl_totals(close_rows))
                    row["filter_blocked"] = filter_blocked
                    row["cooldown_blocked"] = cooldown_blocked
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
                print(f"{name} {fold}: trades={row.get('executed_trades', 0)} ret={row.get('ret_pct', 0)}", flush=True)

    candidates = []
    diagnostics: dict[str, object] = {}
    for name, rows in fold_rows.items():
        aggregate = aggregate_oos(name, rows)
        sides = side_summary(events[name])
        aggregate["development_gate"] = development_gate(aggregate, sides)
        aggregate["side_summary"] = sides
        candidates.append(aggregate)
        diagnostics[name] = {
            "sides": sides,
            "categories": v3.category_summary(events[name]),
        }
    gate_rank = {"PASS_DEVELOPMENT_SCREEN": 2, "WATCH_DEVELOPMENT": 1, "BLOCK_DEVELOPMENT": 0}
    candidates.sort(
        key=lambda row: (gate_rank.get(str(row["development_gate"]), 0), float(row["score"])),
        reverse=True,
    )
    result = {
        "mode": "TWELVE_MONTH_DUAL_DIRECTION_DEVELOPMENT_SCREEN",
        "period_start": min(times).isoformat(),
        "period_end": max(times).isoformat(),
        "windows": args.windows,
        "lookback_days": args.lookback_days,
        "variants": len(VARIANTS),
        "pipeline_runs": len(windows) * len(by_threshold),
        "leader": candidates[0] if candidates else {},
        "candidates": candidates,
        "leader_diagnostics": diagnostics.get(str(candidates[0]["name"]), {}) if candidates else {},
        "promotion_allowed": False,
        "next_required_step": "Freeze one leader and validate on an untouched earlier period or symbol holdout.",
    }
    root.mkdir(parents=True, exist_ok=True)
    base.write_csv(root / "candidate_summary.csv", candidates)
    for name, rows in fold_rows.items():
        base.write_csv(root / "candidate_folds" / f"{name}.csv", rows)
    (root / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
