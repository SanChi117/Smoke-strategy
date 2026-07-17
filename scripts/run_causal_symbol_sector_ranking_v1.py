#!/usr/bin/env python3
"""Strict-OOS causal symbol/sector ranking development study.

The frozen Flat v7.2 soft baseline is the common signal generator. Ranking uses
only completed shadow outcomes available before each new entry. No external
holdout is touched and no candidate may be added after results are viewed.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_binance_walk_forward as wfo  # noqa: E402
import run_causal_long_history_calibration_v3 as v3  # noqa: E402
import run_flat_v72_causal_screening_v1 as flat_base  # noqa: E402
from strategy_lab.causal_symbol_sector_ranking import (  # noqa: E402
    POLICIES,
    annotate_rankings,
    apply_policy,
    load_sector_map,
    safe_float,
)
from strategy_lab.flat_v72 import (  # noqa: E402
    FlatV72Config,
    generate_flat_v72_plans,
    simulate_flat_v72_rows,
)
from strategy_lab.market_data import read_candles_csv, validate_candles  # noqa: E402
from strategy_lab.pipeline import run_pipeline  # noqa: E402
from strategy_lab.research_metrics import aggregate_oos, pnl_totals  # noqa: E402
from strategy_lab.walk_forward_evaluation import (  # noqa: E402
    bool_value,
    evaluate_validation_window,
    trade_key,
)


ACTIVE_POLICIES = tuple(
    policy for policy in POLICIES if policy.mode != "hybrid_priority"
)
BASE_CONFIG = FlatV72Config(
    name="FLAT72_RANKING_BASELINE_CONTROL",
    max_holding_bars=96,
)


def text_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def apply_ranking_decisions(run_dir: Path) -> dict[str, object]:
    """Apply the preregistered risk/block policy after causal pipeline scoring."""
    decisions_path = run_dir / "pipeline_decisions.csv"
    generated_path = run_dir / "generated_trades.csv"
    decisions, fields = v3.read_csv(decisions_path)
    generated, _ = v3.read_csv(generated_path)
    generated_by_key = {
        trade_key(
            row.get("symbol"),
            row.get("side"),
            row.get("entry_time"),
        ): row
        for row in generated
    }
    states: Counter[str] = Counter()
    blocked = 0
    adjusted = 0
    multipliers: list[float] = []
    missing_sources = 0

    for decision in decisions:
        key = trade_key(
            decision.get("symbol"),
            decision.get("side"),
            decision.get("entry_time"),
        )
        source = generated_by_key.get(key)
        if source is None:
            missing_sources += 1
            continue
        state = str(source.get("ranking_state") or "missing")
        states[state] += 1
        multiplier = safe_float(source.get("risk_multiplier"), 1.0)
        rank_block = text_bool(source.get("ranking_block"))
        multipliers.append(multiplier)
        if not bool_value(decision.get("allowed")):
            continue
        reason = str(decision.get("reason") or "")
        if rank_block:
            decision["allowed"] = "False"
            decision["reason"] = (
                reason
                + f"|ranking_policy={source.get('ranking_policy')}"
                + f"|ranking_state={state}|ranking_block=true"
            )
            blocked += 1
            continue
        original = safe_float(decision.get("risk_pct"), 0.0)
        decision["risk_pct"] = str(round(original * multiplier, 8))
        decision["reason"] = (
            reason
            + f"|ranking_policy={source.get('ranking_policy')}"
            + f"|ranking_state={state}"
            + f"|ranking_risk_multiplier={multiplier:.4f}"
        )
        adjusted += 1

    v3.write_csv(decisions_path, decisions, fields)
    return {
        "state_counts": dict(sorted(states.items())),
        "blocked_allowed_signals": blocked,
        "risk_adjusted_allowed_signals": adjusted,
        "avg_risk_multiplier": (
            round(sum(multipliers) / len(multipliers), 6)
            if multipliers
            else 0.0
        ),
        "missing_generated_sources": missing_sources,
    }


def development_gate(aggregate: dict[str, object]) -> str:
    pf_value = aggregate.get("pooled_pf", 0.0)
    pooled_pf = 10.0 if pf_value == "inf" else float(pf_value)
    valid = int(aggregate.get("valid_folds", 0))
    positive = int(aggregate.get("positive_folds", 0))
    trades = int(aggregate.get("total_trades", 0))
    avg_return = float(aggregate.get("avg_return_pct", 0.0))
    worst_dd = float(aggregate.get("worst_dd_pct", 99.0))
    if (
        valid == 10
        and trades >= 60
        and positive >= 6
        and pooled_pf >= 1.20
        and avg_return > 0.0
        and worst_dd <= 8.0
    ):
        return "PASS_DEVELOPMENT_SCREEN"
    if (
        valid == 10
        and trades >= 40
        and positive >= 5
        and pooled_pf >= 1.10
        and avg_return > 0.0
        and worst_dd <= 10.0
    ):
        return "WATCH_DEVELOPMENT"
    return "BLOCK_DEVELOPMENT"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Causal symbol/sector ranking development study"
    )
    parser.add_argument("--candles", required=True)
    parser.add_argument("--universe-manifest", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--windows", type=int, default=10)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--ranking-lookback-days", type=int, default=30)
    parser.add_argument("--profile", default="research_500")
    args = parser.parse_args()

    root = Path(args.out_dir)
    root.mkdir(parents=True, exist_ok=True)
    candles = read_candles_csv(args.candles)
    validate_candles(candles)
    if not candles:
        raise RuntimeError("ranking candle source is empty")

    manifest = json.loads(
        Path(args.universe_manifest).read_text(encoding="utf-8")
    )
    sector_map = load_sector_map(manifest)
    if not sector_map:
        raise RuntimeError("universe manifest has no symbol tags")

    times = [candle.time for candle in candles]
    windows = wfo.make_windows(
        min(times),
        max(times),
        args.lookback_days,
        args.windows,
    )
    if len(windows) != args.windows:
        raise RuntimeError(
            f"expected {args.windows} folds, got {len(windows)}"
        )

    folds_by_candidate: dict[str, list[dict[str, object]]] = {
        policy.name: [] for policy in ACTIVE_POLICIES
    }
    events_by_candidate: dict[str, list[dict[str, str]]] = {
        policy.name: [] for policy in ACTIVE_POLICIES
    }
    ranking_audit: list[dict[str, object]] = []
    generator_rows: list[dict[str, object]] = []

    for fold_no, (
        warmup_start,
        validation_start,
        validation_end,
    ) in enumerate(windows, start=1):
        fold = f"fold_{fold_no:02d}"
        fold_candles = [
            candle
            for candle in candles
            if warmup_start <= candle.time < validation_end
        ]
        plans, generator = generate_flat_v72_plans(
            fold_candles,
            BASE_CONFIG,
        )
        base_rows = simulate_flat_v72_rows(plans, fold_candles)
        if not base_rows:
            raise RuntimeError(f"no baseline ranking trades in {fold}")

        ranking_cfg = flat_base.pipeline_config(
            "FLAT72_RANKING_COST_REFERENCE",
            "soft",
            warmup_start,
            validation_end,
        )
        annotated = annotate_rankings(
            base_rows,
            sector_map,
            args.ranking_lookback_days,
            ranking_cfg.fee_rate,
            ranking_cfg.slippage_rate,
        )
        generator_rows.append({
            "fold": fold,
            "validation_start": validation_start.isoformat(),
            "validation_end": validation_end.isoformat(),
            "plans": int(generator.get("plans", 0)),
            "generated_trades": len(base_rows),
            "ranking_lookback_days": args.ranking_lookback_days,
            "reason_counts": json.dumps(
                generator.get("reason_counts", {}),
                sort_keys=True,
            ),
        })

        for policy in ACTIVE_POLICIES:
            run_dir = (
                root
                / "folds"
                / fold
                / "candidates"
                / policy.name
            )
            run_dir.mkdir(parents=True, exist_ok=True)
            policy_rows = apply_policy(annotated, policy)
            flat_base.write_csv(
                run_dir / "generated_trades.csv",
                policy_rows,
            )
            result_row: dict[str, object] = {
                "fold": fold,
                "validation_start": validation_start.isoformat(),
                "validation_end": validation_end.isoformat(),
                "candidate": policy.name,
                "policy_mode": policy.mode,
                "status": "OK",
            }
            try:
                pipe_cfg = flat_base.pipeline_config(
                    policy.name,
                    "soft",
                    warmup_start,
                    validation_end,
                )
                run_pipeline(
                    run_dir / "generated_trades.csv",
                    run_dir,
                    cfg=pipe_cfg,
                    profile_name=args.profile,
                )
                audit = apply_ranking_decisions(run_dir)
                summary = evaluate_validation_window(
                    run_dir,
                    validation_start,
                    validation_end,
                    args.profile,
                    pipe_cfg,
                )
                close_rows = v3.close_events(run_dir)
                result_row.update(asdict(summary))
                result_row.update(pnl_totals(close_rows))
                result_row["ranking_state_counts"] = json.dumps(
                    audit["state_counts"],
                    sort_keys=True,
                )
                result_row["ranking_blocked"] = int(
                    audit["blocked_allowed_signals"]
                )
                result_row["avg_risk_multiplier"] = float(
                    audit["avg_risk_multiplier"]
                )
                events_by_candidate[policy.name].extend(close_rows)
                ranking_audit.append({
                    "fold": fold,
                    "candidate": policy.name,
                    **audit,
                })
            except Exception as exc:
                result_row["status"] = "ERROR"
                result_row["error"] = (
                    f"{type(exc).__name__}: {exc}"
                )
            folds_by_candidate[policy.name].append(result_row)

    aggregates = [
        aggregate_oos(
            policy.name,
            folds_by_candidate[policy.name],
        )
        for policy in ACTIVE_POLICIES
    ]
    control = next(
        (
            row
            for row in aggregates
            if row.get("name") == "RANK_CONTROL_NO_OVERLAY"
        ),
        {},
    )
    control_trades = int(control.get("total_trades", 0))
    policy_by_name = {
        policy.name: policy for policy in ACTIVE_POLICIES
    }
    for row in aggregates:
        row["policy_mode"] = policy_by_name[str(row["name"])].mode
        row["development_gate"] = development_gate(row)
        row["control_total_trades"] = control_trades
        row["trade_retention_pct"] = (
            round(
                int(row.get("total_trades", 0))
                / control_trades
                * 100.0,
                4,
            )
            if control_trades > 0
            else 0.0
        )
        flat_base.write_csv(
            root / "candidate_folds" / f"{row['name']}.csv",
            folds_by_candidate[str(row["name"])],
        )

    passes = [
        row
        for row in aggregates
        if row.get("development_gate")
        == "PASS_DEVELOPMENT_SCREEN"
    ]
    passes.sort(
        key=lambda row: (
            -(
                10.0
                if row.get("pooled_pf") == "inf"
                else float(row.get("pooled_pf", 0.0))
            ),
            float(row.get("worst_dd_pct", 99.0)),
            -float(row.get("positive_pct", 0.0)),
            -int(row.get("total_trades", 0)),
            str(row.get("name")),
        )
    )
    selected = passes[0] if passes else None
    aggregates.sort(
        key=lambda row: float(row.get("score", -999.0)),
        reverse=True,
    )

    result = {
        "mode": "CAUSAL_SYMBOL_SECTOR_RANKING_V1",
        "period_start": min(times).isoformat(),
        "period_end": max(times).isoformat(),
        "windows": args.windows,
        "fold_lookback_days": args.lookback_days,
        "ranking_lookback_days": args.ranking_lookback_days,
        "shadow_book": (
            "all valid baseline signals, available only after exit"
        ),
        "control_total_trades": control_trades,
        "selected_for_holdout": selected,
        "candidates": aggregates,
        "promotion_allowed": False,
        "external_holdout_touched": False,
        "development_gate": {
            "pooled_pf_min": 1.20,
            "avg_return_gt": 0.0,
            "positive_folds_min": 6,
            "worst_dd_max": 8.0,
            "minimum_trades": 60,
        },
        "next_required_step": (
            "If selected_for_holdout is non-null, freeze exactly that policy "
            "and run one untouched external holdout. Otherwise stop ranking "
            "tuning on this period and proceed to separate LONG/SHORT regime "
            "families."
        ),
        "limitations": [
            "The underlying recovered Flat v7.2 entry family is already weak.",
            "Sector membership is frozen metadata, not a manually selected winner list.",
            "Filtered signals remain in a causal shadow book so future ranks are policy-independent.",
            "No additional ranking policies may be added after viewing this result.",
        ],
    }
    (root / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    flat_base.write_csv(root / "candidate_summary.csv", aggregates)
    flat_base.write_csv(
        root / "fold_summary.csv",
        [
            row
            for policy in ACTIVE_POLICIES
            for row in folds_by_candidate[policy.name]
        ],
    )
    flat_base.write_csv(root / "ranking_audit.csv", ranking_audit)
    flat_base.write_csv(root / "generator_summary.csv", generator_rows)
    print(json.dumps({
        "selected_for_holdout": (
            selected.get("name") if selected else None
        ),
        "best_candidate": (
            aggregates[0].get("name") if aggregates else None
        ),
        "best_gate": (
            aggregates[0].get("development_gate")
            if aggregates
            else None
        ),
        "best_pooled_pf": (
            aggregates[0].get("pooled_pf")
            if aggregates
            else None
        ),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
