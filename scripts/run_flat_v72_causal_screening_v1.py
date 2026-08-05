#!/usr/bin/env python3
"""Strict-OOS development screening for the recovered Flat v7.2 family.

This is a reconstruction test, not a promotion test. Unknown historical Pine
coefficients are held as explicit research assumptions and tested through a
small, predeclared A/B set. No external holdout is touched here.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_binance_walk_forward as wfo  # noqa: E402
import run_causal_long_history_calibration_v3 as v3  # noqa: E402
from strategy_lab.config import PipelineConfig  # noqa: E402
from strategy_lab.flat_v72 import (  # noqa: E402
    FlatV72Config,
    config_as_dict,
    generate_flat_v72_plans,
    simulate_flat_v72_rows,
)
from strategy_lab.market_data import read_candles_csv, validate_candles  # noqa: E402
from strategy_lab.pipeline import run_pipeline  # noqa: E402
from strategy_lab.research_metrics import aggregate_oos, pnl_totals, safe_float  # noqa: E402
from strategy_lab.walk_forward_evaluation import evaluate_validation_window  # noqa: E402


VARIANTS = [
    {
        "name": "FLAT72_RECOVERED_BASE_RAW",
        "learning": "raw",
        "config": FlatV72Config(name="FLAT72_RECOVERED_BASE_RAW"),
    },
    {
        "name": "FLAT72_RECOVERED_BASE_SOFT",
        "learning": "soft",
        "config": FlatV72Config(name="FLAT72_RECOVERED_BASE_SOFT"),
    },
    {
        "name": "FLAT72_NO_60M_FILTER_RAW",
        "learning": "raw",
        "config": FlatV72Config(name="FLAT72_NO_60M_FILTER_RAW", use_60m_trend_filter=False),
    },
    {
        "name": "FLAT72_FIXED_VOLUME_18_RAW",
        "learning": "raw",
        "config": FlatV72Config(
            name="FLAT72_FIXED_VOLUME_18_RAW",
            dynamic_volume=False,
            fixed_volume_multiplier=1.80,
        ),
    },
    {
        "name": "FLAT72_FIXED_RR17_RAW",
        "learning": "raw",
        "config": FlatV72Config(
            name="FLAT72_FIXED_RR17_RAW",
            use_structural_target=False,
            fixed_target_rr=1.70,
        ),
    },
    {
        "name": "FLAT72_RANGE_ONLY_RAW",
        "learning": "raw",
        "config": FlatV72Config(
            name="FLAT72_RANGE_ONLY_RAW",
            use_60m_trend_filter=False,
            use_15m_ema200_filter=False,
        ),
    },
]


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(fields or [])
    if not names:
        for row in rows:
            for key in row:
                if key not in names:
                    names.append(key)
    if not names:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def pipeline_config(name: str, learning: str, start, end) -> PipelineConfig:
    if learning == "raw":
        q_take = q_watch = s_take = s_watch = 0.0
    elif learning == "soft":
        q_take, q_watch, s_take, s_watch = 57.0, 44.0, 56.0, 44.0
    else:
        raise ValueError(f"unknown learning mode: {learning}")
    return replace(
        PipelineConfig(),
        name=name,
        start=start.date().isoformat(),
        end=(end + timedelta(days=1)).date().isoformat(),
        require_rolling_top=False,
        require_universe_gate=False,
        quality_take_threshold=q_take,
        quality_watch_threshold=q_watch,
        structure_take_threshold=s_take,
        structure_watch_threshold=s_watch,
        allowed_setup_types=("flat_v72",),
        blocked_setup_types=(),
        blocked_volatility_regimes=(),
        blocked_liquidity_states=(),
        blocked_candle_types=(),
        allowed_direction_contexts=(),
        min_volume_ratio=0.0,
    )


def development_gate(aggregate: dict[str, object]) -> str:
    pf_value = aggregate.get("pooled_pf", 0.0)
    pooled_pf = 10.0 if pf_value == "inf" else float(pf_value)
    valid = int(aggregate.get("valid_folds", 0))
    positive = int(aggregate.get("positive_folds", 0))
    trades = int(aggregate.get("total_trades", 0))
    avg_return = float(aggregate.get("avg_return_pct", 0.0))
    worst_fold = float(aggregate.get("worst_fold_return_pct", 0.0))
    worst_dd = float(aggregate.get("worst_dd_pct", 99.0))
    if (
        trades >= 60
        and positive >= max(1, int(valid * 0.60 + 0.9999))
        and pooled_pf >= 1.20
        and avg_return > 0
        and worst_fold > -2.5
        and worst_dd <= 8.0
    ):
        return "PASS_DEVELOPMENT_SCREEN"
    if (
        trades >= 30
        and positive >= max(1, int(valid * 0.50 + 0.9999))
        and pooled_pf >= 1.05
        and avg_return > 0
        and worst_dd <= 10.0
    ):
        return "WATCH_DEVELOPMENT"
    return "BLOCK_DEVELOPMENT"


def symbol_summary(events: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in events:
        grouped[str(row.get("symbol") or "UNKNOWN")].append(safe_float(row.get("net_pnl"), 0.0))
    output = []
    for symbol, values in grouped.items():
        output.append({
            "symbol": symbol,
            "trades": len(values),
            "wins": sum(1 for value in values if value > 0),
            "losses": sum(1 for value in values if value < 0),
            "net_pnl": round(sum(values), 6),
        })
    output.sort(key=lambda row: (float(row["net_pnl"]), int(row["trades"])))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Flat v7.2 causal development screening")
    parser.add_argument("--candles", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--windows", type=int, default=10)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--profile", default="research_500")
    args = parser.parse_args()

    source = Path(args.candles)
    root = Path(args.out_dir)
    root.mkdir(parents=True, exist_ok=True)
    candles = read_candles_csv(source)
    validate_candles(candles)
    if not candles:
        raise RuntimeError("Flat screening candle source is empty")
    times = [candle.time for candle in candles]
    windows = wfo.make_windows(min(times), max(times), args.lookback_days, args.windows)
    if len(windows) != args.windows:
        raise RuntimeError(f"expected {args.windows} folds, got {len(windows)}")

    folds_by_candidate: dict[str, list[dict[str, object]]] = {
        str(item["name"]): [] for item in VARIANTS
    }
    events_by_candidate: dict[str, list[dict[str, str]]] = {
        str(item["name"]): [] for item in VARIANTS
    }
    generator_rows: list[dict[str, object]] = []

    for fold_no, (warmup_start, validation_start, validation_end) in enumerate(windows, start=1):
        fold = f"fold_{fold_no:02d}"
        fold_candles = [
            candle for candle in candles
            if warmup_start <= candle.time < validation_end
        ]
        for item in VARIANTS:
            name = str(item["name"])
            learning = str(item["learning"])
            cfg = item["config"]
            run_dir = root / "folds" / fold / "candidates" / name
            run_dir.mkdir(parents=True, exist_ok=True)
            plans, generator = generate_flat_v72_plans(fold_candles, cfg)
            rows = simulate_flat_v72_rows(plans, fold_candles)
            write_csv(run_dir / "generated_trades.csv", rows)
            generator_rows.append({
                "fold": fold,
                "validation_start": validation_start.isoformat(),
                "validation_end": validation_end.isoformat(),
                "candidate": name,
                "learning": learning,
                "plans": int(generator.get("plans", 0)),
                "generated_trades": len(rows),
                "reason_counts": json.dumps(generator.get("reason_counts", {}), sort_keys=True),
            })
            row: dict[str, object] = {
                "fold": fold,
                "validation_start": validation_start.isoformat(),
                "validation_end": validation_end.isoformat(),
                "candidate": name,
                "learning": learning,
                "status": "OK",
            }
            try:
                if not rows:
                    raise RuntimeError("no generated Flat trades in fold")
                pipe_cfg = pipeline_config(name, learning, warmup_start, validation_end)
                run_pipeline(run_dir / "generated_trades.csv", run_dir, cfg=pipe_cfg, profile_name=args.profile)
                summary = evaluate_validation_window(
                    run_dir, validation_start, validation_end, args.profile, pipe_cfg
                )
                close_rows = v3.close_events(run_dir)
                row.update(asdict(summary))
                row.update(pnl_totals(close_rows))
                events_by_candidate[name].extend(close_rows)
            except Exception as exc:  # keep the remaining frozen variants auditable
                row["status"] = "ERROR"
                row["error"] = f"{type(exc).__name__}: {exc}"
            folds_by_candidate[name].append(row)

    candidates = []
    for item in VARIANTS:
        name = str(item["name"])
        aggregate = aggregate_oos(name, folds_by_candidate[name])
        aggregate["development_gate"] = development_gate(aggregate)
        aggregate["learning"] = item["learning"]
        aggregate["config"] = config_as_dict(item["config"])
        candidates.append(aggregate)
        write_csv(root / "candidate_folds" / f"{name}.csv", folds_by_candidate[name])
    candidates.sort(key=lambda row: float(row.get("score", -999.0)), reverse=True)
    leader = candidates[0] if candidates else {}
    leader_events = events_by_candidate.get(str(leader.get("name", "")), [])

    result = {
        "mode": "FLAT_V72_CAUSAL_SCREENING_V1",
        "period_start": min(times).isoformat(),
        "period_end": max(times).isoformat(),
        "windows": args.windows,
        "lookback_days": args.lookback_days,
        "variants": len(VARIANTS),
        "leader": leader,
        "candidates": candidates,
        "leader_symbol_diagnostics": symbol_summary(leader_events),
        "promotion_allowed": False,
        "next_required_step": (
            "If a candidate passes development, freeze exactly one configuration for an untouched external holdout. "
            "If all candidates block, proceed to the separate dynamic-target and 5m-soft packages without tuning on holdout."
        ),
        "limitations": [
            "The original full Flat v7.2 Pine source was not located.",
            "Width bands 3%/5%, fractal lookback 7, ATR stop reserves 0.45/0.65, strong impulse classifier and 24h time-stop are explicit research assumptions.",
            "This development period has already been used for screening and must never be treated as an external holdout.",
            "LONG-only recovered reference; no synthetic SHORT mirror is added in this test.",
        ],
    }
    (root / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_csv(root / "candidate_summary.csv", candidates)
    write_csv(
        root / "fold_summary.csv",
        [row for name in folds_by_candidate for row in folds_by_candidate[name]],
    )
    write_csv(root / "generator_summary.csv", generator_rows)
    print(json.dumps({
        "leader": leader.get("name"),
        "development_gate": leader.get("development_gate"),
        "pooled_pf": leader.get("pooled_pf"),
        "positive_folds": leader.get("positive_folds"),
        "trades": leader.get("total_trades"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
