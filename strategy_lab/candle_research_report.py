#!/usr/bin/env python3
"""Compact candle research report.

Builds one high-level summary from the candle path so we do not need to open
five separate CSVs just to understand what happened.

Research only. No live trading.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Iterable

from strategy_lab.candle_exit_simulator import SimulatedExit
from strategy_lab.exit_diagnostics import ExitDiagnosticRow
from strategy_lab.feature_builder import MarketFeature
from strategy_lab.risk_model import RiskPlan
from strategy_lab.setup_generator import CandidateSetup


@dataclass(frozen=True)
class CandleResearchReportRow:
    metric: str
    value: str
    note: str


def fmt(value: float, digits: int = 4) -> str:
    return str(round(value, digits))


def top_group(rows: list[ExitDiagnosticRow], group: str, key: str = "avg_r", best: bool = True) -> ExitDiagnosticRow | None:
    candidates = [r for r in rows if r.group == group and r.trades > 0]
    if not candidates:
        return None
    if key == "trades":
        return sorted(candidates, key=lambda r: r.trades, reverse=best)[0]
    if key == "winrate":
        return sorted(candidates, key=lambda r: r.winrate, reverse=best)[0]
    return sorted(candidates, key=lambda r: r.avg_r, reverse=best)[0]


def build_candle_research_report(
    candles_count: int,
    features: Iterable[MarketFeature],
    candidates: Iterable[CandidateSetup],
    plans: Iterable[RiskPlan],
    exits: Iterable[SimulatedExit],
    diagnostics: Iterable[ExitDiagnosticRow],
) -> list[CandleResearchReportRow]:
    feature_rows = list(features)
    candidate_rows = list(candidates)
    plan_rows = list(plans)
    exit_rows = list(exits)
    diagnostic_rows = list(diagnostics)
    rs = [float(e.r_mult) for e in exit_rows]
    wins = sum(1 for r in rs if r > 0)
    all_diag = next((r for r in diagnostic_rows if r.group == "all" and r.value == "all"), None)

    rows: list[CandleResearchReportRow] = [
        CandleResearchReportRow("candles", str(candles_count), "Input OHLCV candle count."),
        CandleResearchReportRow("features", str(len(feature_rows)), "Generated market feature rows."),
        CandleResearchReportRow("candidate_setups", str(len(candidate_rows)), "Candidate setups emitted by setup generator."),
        CandleResearchReportRow("risk_plans", str(len(plan_rows)), "Risk plans generated from candidates."),
        CandleResearchReportRow("simulated_exits", str(len(exit_rows)), "Candle-based exits generated from risk plans."),
        CandleResearchReportRow("winrate_pct", fmt(wins / len(rs) * 100.0 if rs else 0.0, 2), "Winrate after candle-based exit simulation."),
        CandleResearchReportRow("avg_r", fmt(mean(rs) if rs else 0.0, 6), "Average R after candle-based exit simulation."),
        CandleResearchReportRow("total_r", fmt(sum(rs), 6), "Total R after candle-based exit simulation."),
    ]

    if all_diag:
        rows.extend([
            CandleResearchReportRow("take_profit_count", str(all_diag.take_profit), "Trades exited by TP."),
            CandleResearchReportRow("stop_loss_count", str(all_diag.stop_loss), "Trades exited by SL."),
            CandleResearchReportRow("time_stop_count", str(all_diag.time_stop), "Trades exited by time-stop."),
            CandleResearchReportRow("avg_bars_held", str(all_diag.avg_bars_held), "Average bars held."),
        ])

    setup_best = top_group(diagnostic_rows, "setup_type", "avg_r", True)
    setup_worst = top_group(diagnostic_rows, "setup_type", "avg_r", False)
    grade_best = top_group(diagnostic_rows, "risk_grade", "avg_r", True)
    policy_best = top_group(diagnostic_rows, "target_policy", "avg_r", True)
    symbol_best = top_group(diagnostic_rows, "symbol", "avg_r", True)
    symbol_worst = top_group(diagnostic_rows, "symbol", "avg_r", False)
    most_common_exit = top_group(diagnostic_rows, "exit_reason", "trades", True)

    if setup_best:
        rows.append(CandleResearchReportRow("best_setup_type", setup_best.value, f"avg_r={setup_best.avg_r}, trades={setup_best.trades}"))
    if setup_worst:
        rows.append(CandleResearchReportRow("worst_setup_type", setup_worst.value, f"avg_r={setup_worst.avg_r}, trades={setup_worst.trades}"))
    if grade_best:
        rows.append(CandleResearchReportRow("best_risk_grade", grade_best.value, f"avg_r={grade_best.avg_r}, trades={grade_best.trades}"))
    if policy_best:
        rows.append(CandleResearchReportRow("best_target_policy", policy_best.value, f"avg_r={policy_best.avg_r}, trades={policy_best.trades}"))
    if symbol_best:
        rows.append(CandleResearchReportRow("best_symbol", symbol_best.value, f"avg_r={symbol_best.avg_r}, trades={symbol_best.trades}"))
    if symbol_worst:
        rows.append(CandleResearchReportRow("worst_symbol", symbol_worst.value, f"avg_r={symbol_worst.avg_r}, trades={symbol_worst.trades}"))
    if most_common_exit:
        rows.append(CandleResearchReportRow("most_common_exit", most_common_exit.value, f"trades={most_common_exit.trades}"))

    setup_types = sorted({c.setup_type for c in candidate_rows})
    risk_grades = sorted({p.risk_grade for p in plan_rows})
    target_policies = sorted({p.target_policy for p in plan_rows})
    rows.extend([
        CandleResearchReportRow("setup_types_seen", ",".join(setup_types), "Setup types emitted in this run."),
        CandleResearchReportRow("risk_grades_seen", ",".join(risk_grades), "Risk grades emitted in this run."),
        CandleResearchReportRow("target_policies_seen", ",".join(target_policies), "Target policies emitted in this run."),
    ])
    return rows


def rows_as_dicts(rows: Iterable[CandleResearchReportRow]) -> list[dict]:
    return [asdict(row) for row in rows]
