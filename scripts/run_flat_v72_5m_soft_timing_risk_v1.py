#!/usr/bin/env python3
"""Strict-OOS Flat v7.2 5m soft timing/risk development study.

Exactly one baseline and four preregistered soft overlays are compared. No
candidate rejects a valid 15m signal. External holdout is forbidden here.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_binance_walk_forward as wfo  # noqa: E402
import run_causal_long_history_calibration_v3 as v3  # noqa: E402
import run_flat_v72_causal_screening_v1 as flat_base  # noqa: E402
from strategy_lab.flat_v72 import FlatV72Config, generate_flat_v72_plans  # noqa: E402
from strategy_lab.flat_v72_5m import SPECS, build_overlay_rows, resample_complete_5m_to_15m  # noqa: E402
from strategy_lab.market_data import read_candles_csv, validate_candles  # noqa: E402
from strategy_lab.pipeline import run_pipeline  # noqa: E402
from strategy_lab.research_metrics import aggregate_oos, pnl_totals, safe_float  # noqa: E402
from strategy_lab.walk_forward_evaluation import (  # noqa: E402
    bool_value,
    evaluate_validation_window,
    parse_dt,
    trade_key,
)


BASE_CONFIG = FlatV72Config(
    name="FLAT72_15M_BASELINE_CONTROL",
    max_holding_bars=96,
)


def apply_risk_multipliers(run_dir: Path) -> dict[str, int]:
    decisions_path = run_dir / "pipeline_decisions.csv"
    generated_path = run_dir / "generated_trades.csv"
    decisions, fields = v3.read_csv(decisions_path)
    generated, _ = v3.read_csv(generated_path)
    by_key = {
        trade_key(row.get("symbol"), row.get("side"), row.get("entry_time")): row
        for row in generated
    }
    counts: dict[str, int] = defaultdict(int)
    for row in decisions:
        key = trade_key(row.get("symbol"), row.get("side"), row.get("entry_time"))
        source = by_key.get(key, {})
        state = str(source.get("micro_state") or "missing")
        multiplier = safe_float(source.get("risk_multiplier"), 1.0)
        counts[state] += 1
        if not bool_value(row.get("allowed")):
            continue
        original = safe_float(row.get("risk_pct"), 0.0)
        row["risk_pct"] = str(round(original * multiplier, 8))
        row["reason"] = str(row.get("reason") or "") + f"|micro_state={state}|risk_multiplier={multiplier:.4f}"
    v3.write_csv(decisions_path, decisions, fields)
    return dict(sorted(counts.items()))


def development_gate(aggregate: dict[str, object], baseline_trades: int) -> str:
    pf_value = aggregate.get("pooled_pf", 0.0)
    pooled_pf = 10.0 if pf_value == "inf" else float(pf_value)
    valid = int(aggregate.get("valid_folds", 0))
    positive = int(aggregate.get("positive_folds", 0))
    trades = int(aggregate.get("total_trades", 0))
    avg_return = float(aggregate.get("avg_return_pct", 0.0))
    worst_dd = float(aggregate.get("worst_dd_pct", 99.0))
    count_ok = baseline_trades > 0 and trades >= baseline_trades
    if (
        valid == 10
        and positive >= 6
        and pooled_pf >= 1.20
        and avg_return > 0
        and worst_dd <= 8.0
        and count_ok
    ):
        return "PASS_DEVELOPMENT_SCREEN"
    if (
        valid == 10
        and positive >= 5
        and pooled_pf >= 1.10
        and avg_return > 0
        and worst_dd <= 10.0
        and count_ok
    ):
        return "WATCH_DEVELOPMENT"
    return "BLOCK_DEVELOPMENT"


def main() -> int:
    parser = argparse.ArgumentParser(description="Flat v7.2 causal 5m soft timing/risk study")
    parser.add_argument("--candles-5m", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--windows", type=int, default=10)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--profile", default="research_500")
    args = parser.parse_args()

    root = Path(args.out_dir)
    root.mkdir(parents=True, exist_ok=True)
    micro = read_candles_csv(args.candles_5m)
    validate_candles(micro)
    if not micro:
        raise RuntimeError("5m candle source is empty")
    base_candles = resample_complete_5m_to_15m(micro)
    validate_candles(base_candles)
    if not base_candles:
        raise RuntimeError("complete 15m reconstruction is empty")

    base_times = [row.time for row in base_candles]
    windows = wfo.make_windows(min(base_times), max(base_times), args.lookback_days, args.windows)
    if len(windows) != args.windows:
        raise RuntimeError(f"expected {args.windows} folds, got {len(windows)}")

    folds_by_candidate: dict[str, list[dict[str, object]]] = {spec.name: [] for spec in SPECS}
    events_by_candidate: dict[str, list[dict[str, str]]] = {spec.name: [] for spec in SPECS}
    overlay_rows: list[dict[str, object]] = []

    for fold_no, (warmup_start, validation_start, validation_end) in enumerate(windows, start=1):
        fold = f"fold_{fold_no:02d}"
        fold_base = [row for row in base_candles if warmup_start <= row.time < validation_end]
        fold_micro = [row for row in micro if warmup_start <= row.time < validation_end]
        plans, plan_summary = generate_flat_v72_plans(fold_base, BASE_CONFIG)

        for spec in SPECS:
            run_dir = root / "folds" / fold / "candidates" / spec.name
            run_dir.mkdir(parents=True, exist_ok=True)
            rows, overlay = build_overlay_rows(plans, fold_micro, spec)
            flat_base.write_csv(run_dir / "generated_trades.csv", rows)
            overlay_rows.append({
                "fold": fold,
                "candidate": spec.name,
                "validation_start": validation_start.isoformat(),
                "validation_end": validation_end.isoformat(),
                "base_plans": int(plan_summary.get("plans", 0)),
                "generated_trades": len(rows),
                "overlay_counts": json.dumps(overlay.get("counts", {}), sort_keys=True),
            })
            result_row: dict[str, object] = {
                "fold": fold,
                "validation_start": validation_start.isoformat(),
                "validation_end": validation_end.isoformat(),
                "candidate": spec.name,
                "status": "OK",
            }
            try:
                if not rows:
                    raise RuntimeError("no generated 5m overlay trades in fold")
                cfg = flat_base.pipeline_config(spec.name, "soft", warmup_start, validation_end)
                run_pipeline(run_dir / "generated_trades.csv", run_dir, cfg=cfg, profile_name=args.profile)
                risk_states = apply_risk_multipliers(run_dir)
                summary = evaluate_validation_window(
                    run_dir, validation_start, validation_end, args.profile, cfg
                )
                close_rows = v3.close_events(run_dir)
                result_row.update(asdict(summary))
                result_row.update(pnl_totals(close_rows))
                result_row["risk_state_counts"] = json.dumps(risk_states, sort_keys=True)
                events_by_candidate[spec.name].extend(close_rows)
            except Exception as exc:
                result_row["status"] = "ERROR"
                result_row["error"] = f"{type(exc).__name__}: {exc}"
            folds_by_candidate[spec.name].append(result_row)

    aggregates = [aggregate_oos(spec.name, folds_by_candidate[spec.name]) for spec in SPECS]
    baseline = next(
        (row for row in aggregates if row.get("name") == "FLAT72_15M_BASELINE_CONTROL"),
        {},
    )
    baseline_trades = int(baseline.get("total_trades", 0))
    by_spec = {spec.name: spec for spec in SPECS}
    for row in aggregates:
        row["baseline_total_trades"] = baseline_trades
        row["trade_count_ok"] = int(row.get("total_trades", 0)) >= baseline_trades > 0
        row["development_gate"] = development_gate(row, baseline_trades)
        spec = by_spec[str(row["name"])]
        row["risk_by_state"] = {
            "supportive": spec.risk_supportive,
            "neutral": spec.risk_neutral,
            "adverse": spec.risk_adverse,
            "missing": spec.risk_missing,
        }
        row["delay_one_5m_if_adverse"] = spec.delay_one_5m_if_adverse
        flat_base.write_csv(root / "candidate_folds" / f"{spec.name}.csv", folds_by_candidate[spec.name])

    passes = [row for row in aggregates if row.get("development_gate") == "PASS_DEVELOPMENT_SCREEN"]
    passes.sort(
        key=lambda row: (
            -(10.0 if row.get("pooled_pf") == "inf" else float(row.get("pooled_pf", 0.0))),
            float(row.get("worst_dd_pct", 99.0)),
            -float(row.get("positive_pct", 0.0)),
            str(row.get("name")),
        )
    )
    selected = passes[0] if passes else None
    aggregates.sort(key=lambda row: float(row.get("score", -999.0)), reverse=True)

    result = {
        "mode": "FLAT_V72_5M_SOFT_TIMING_RISK_V1",
        "period_start": min(base_times).isoformat(),
        "period_end": max(base_times).isoformat(),
        "windows": args.windows,
        "lookback_days": args.lookback_days,
        "base_5m_candles": len(micro),
        "rebuilt_15m_candles": len(base_candles),
        "baseline_total_trades": baseline_trades,
        "selected_for_holdout": selected,
        "candidates": aggregates,
        "promotion_allowed": False,
        "external_holdout_touched": False,
        "next_required_step": (
            "If selected_for_holdout is non-null, freeze exactly that candidate and run one untouched external holdout. "
            "Otherwise stop 5m tuning on this period and proceed to preregistered causal symbol/sector ranking."
        ),
        "limitations": [
            "This is development data already used by prior Flat studies.",
            "5m is a soft timing/risk overlay only; no valid 15m signal is hard-blocked.",
            "No additional 5m candidates may be added after viewing this result.",
        ],
    }
    (root / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    flat_base.write_csv(root / "candidate_summary.csv", aggregates)
    flat_base.write_csv(
        root / "fold_summary.csv",
        [row for spec in SPECS for row in folds_by_candidate[spec.name]],
    )
    flat_base.write_csv(root / "overlay_summary.csv", overlay_rows)
    print(json.dumps({
        "selected_for_holdout": selected.get("name") if selected else None,
        "best_candidate": aggregates[0].get("name") if aggregates else None,
        "best_gate": aggregates[0].get("development_gate") if aggregates else None,
        "best_pooled_pf": aggregates[0].get("pooled_pf") if aggregates else None,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
