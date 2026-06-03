#!/usr/bin/env python3
"""Risk diagnostics for the integrated Smoke Strategy pipeline.

The goal is to explain how the $100 / 20x profile is being used:
- what was allowed or blocked
- why trades were blocked
- how risk was distributed
- whether quality/structure gates are too strict or too loose

Research only. No live trading. No API keys.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Iterable

from strategy_lab.schemas import PipelineDecision


@dataclass(frozen=True)
class RiskDiagnosticRow:
    group: str
    value: str
    candidates: int
    allowed: int
    blocked: int
    allowed_pct: float
    avg_risk_pct: float
    min_risk_pct: float
    max_risk_pct: float
    full_risk_trades: int
    reduced_risk_trades: int
    zero_risk_trades: int


@dataclass(frozen=True)
class RiskPolicyRow:
    metric: str
    value: str
    note: str


def bucket_risk(risk_pct: float) -> str:
    if risk_pct <= 0:
        return "zero_risk"
    if risk_pct < 0.006:
        return "reduced_risk"
    if risk_pct < 0.009:
        return "base_risk"
    return "full_risk"


def summarize_group(group: str, value: str, rows: list[PipelineDecision]) -> RiskDiagnosticRow:
    risks = [float(r.risk_pct) for r in rows]
    allowed_rows = [r for r in rows if r.allowed]
    return RiskDiagnosticRow(
        group=group,
        value=value,
        candidates=len(rows),
        allowed=len(allowed_rows),
        blocked=len(rows) - len(allowed_rows),
        allowed_pct=round(len(allowed_rows) / len(rows) * 100.0, 2) if rows else 0.0,
        avg_risk_pct=round(mean(risks), 6) if risks else 0.0,
        min_risk_pct=round(min(risks), 6) if risks else 0.0,
        max_risk_pct=round(max(risks), 6) if risks else 0.0,
        full_risk_trades=sum(1 for r in rows if bucket_risk(float(r.risk_pct)) == "full_risk"),
        reduced_risk_trades=sum(1 for r in rows if bucket_risk(float(r.risk_pct)) in {"reduced_risk", "base_risk"}),
        zero_risk_trades=sum(1 for r in rows if float(r.risk_pct) <= 0),
    )


def build_risk_diagnostics(decisions: Iterable[PipelineDecision]) -> list[RiskDiagnosticRow]:
    rows = list(decisions)
    out: list[RiskDiagnosticRow] = []
    if not rows:
        return out

    out.append(summarize_group("all", "all", rows))

    groups: dict[str, dict[str, list[PipelineDecision]]] = {
        "allowed": {},
        "reason": {},
        "universe_state": {},
        "quality_decision": {},
        "structure_decision": {},
        "quality_x_structure": {},
        "risk_bucket": {},
        "target_policy": {},
        "setup_type": {},
        "trend_context": {},
        "volatility_regime": {},
    }

    for row in rows:
        items = [
            ("allowed", "allowed" if row.allowed else "blocked"),
            ("reason", row.reason),
            ("universe_state", row.universe_state),
            ("quality_decision", row.quality_decision),
            ("structure_decision", row.structure_decision),
            ("quality_x_structure", f"{row.quality_decision}+{row.structure_decision}"),
            ("risk_bucket", bucket_risk(float(row.risk_pct))),
            ("target_policy", row.target_policy),
            ("setup_type", row.setup_type),
            ("trend_context", row.trend_context),
            ("volatility_regime", row.volatility_regime),
        ]
        for group, value in items:
            groups[group].setdefault(value, []).append(row)

    for group, values in groups.items():
        for value, group_rows in sorted(values.items()):
            out.append(summarize_group(group, value, group_rows))
    return out


def build_risk_policy_notes() -> list[RiskPolicyRow]:
    return [
        RiskPolicyRow("profile", "growth_100_20x", "$100 balance, 20x leverage, growth-oriented research profile."),
        RiskPolicyRow("base_risk", "0.75%", "Default risk for strong allowed trades."),
        RiskPolicyRow("max_risk", "1.00%", "Hard cap for strongest signals only."),
        RiskPolicyRow("watch_risk", "0.375%", "WATCH-based allowed trades use half of base risk."),
        RiskPolicyRow("max_positions", "2", "No more than two simultaneous positions."),
        RiskPolicyRow("max_symbol_positions", "1", "No duplicate active position on the same symbol."),
        RiskPolicyRow("daily_loss_limit", "3%", "Research halt target for same-day new entries after realized losses."),
        RiskPolicyRow("weekly_loss_limit", "8%", "Research halt target for same-week new entries after realized losses."),
        RiskPolicyRow("skip_rule", "Any SKIP blocks trade", "Quality SKIP or Structure SKIP sets risk to zero and blocks the trade."),
    ]


def rows_as_dicts(rows: Iterable[object]) -> list[dict]:
    return [asdict(row) for row in rows]
