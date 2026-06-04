#!/usr/bin/env python3
"""Candle-to-trades research pipeline.

This is the first executable skeleton for the missing chain:

candles CSV -> data quality -> features -> candidate setups -> risk plans -> candle exits -> generated trades CSV

It does not prove profitability and does not connect to an exchange. It only
creates normalized research artifacts that can be fed into the integrated
trade pipeline.
"""

from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path

from strategy_lab.candle_exit_simulator import SimulatedExit, exit_to_trade, rows_as_dicts as exit_rows_as_dicts, simulate_plan_exits
from strategy_lab.candle_research_report import build_candle_research_report, rows_as_dicts as candle_report_rows_as_dicts
from strategy_lab.data_quality import DataQualityConfig, analyze_data_quality, rows_as_dicts as data_quality_rows_as_dicts
from strategy_lab.exit_diagnostics import build_exit_diagnostics, rows_as_dicts as exit_diagnostic_rows_as_dicts
from strategy_lab.feature_builder import build_features, rows_as_dicts as feature_rows_as_dicts
from strategy_lab.market_data import read_candles_csv, validate_candles
from strategy_lab.risk_model import RiskPlan, build_risk_plans, rows_as_dicts as risk_rows_as_dicts
from strategy_lab.setup_generator import generate_candidate_setups, rows_as_dicts as candidate_rows_as_dicts


def write_dict_csv(path: str | Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def trade_rows_from_plans(plans: list[RiskPlan], exits: list[SimulatedExit]) -> list[dict]:
    """Build a pipeline-ready generated trades CSV.

    The integrated pipeline needs the normalized trade columns, while the
    structure-learning layer benefits from optional context columns. Keeping
    the context here prevents the candle path from becoming blind again.
    """
    rows = []
    for plan, exit_result in zip(plans, exits):
        trade = exit_to_trade(plan, exit_result)
        row = asdict(trade)
        row["entry_time"] = trade.entry_time.isoformat(timespec="seconds") if hasattr(trade.entry_time, "isoformat") else str(trade.entry_time)
        row["exit_time"] = trade.exit_time.isoformat(timespec="seconds") if hasattr(trade.exit_time, "isoformat") else str(trade.exit_time)
        row["setup_type"] = plan.setup_type
        row["trend_context"] = plan.trend_context
        row["volatility_regime"] = plan.volatility_regime
        row["structure_type"] = plan.structure_type
        row["confidence_hint"] = plan.confidence_hint
        row["target_policy"] = plan.target_policy
        row["risk_grade"] = plan.risk_grade
        row["exit_reason"] = exit_result.exit_reason
        row["bars_held"] = exit_result.bars_held
        row["risk_plan_reason"] = plan.reason
        row["target_rr"] = plan.target_rr
        row["stop_pct"] = plan.stop_pct
        rows.append(row)
    return rows


def run_candle_pipeline(candles_csv: str | Path, out_dir: str | Path = "results", min_confidence: float = 50.0) -> dict[str, int]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    candles = read_candles_csv(candles_csv)
    quality_summary, quality_coverage, quality_issues = analyze_data_quality(candles, DataQualityConfig())
    write_dict_csv(out / "data_quality_summary.csv", data_quality_rows_as_dicts([quality_summary]))
    write_dict_csv(out / "data_quality_report.csv", data_quality_rows_as_dicts(quality_coverage))
    write_dict_csv(out / "data_quality_issues.csv", data_quality_rows_as_dicts(quality_issues))

    validate_candles(candles)
    features = build_features(candles)
    candidates = generate_candidate_setups(features, min_confidence=min_confidence)
    plans = build_risk_plans(candidates)
    exits = simulate_plan_exits(plans, candles)
    generated_trade_rows = trade_rows_from_plans(plans, exits)
    exit_diagnostics = build_exit_diagnostics(plans, exits)
    candle_report = build_candle_research_report(
        candles_count=len(candles),
        features=features,
        candidates=candidates,
        plans=plans,
        exits=exits,
        diagnostics=exit_diagnostics,
    )

    write_dict_csv(out / "candle_features.csv", feature_rows_as_dicts(features))
    write_dict_csv(out / "candidate_setups.csv", candidate_rows_as_dicts(candidates))
    write_dict_csv(out / "risk_plans.csv", risk_rows_as_dicts(plans))
    write_dict_csv(out / "candle_exit_results.csv", exit_rows_as_dicts(exits))
    write_dict_csv(out / "candle_exit_diagnostics.csv", exit_diagnostic_rows_as_dicts(exit_diagnostics))
    write_dict_csv(out / "candle_research_report.csv", candle_report_rows_as_dicts(candle_report))
    write_dict_csv(out / "generated_trades.csv", generated_trade_rows)

    return {
        "candles": len(candles),
        "data_quality_status": quality_summary.status,
        "data_quality_errors": quality_summary.errors,
        "data_quality_warnings": quality_summary.warnings,
        "features": len(features),
        "candidates": len(candidates),
        "risk_plans": len(plans),
        "exit_results": len(exits),
        "exit_diagnostics": len(exit_diagnostics),
        "candle_research_report": len(candle_report),
        "generated_trades": len(generated_trade_rows),
    }


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--candles", required=True)
    p.add_argument("--out-dir", default="results")
    p.add_argument("--min-confidence", type=float, default=50.0)
    args = p.parse_args()

    summary = run_candle_pipeline(args.candles, args.out_dir, min_confidence=args.min_confidence)
    print("Candle pipeline complete")
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
