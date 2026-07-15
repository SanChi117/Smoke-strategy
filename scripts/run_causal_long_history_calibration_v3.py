#!/usr/bin/env python3
"""Cached strict-OOS pullback calibration with honest pooled PF and cooldowns.

The six chronological Binance Futures folds are frozen. This iteration varies only
causal decision thresholds and the minimum spacing between entries on the same
symbol. No future outcome is used to choose or suppress a candidate.

Research only. No API keys and no order execution.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

import run_causal_long_history_sweep as base
from strategy_lab.pipeline import run_pipeline
from strategy_lab.research_metrics import aggregate_oos, pnl_totals, safe_float
from strategy_lab.walk_forward_evaluation import (
    bool_value,
    causal_priority,
    evaluate_validation_window,
    parse_dt,
    reason_values,
    trade_key,
)

SOURCE = Path("results/causal_long_history_sweep_v1")
OUT = Path("results/causal_long_history_calibration_v3")
PROFILE = "research_500"
PULLBACK_FAMILY = ("pullback", "pullback_resumption", "pullback_resumption_strict")


def spec(name: str, cooldown_hours: float = 0.0, **overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "name": name,
        "cooldown_hours": cooldown_hours,
        "rolling_top_n": 8,
        "require_rolling_top": False,
        "require_universe_gate": False,
        "min_confidence": 40.0,
        "quality_take_threshold": 61.0,
        "quality_watch_threshold": 48.0,
        "structure_take_threshold": 60.0,
        "structure_watch_threshold": 48.0,
        "allowed_setup_types": PULLBACK_FAMILY,
        "blocked_setup_types": ("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim", "ignition"),
        "blocked_volatility_regimes": ("high",),
        "blocked_liquidity_states": ("high_sweep_reject",),
        "blocked_candle_types": ("bear_rejection",),
        "allowed_direction_contexts": ("down",),
        "min_volume_ratio": 0.60,
    }
    item.update(overrides)
    return item


CANDIDATES = [
    spec("CAL3_BASE_V2_LEADER"),
    spec(
        "CAL3_MEDIUM_NO_COOLDOWN",
        quality_take_threshold=59.0,
        quality_watch_threshold=46.0,
        structure_take_threshold=58.0,
        structure_watch_threshold=46.0,
        min_volume_ratio=0.55,
    ),
    spec(
        "CAL3_MEDIUM_CD4H",
        cooldown_hours=4.0,
        quality_take_threshold=59.0,
        quality_watch_threshold=46.0,
        structure_take_threshold=58.0,
        structure_watch_threshold=46.0,
        min_volume_ratio=0.55,
    ),
    spec(
        "CAL3_MEDIUM_CD8H",
        cooldown_hours=8.0,
        quality_take_threshold=59.0,
        quality_watch_threshold=46.0,
        structure_take_threshold=58.0,
        structure_watch_threshold=46.0,
        min_volume_ratio=0.55,
    ),
    spec(
        "CAL3_MEDIUM_CD12H",
        cooldown_hours=12.0,
        quality_take_threshold=59.0,
        quality_watch_threshold=46.0,
        structure_take_threshold=58.0,
        structure_watch_threshold=46.0,
        min_volume_ratio=0.55,
    ),
    spec(
        "CAL3_MEDIUM_CD24H",
        cooldown_hours=24.0,
        quality_take_threshold=59.0,
        quality_watch_threshold=46.0,
        structure_take_threshold=58.0,
        structure_watch_threshold=46.0,
        min_volume_ratio=0.55,
    ),
    spec(
        "CAL3_AGGRESSIVE_CD8H",
        cooldown_hours=8.0,
        quality_take_threshold=57.0,
        quality_watch_threshold=44.0,
        structure_take_threshold=56.0,
        structure_watch_threshold=44.0,
        min_volume_ratio=0.50,
    ),
    spec(
        "CAL3_AGGRESSIVE_CD12H",
        cooldown_hours=12.0,
        quality_take_threshold=57.0,
        quality_watch_threshold=44.0,
        structure_take_threshold=56.0,
        structure_watch_threshold=44.0,
        min_volume_ratio=0.50,
    ),
]


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists() or path.stat().st_size == 0:
        return [], []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = fields or (list(rows[0].keys()) if rows else [])
    if not names:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def apply_symbol_cooldown(
    run_dir: Path,
    validation_start: datetime,
    validation_end: datetime,
    cooldown_hours: float,
) -> int:
    if cooldown_hours <= 0:
        return 0
    decisions_path = run_dir / "pipeline_decisions.csv"
    generated_path = run_dir / "generated_trades.csv"
    decisions, fields = read_csv(decisions_path)
    generated, _ = read_csv(generated_path)
    generated_by_key = {
        trade_key(row.get("symbol"), row.get("side"), row.get("entry_time")): row
        for row in generated
    }
    ranked: list[tuple[datetime, float, str, int]] = []
    for index, row in enumerate(decisions):
        entry_time = parse_dt(row.get("entry_time"))
        if not (validation_start <= entry_time < validation_end):
            continue
        if not bool_value(row.get("allowed")):
            continue
        key = trade_key(row.get("symbol"), row.get("side"), row.get("entry_time"))
        score = causal_priority(row, generated_by_key.get(key, {}))
        ranked.append((entry_time, -score, str(row.get("symbol", "")).upper(), index))

    spacing = timedelta(hours=cooldown_hours)
    last_kept: dict[str, datetime] = {}
    blocked = 0
    for entry_time, _negative_score, symbol, index in sorted(ranked):
        previous = last_kept.get(symbol)
        if previous is not None and entry_time - previous < spacing:
            decisions[index]["allowed"] = "False"
            decisions[index]["risk_pct"] = "0"
            decisions[index]["reason"] = f"symbol_cooldown_{cooldown_hours:g}h"
            blocked += 1
            continue
        last_kept[symbol] = entry_time
    write_csv(decisions_path, decisions, fields)
    return blocked


def close_events(run_dir: Path) -> list[dict[str, str]]:
    rows, _ = read_csv(run_dir / "walk_forward_portfolio_audit.csv")
    return [row for row in rows if str(row.get("event", "")).upper() == "CLOSE"]


def category_summary(events: list[dict[str, str]]) -> dict[str, list[dict[str, object]]]:
    dimensions = ("symbol", "setup_type", "candle_type", "context_alignment", "liquidity_state")
    output: dict[str, list[dict[str, object]]] = {}
    for dimension in dimensions:
        grouped: dict[str, list[float]] = defaultdict(list)
        for row in events:
            grouped[str(row.get(dimension) or "unknown")].append(safe_float(row.get("net_pnl"), 0.0))
        values = []
        for key, pnl_values in grouped.items():
            values.append({
                "value": key,
                "trades": len(pnl_values),
                "wins": sum(1 for value in pnl_values if value > 0),
                "losses": sum(1 for value in pnl_values if value < 0),
                "net_pnl": round(sum(pnl_values), 6),
            })
        values.sort(key=lambda row: (float(row["net_pnl"]), int(row["trades"])))
        output[dimension] = values

    volume_groups: dict[str, list[float]] = defaultdict(list)
    for row in events:
        volume = safe_float(row.get("volume_ratio"), 0.0)
        if volume < 0.75:
            bucket = "lt_0.75"
        elif volume < 1.0:
            bucket = "0.75_1.0"
        elif volume < 1.5:
            bucket = "1.0_1.5"
        elif volume < 2.0:
            bucket = "1.5_2.0"
        else:
            bucket = "gte_2.0"
        volume_groups[bucket].append(safe_float(row.get("net_pnl"), 0.0))
    output["volume_bucket"] = [
        {
            "value": key,
            "trades": len(values),
            "wins": sum(1 for value in values if value > 0),
            "losses": sum(1 for value in values if value < 0),
            "net_pnl": round(sum(values), 6),
        }
        for key, values in sorted(volume_groups.items())
    ]
    return output


def main() -> int:
    fold_index, _ = read_csv(SOURCE / "fold_index.csv")
    folds_by_candidate: dict[str, list[dict[str, object]]] = {str(item["name"]): [] for item in CANDIDATES}
    events_by_candidate: dict[str, list[dict[str, str]]] = {str(item["name"]): [] for item in CANDIDATES}

    for fold_row in fold_index:
        fold = fold_row["fold"]
        warmup_start = parse_dt(fold_row["warmup_start"])
        validation_start = parse_dt(fold_row["validation_start"])
        validation_end = parse_dt(fold_row["validation_end"])
        pool_path = SOURCE / "folds" / fold / "pool" / "generated_trades.csv"
        pool_rows, pool_fields = read_csv(pool_path)

        for item in CANDIDATES:
            name = str(item["name"])
            run_dir = OUT / "folds" / fold / name
            selected = base.filtered_pool(pool_rows, float(item["min_confidence"]))
            generated_path = run_dir / "generated_trades.csv"
            write_csv(generated_path, selected, pool_fields)
            cfg = base.config_for(item, warmup_start, validation_end)
            row: dict[str, object] = {
                "fold": fold,
                "validation_start": validation_start.isoformat(),
                "validation_end": validation_end.isoformat(),
                "cooldown_hours": item["cooldown_hours"],
                "status": "OK",
            }
            try:
                run_pipeline(generated_path, run_dir, cfg=cfg, profile_name=PROFILE)
                blocked = apply_symbol_cooldown(
                    run_dir,
                    validation_start,
                    validation_end,
                    float(item["cooldown_hours"]),
                )
                summary = evaluate_validation_window(run_dir, validation_start, validation_end, PROFILE, cfg)
                events = close_events(run_dir)
                totals = pnl_totals(events)
                row.update(asdict(summary))
                row.update(totals)
                row["cooldown_blocked"] = blocked
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
                f"ret={row.get('ret_pct', 0)} pooled_fold_pf={row.get('pooled_pf', 0)} "
                f"cooldown_blocked={row.get('cooldown_blocked', 0)}",
                flush=True,
            )

    aggregates = [aggregate_oos(name, rows) for name, rows in folds_by_candidate.items()]
    aggregates.sort(key=lambda row: float(row["score"]), reverse=True)
    leader_name = str(aggregates[0]["name"]) if aggregates else ""
    result = {
        "mode": "CACHED_STRICT_OOS_PULLBACK_CALIBRATION_V3_POOLED_PF",
        "source": str(SOURCE),
        "folds": len(fold_index),
        "leader": aggregates[0] if aggregates else {},
        "candidates": aggregates,
        "leader_diagnostics": category_summary(events_by_candidate.get(leader_name, [])),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "candidate_summary.csv", aggregates)
    for name, rows in folds_by_candidate.items():
        write_csv(OUT / "candidate_folds" / f"{name}.csv", rows)
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
