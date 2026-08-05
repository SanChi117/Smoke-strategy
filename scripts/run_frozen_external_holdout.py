#!/usr/bin/env python3
"""Validate one frozen SMOKE baseline on a separate historical holdout.

This runner never selects between variants. It accepts exactly one baseline JSON,
replays causal Quality/Structure learning on each chronological fold, and reports
strict out-of-sample pooled metrics. The market period and baseline must be frozen
before the workflow starts.

Research only. No API keys and no order execution.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

import run_binance_walk_forward as wfo
import run_causal_long_history_calibration_v3 as v3
import run_causal_long_history_calibration_v4 as v4
import run_causal_long_history_sweep as base
from strategy_lab.pipeline import run_pipeline
from strategy_lab.research_metrics import aggregate_oos, pnl_totals
from strategy_lab.walk_forward_evaluation import evaluate_validation_window, parse_dt


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen strict-OOS external holdout")
    parser.add_argument("--candles", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--windows", type=int, default=6)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--profile", default="research_500")
    parser.add_argument("--pool-min-confidence", type=float, default=40.0)
    args = parser.parse_args()

    candle_source = Path(args.candles)
    baseline_path = Path(args.baseline)
    root = Path(args.out_dir)
    if not candle_source.exists() or candle_source.stat().st_size == 0:
        raise RuntimeError("external holdout candles are missing")
    if not baseline_path.exists() or baseline_path.stat().st_size == 0:
        raise RuntimeError("frozen baseline JSON is missing")

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    required = {
        "name", "min_confidence", "quality_take_threshold", "quality_watch_threshold",
        "structure_take_threshold", "structure_watch_threshold", "min_volume_ratio",
        "guard", "cooldown_hours",
    }
    missing = sorted(required - set(baseline))
    if missing:
        raise RuntimeError("frozen baseline missing fields: " + ", ".join(missing))

    candle_rows, candle_fields = base.read_csv(candle_source)
    if not candle_rows:
        raise RuntimeError("external holdout candle CSV is empty")
    times = [parse_dt(row["time"]) for row in candle_rows]
    windows = wfo.make_windows(min(times), max(times), args.lookback_days, args.windows)
    if len(windows) != args.windows:
        raise RuntimeError(f"expected {args.windows} folds, received {len(windows)}")

    fold_rows: list[dict[str, object]] = []
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
        pool_summary = base.generate_trade_pool(candles_path, pool_path, args.pool_min_confidence)
        pool_rows, pool_fields = base.read_csv(pool_path)
        selected = base.filtered_pool(pool_rows, float(baseline["min_confidence"]))
        run_dir = fold_root / "candidate"
        generated_path = run_dir / "generated_trades.csv"
        base.write_csv(generated_path, selected, pool_fields)

        spec = dict(baseline)
        spec.setdefault("rolling_top_n", 8)
        spec.setdefault("require_rolling_top", False)
        spec.setdefault("require_universe_gate", False)
        spec.setdefault("allowed_setup_types", ("pullback", "pullback_resumption", "pullback_resumption_strict"))
        spec.setdefault("blocked_setup_types", ("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim", "ignition"))
        spec.setdefault("blocked_volatility_regimes", ("high",))
        spec.setdefault("blocked_liquidity_states", ("high_sweep_reject",))
        spec.setdefault("blocked_candle_types", ("bear_rejection",))
        spec.setdefault("allowed_direction_contexts", ("down",))
        cfg = base.config_for(spec, warmup_start, validation_end)

        row: dict[str, object] = {
            "fold": fold,
            "warmup_start": warmup_start.isoformat(),
            "validation_start": validation_start.isoformat(),
            "validation_end": validation_end.isoformat(),
            "status": "OK",
            "pool_generated_trades": pool_summary.get("generated_trades", 0),
        }
        try:
            run_pipeline(generated_path, run_dir, cfg=cfg, profile_name=args.profile)
            guard_blocked = v4.apply_guard(
                run_dir,
                validation_start,
                validation_end,
                str(baseline["guard"]),
            )
            cooldown_blocked = v3.apply_symbol_cooldown(
                run_dir,
                validation_start,
                validation_end,
                float(baseline["cooldown_hours"]),
            )
            summary = evaluate_validation_window(
                run_dir,
                validation_start,
                validation_end,
                args.profile,
                cfg,
            )
            events = v3.close_events(run_dir)
            row.update(asdict(summary))
            row.update(pnl_totals(events))
            row["guard_blocked"] = guard_blocked
            row["cooldown_blocked"] = cooldown_blocked
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
            f"{fold}: status={row['status']} trades={row.get('executed_trades', 0)} "
            f"ret={row.get('ret_pct', 0)}",
            flush=True,
        )

    aggregate = aggregate_oos(str(baseline["name"]), fold_rows)
    result = {
        "mode": "FROZEN_EXTERNAL_HOLDOUT_STRICT_OOS",
        "baseline_file": str(baseline_path),
        "baseline": baseline,
        "candle_source": str(candle_source),
        "period_start": min(times).isoformat(),
        "period_end": max(times).isoformat(),
        "windows": args.windows,
        "lookback_days": args.lookback_days,
        "result": aggregate,
        "promotion_blocked_until_review": True,
    }
    root.mkdir(parents=True, exist_ok=True)
    base.write_csv(root / "fold_summary.csv", fold_rows)
    (root / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
