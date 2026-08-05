#!/usr/bin/env python3
"""Strict-OOS v4 screening for causal legacy-pullback guards.

The six existing Binance Futures folds are reused only as a screening set. The
script tests simple entry-time guards suggested by v3 diagnostics: repeated-entry
spacing, bull-impulse legacy pullbacks and weak higher-timeframe alignment. Any
winner still requires a separate external validation period/universe.

Research only. No API keys and no order execution.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import run_causal_long_history_calibration_v3 as v3
import run_causal_long_history_sweep as base
from strategy_lab.pipeline import run_pipeline
from strategy_lab.research_metrics import aggregate_oos, pnl_totals
from strategy_lab.walk_forward_evaluation import bool_value, parse_dt, reason_values, trade_key
from strategy_lab.walk_forward_evaluation import evaluate_validation_window

SOURCE = Path("results/causal_long_history_sweep_v1")
OUT = Path("results/causal_long_history_calibration_v4")
PROFILE = "research_500"


def threshold_spec(name: str, mode: str) -> dict[str, object]:
    if mode == "aggressive":
        return v3.spec(
            name,
            quality_take_threshold=57.0,
            quality_watch_threshold=44.0,
            structure_take_threshold=56.0,
            structure_watch_threshold=44.0,
            min_volume_ratio=0.50,
        )
    if mode == "expanded":
        return v3.spec(
            name,
            quality_take_threshold=55.0,
            quality_watch_threshold=42.0,
            structure_take_threshold=54.0,
            structure_watch_threshold=42.0,
            min_volume_ratio=0.45,
        )
    raise ValueError(f"unknown threshold mode: {mode}")


VARIANTS = [
    {"name": "CAL4_AGG_CONTROL_CD12", "mode": "aggressive", "cooldown": 12.0, "guard": "none"},
    {"name": "CAL4_AGG_CONTROL_CD16", "mode": "aggressive", "cooldown": 16.0, "guard": "none"},
    {"name": "CAL4_AGG_LEGACY_NO_BULL_CD12", "mode": "aggressive", "cooldown": 12.0, "guard": "legacy_no_bull"},
    {"name": "CAL4_AGG_LEGACY_CONTEXT_CD12", "mode": "aggressive", "cooldown": 12.0, "guard": "legacy_strong_context"},
    {"name": "CAL4_AGG_LEGACY_FULL_GUARD_CD12", "mode": "aggressive", "cooldown": 12.0, "guard": "legacy_full_guard"},
    {"name": "CAL4_AGG_ALL_STRONG_CONTEXT_CD12", "mode": "aggressive", "cooldown": 12.0, "guard": "all_strong_context"},
    {"name": "CAL4_EXP_CONTROL_CD12", "mode": "expanded", "cooldown": 12.0, "guard": "none"},
    {"name": "CAL4_EXP_LEGACY_NO_BULL_CD12", "mode": "expanded", "cooldown": 12.0, "guard": "legacy_no_bull"},
    {"name": "CAL4_EXP_LEGACY_CONTEXT_CD12", "mode": "expanded", "cooldown": 12.0, "guard": "legacy_strong_context"},
    {"name": "CAL4_EXP_LEGACY_FULL_GUARD_CD12", "mode": "expanded", "cooldown": 12.0, "guard": "legacy_full_guard"},
]


def apply_guard(
    run_dir: Path,
    validation_start: datetime,
    validation_end: datetime,
    guard: str,
) -> int:
    if guard == "none":
        return 0
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
        setup = str(row.get("setup_type") or source.get("setup_type") or "").lower()
        meta = reason_values(source.get("risk_plan_reason"))
        candle = meta.get("candle", "")
        alignment = meta.get("ctx_align", "")
        legacy = setup == "pullback"
        weak_context = alignment not in {"aligned", "h4_only"}

        should_block = False
        if guard == "legacy_no_bull":
            should_block = legacy and candle == "bull_impulse"
        elif guard == "legacy_strong_context":
            should_block = legacy and weak_context
        elif guard == "legacy_full_guard":
            should_block = legacy and (candle == "bull_impulse" or weak_context)
        elif guard == "all_strong_context":
            should_block = weak_context
        else:
            raise ValueError(f"unknown guard: {guard}")

        if should_block:
            row["allowed"] = "False"
            row["risk_pct"] = "0"
            row["reason"] = f"cal4_{guard}"
            blocked += 1
    v3.write_csv(decisions_path, decisions, fields)
    return blocked


def main() -> int:
    fold_index, _ = v3.read_csv(SOURCE / "fold_index.csv")
    folds_by_candidate: dict[str, list[dict[str, object]]] = {
        str(item["name"]): [] for item in VARIANTS
    }
    events_by_candidate: dict[str, list[dict[str, str]]] = {
        str(item["name"]): [] for item in VARIANTS
    }

    variants_by_mode: dict[str, list[dict[str, object]]] = {"aggressive": [], "expanded": []}
    for item in VARIANTS:
        variants_by_mode[str(item["mode"])].append(item)

    for fold_row in fold_index:
        fold = fold_row["fold"]
        warmup_start = parse_dt(fold_row["warmup_start"])
        validation_start = parse_dt(fold_row["validation_start"])
        validation_end = parse_dt(fold_row["validation_end"])
        pool_path = SOURCE / "folds" / fold / "pool" / "generated_trades.csv"
        pool_rows, pool_fields = v3.read_csv(pool_path)

        for mode, mode_variants in variants_by_mode.items():
            template_spec = threshold_spec(f"CAL4_{mode.upper()}_TEMPLATE", mode)
            template_dir = OUT / "templates" / fold / mode
            selected = base.filtered_pool(pool_rows, float(template_spec["min_confidence"]))
            generated_path = template_dir / "generated_trades.csv"
            v3.write_csv(generated_path, selected, pool_fields)
            template_cfg = base.config_for(template_spec, warmup_start, validation_end)
            run_pipeline(generated_path, template_dir, cfg=template_cfg, profile_name=PROFILE)

            for item in mode_variants:
                name = str(item["name"])
                run_dir = OUT / "folds" / fold / name
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
                    "threshold_mode": mode,
                    "guard": item["guard"],
                    "cooldown_hours": item["cooldown"],
                    "status": "OK",
                }
                try:
                    guard_blocked = apply_guard(
                        run_dir,
                        validation_start,
                        validation_end,
                        str(item["guard"]),
                    )
                    cooldown_blocked = v3.apply_symbol_cooldown(
                        run_dir,
                        validation_start,
                        validation_end,
                        float(item["cooldown"]),
                    )
                    summary = evaluate_validation_window(
                        run_dir,
                        validation_start,
                        validation_end,
                        PROFILE,
                        cfg,
                    )
                    events = v3.close_events(run_dir)
                    row.update(asdict(summary))
                    row.update(pnl_totals(events))
                    row["guard_blocked"] = guard_blocked
                    row["cooldown_blocked"] = cooldown_blocked
                    events_by_candidate[name].extend(events)
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
                folds_by_candidate[name].append(row)
                print(
                    f"{name} {fold}: trades={row.get('executed_trades', 0)} "
                    f"ret={row.get('ret_pct', 0)} guard={row.get('guard_blocked', 0)} "
                    f"cooldown={row.get('cooldown_blocked', 0)}",
                    flush=True,
                )

    aggregates = [aggregate_oos(name, rows) for name, rows in folds_by_candidate.items()]
    aggregates.sort(key=lambda row: float(row["score"]), reverse=True)
    leader_name = str(aggregates[0]["name"]) if aggregates else ""
    result = {
        "mode": "CAL4_SCREENING_ONLY_REQUIRES_EXTERNAL_HOLDOUT",
        "source": str(SOURCE),
        "folds": len(fold_index),
        "pipeline_runs": len(fold_index) * len(variants_by_mode),
        "variants": len(VARIANTS),
        "leader": aggregates[0] if aggregates else {},
        "candidates": aggregates,
        "leader_diagnostics": v3.category_summary(events_by_candidate.get(leader_name, [])),
        "acceptance_note": "No candidate may be promoted from this screening set without a separate external period or symbol holdout.",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    v3.write_csv(OUT / "candidate_summary.csv", aggregates)
    for name, rows in folds_by_candidate.items():
        v3.write_csv(OUT / "candidate_folds" / f"{name}.csv", rows)
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
