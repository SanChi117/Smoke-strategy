#!/usr/bin/env python3
"""Frozen external holdout for the refined dual-direction baseline.

Frozen rules:
- moderate causal Quality/Structure thresholds;
- dual LONG/SHORT pullback family;
- legacy_full guard;
- global 12-hour symbol cooldown;
- additional SHORT-only block when the entry candle type is neutral.

The period and rule set must not be changed after launch. Research only.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import run_binance_walk_forward as wfo
import run_causal_long_history_calibration_v3 as v3
import run_causal_long_history_sweep as base
import run_twelve_month_dual_direction_screening as dev
import run_twelve_month_short_refinement as short_ref
from strategy_lab.pipeline import run_pipeline
from strategy_lab.research_metrics import aggregate_oos, pnl_totals
from strategy_lab.walk_forward_evaluation import evaluate_validation_window, parse_dt


FROZEN_NAME = "FROZEN_DUAL_SHORT_NO_NEUTRAL_V1"


def external_gate(aggregate: dict[str, object], sides: dict[str, dict[str, object]]) -> str:
    long_stats = sides.get("long", {})
    short_stats = sides.get("short", {})

    pooled_pf_raw = aggregate.get("pooled_pf", 0.0)
    pooled_pf = 10.0 if pooled_pf_raw == "inf" else float(pooled_pf_raw)
    long_pf_raw = long_stats.get("pf", 0.0)
    long_pf = 10.0 if long_pf_raw == "inf" else float(long_pf_raw)
    short_pf_raw = short_stats.get("pf", 0.0)
    short_pf = 10.0 if short_pf_raw == "inf" else float(short_pf_raw)

    if (
        int(aggregate.get("total_trades", 0)) >= 30
        and int(aggregate.get("positive_folds", 0)) >= 4
        and pooled_pf >= 1.25
        and float(aggregate.get("avg_return_pct", 0.0)) > 0
        and float(aggregate.get("worst_fold_return_pct", 0.0)) > -2.0
        and float(aggregate.get("worst_dd_pct", 99.0)) <= 6.0
        and int(long_stats.get("trades", 0)) >= 12
        and int(short_stats.get("trades", 0)) >= 10
        and float(long_stats.get("net_pnl", 0.0)) > 0
        and float(short_stats.get("net_pnl", 0.0)) > 0
        and long_pf >= 1.20
        and short_pf >= 1.20
    ):
        return "PASS_EXTERNAL_HOLDOUT"

    if (
        int(aggregate.get("total_trades", 0)) >= 20
        and int(aggregate.get("positive_folds", 0)) >= 3
        and pooled_pf >= 1.10
        and float(aggregate.get("avg_return_pct", 0.0)) >= 0
        and float(aggregate.get("worst_dd_pct", 99.0)) <= 8.0
    ):
        return "WATCH_EXTERNAL_HOLDOUT"

    return "BLOCK_EXTERNAL_HOLDOUT"


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen external holdout for refined SHORT baseline")
    parser.add_argument("--candles", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--windows", type=int, default=6)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--profile", default="research_500")
    parser.add_argument("--pool-min-confidence", type=float, default=40.0)
    args = parser.parse_args()

    source = Path(args.candles)
    root = Path(args.out_dir)
    candle_rows, candle_fields = base.read_csv(source)
    if not candle_rows:
        raise RuntimeError("external holdout candle source is empty")

    times = [parse_dt(row["time"]) for row in candle_rows]
    windows = wfo.make_windows(min(times), max(times), args.lookback_days, args.windows)
    if len(windows) != args.windows:
        raise RuntimeError(f"expected {args.windows} folds, got {len(windows)}")

    fold_rows = []
    all_events: list[dict[str, str]] = []

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

        spec = dev.threshold_spec(FROZEN_NAME, "moderate")
        selected = base.filtered_pool(pool_rows, float(spec["min_confidence"]))
        run_dir = fold_root / "frozen"
        generated_path = run_dir / "generated_trades.csv"
        base.write_csv(generated_path, selected, pool_fields)

        cfg = base.config_for(spec, warmup_start, validation_end)
        run_pipeline(generated_path, run_dir, cfg=cfg, profile_name=args.profile)

        row: dict[str, object] = {
            "fold": fold,
            "validation_start": validation_start.isoformat(),
            "validation_end": validation_end.isoformat(),
            "status": "OK",
            "frozen_name": FROZEN_NAME,
        }

        try:
            legacy_blocked = dev.apply_variant_filter(
                run_dir,
                validation_start,
                validation_end,
                "dual",
                "legacy_full",
            )
            short_neutral_blocked = short_ref.apply_short_guard(
                run_dir,
                validation_start,
                validation_end,
                "no_neutral",
            )
            cooldown_blocked = v3.apply_symbol_cooldown(
                run_dir,
                validation_start,
                validation_end,
                12.0,
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
            row["legacy_blocked"] = legacy_blocked
            row["short_neutral_blocked"] = short_neutral_blocked
            row["cooldown_blocked"] = cooldown_blocked
            all_events.extend(close_rows)
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

        fold_rows.append(row)
        print(
            f"{FROZEN_NAME} {fold}: trades={row.get('executed_trades', 0)} "
            f"ret={row.get('ret_pct', 0)}",
            flush=True,
        )

    aggregate = aggregate_oos(FROZEN_NAME, fold_rows)
    sides = dev.side_summary(all_events)
    verdict = external_gate(aggregate, sides)
    aggregate["external_gate"] = verdict
    aggregate["side_summary"] = sides

    long_events = [
        row for row in all_events
        if str(row.get("side") or "").lower() == "long"
    ]
    short_events = [
        row for row in all_events
        if str(row.get("side") or "").lower() == "short"
    ]

    result = {
        "mode": "FROZEN_EXTERNAL_HOLDOUT",
        "frozen_baseline": FROZEN_NAME,
        "period_start": min(times).isoformat(),
        "period_end": max(times).isoformat(),
        "windows": args.windows,
        "lookback_days": args.lookback_days,
        "rules": {
            "threshold": "moderate",
            "mode": "dual",
            "guard": "legacy_full",
            "global_symbol_cooldown_hours": 12.0,
            "short_neutral_entry_block": True,
        },
        "result": aggregate,
        "diagnostics": {
            "sides": sides,
            "short_categories": v3.category_summary(short_events),
            "long_categories": v3.category_summary(long_events),
            "all_categories": v3.category_summary(all_events),
        },
        "promotion_allowed": verdict == "PASS_EXTERNAL_HOLDOUT",
        "next_required_step": (
            "If PASS: run final full causal paper review with this frozen baseline. "
            "If WATCH/BLOCK: do not tune on this holdout; return to development with a new hypothesis."
        ),
    }

    root.mkdir(parents=True, exist_ok=True)
    base.write_csv(root / "folds.csv", fold_rows)
    if all_events:
        base.write_csv(root / "all_trades.csv", all_events)
    if short_events:
        base.write_csv(root / "short_trades.csv", short_events)
    if long_events:
        base.write_csv(root / "long_trades.csv", long_events)
    (root / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
