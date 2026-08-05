#!/usr/bin/env python3
"""Optimized v3 calibration: one causal pipeline run per threshold group and fold."""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path

import run_causal_long_history_calibration_v3 as v3
import run_causal_long_history_sweep as base
from strategy_lab.pipeline import run_pipeline
from strategy_lab.research_metrics import aggregate_oos, pnl_totals
from strategy_lab.walk_forward_evaluation import evaluate_validation_window, parse_dt

SOURCE = v3.SOURCE
OUT = Path("results/causal_long_history_calibration_v3_fast")
PROFILE = v3.PROFILE

GROUPS = [
    (
        "base",
        v3.spec("CAL3_BASE_V2_LEADER"),
        [("CAL3_BASE_V2_LEADER", 0.0)],
    ),
    (
        "medium",
        v3.spec(
            "CAL3_MEDIUM_TEMPLATE",
            quality_take_threshold=59.0,
            quality_watch_threshold=46.0,
            structure_take_threshold=58.0,
            structure_watch_threshold=46.0,
            min_volume_ratio=0.55,
        ),
        [
            ("CAL3_MEDIUM_NO_COOLDOWN", 0.0),
            ("CAL3_MEDIUM_CD4H", 4.0),
            ("CAL3_MEDIUM_CD8H", 8.0),
            ("CAL3_MEDIUM_CD12H", 12.0),
            ("CAL3_MEDIUM_CD24H", 24.0),
        ],
    ),
    (
        "aggressive",
        v3.spec(
            "CAL3_AGGRESSIVE_TEMPLATE",
            quality_take_threshold=57.0,
            quality_watch_threshold=44.0,
            structure_take_threshold=56.0,
            structure_watch_threshold=44.0,
            min_volume_ratio=0.50,
        ),
        [
            ("CAL3_AGGRESSIVE_CD8H", 8.0),
            ("CAL3_AGGRESSIVE_CD12H", 12.0),
        ],
    ),
]


def main() -> int:
    fold_index, _ = v3.read_csv(SOURCE / "fold_index.csv")
    variant_names = [name for _group, _spec, variants in GROUPS for name, _hours in variants]
    folds_by_candidate: dict[str, list[dict[str, object]]] = {name: [] for name in variant_names}
    events_by_candidate: dict[str, list[dict[str, str]]] = {name: [] for name in variant_names}

    for fold_row in fold_index:
        fold = fold_row["fold"]
        warmup_start = parse_dt(fold_row["warmup_start"])
        validation_start = parse_dt(fold_row["validation_start"])
        validation_end = parse_dt(fold_row["validation_end"])
        pool_path = SOURCE / "folds" / fold / "pool" / "generated_trades.csv"
        pool_rows, pool_fields = v3.read_csv(pool_path)

        for group_name, group_spec, variants in GROUPS:
            template_dir = OUT / "templates" / fold / group_name
            selected = base.filtered_pool(pool_rows, float(group_spec["min_confidence"]))
            generated_path = template_dir / "generated_trades.csv"
            v3.write_csv(generated_path, selected, pool_fields)
            template_cfg = base.config_for(group_spec, warmup_start, validation_end)
            run_pipeline(generated_path, template_dir, cfg=template_cfg, profile_name=PROFILE)

            for variant_name, cooldown_hours in variants:
                run_dir = OUT / "folds" / fold / variant_name
                run_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(template_dir / "generated_trades.csv", run_dir / "generated_trades.csv")
                shutil.copy2(template_dir / "pipeline_decisions.csv", run_dir / "pipeline_decisions.csv")
                variant_spec = dict(group_spec)
                variant_spec["name"] = variant_name
                variant_spec["cooldown_hours"] = cooldown_hours
                cfg = base.config_for(variant_spec, warmup_start, validation_end)
                row: dict[str, object] = {
                    "fold": fold,
                    "validation_start": validation_start.isoformat(),
                    "validation_end": validation_end.isoformat(),
                    "cooldown_hours": cooldown_hours,
                    "status": "OK",
                }
                try:
                    blocked = v3.apply_symbol_cooldown(
                        run_dir,
                        validation_start,
                        validation_end,
                        cooldown_hours,
                    )
                    summary = evaluate_validation_window(run_dir, validation_start, validation_end, PROFILE, cfg)
                    events = v3.close_events(run_dir)
                    row.update(asdict(summary))
                    row.update(pnl_totals(events))
                    row["cooldown_blocked"] = blocked
                    events_by_candidate[variant_name].extend(events)
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
                folds_by_candidate[variant_name].append(row)
                print(
                    f"{variant_name} {fold}: trades={row.get('executed_trades', 0)} "
                    f"ret={row.get('ret_pct', 0)} cooldown_blocked={row.get('cooldown_blocked', 0)}",
                    flush=True,
                )

    aggregates = [aggregate_oos(name, rows) for name, rows in folds_by_candidate.items()]
    aggregates.sort(key=lambda row: float(row["score"]), reverse=True)
    leader_name = str(aggregates[0]["name"]) if aggregates else ""
    result = {
        "mode": "CACHED_STRICT_OOS_PULLBACK_CALIBRATION_V3_FAST_POOLED_PF",
        "source": str(SOURCE),
        "pipeline_runs": len(fold_index) * len(GROUPS),
        "variants": len(variant_names),
        "folds": len(fold_index),
        "leader": aggregates[0] if aggregates else {},
        "candidates": aggregates,
        "leader_diagnostics": v3.category_summary(events_by_candidate.get(leader_name, [])),
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
