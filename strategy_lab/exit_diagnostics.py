#!/usr/bin/env python3
"""Exit diagnostics for candle-based research exits.

Explains how generated trades exit after candle simulation:
- TP / SL / time-stop distribution
- performance by setup_type
- performance by risk_grade
- performance by target_policy
- performance by symbol and side

Research only. No live trading.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Iterable

from strategy_lab.candle_exit_simulator import SimulatedExit
from strategy_lab.risk_model import RiskPlan


@dataclass(frozen=True)
class ExitDiagnosticRow:
    group: str
    value: str
    trades: int
    take_profit: int
    stop_loss: int
    time_stop: int
    no_future_candles: int
    winrate: float
    avg_r: float
    total_r: float
    min_r: float
    max_r: float
    avg_bars_held: float


def summarize(group: str, value: str, pairs: list[tuple[RiskPlan, SimulatedExit]]) -> ExitDiagnosticRow:
    rs = [float(exit_result.r_mult) for _plan, exit_result in pairs]
    bars = [int(exit_result.bars_held) for _plan, exit_result in pairs]
    trades = len(pairs)
    wins = sum(1 for r in rs if r > 0)
    return ExitDiagnosticRow(
        group=group,
        value=value,
        trades=trades,
        take_profit=sum(1 for _plan, e in pairs if e.exit_reason == "take_profit"),
        stop_loss=sum(1 for _plan, e in pairs if e.exit_reason == "stop_loss"),
        time_stop=sum(1 for _plan, e in pairs if e.exit_reason == "time_stop"),
        no_future_candles=sum(1 for _plan, e in pairs if e.exit_reason == "no_future_candles"),
        winrate=round(wins / trades * 100.0, 2) if trades else 0.0,
        avg_r=round(mean(rs), 6) if rs else 0.0,
        total_r=round(sum(rs), 6),
        min_r=round(min(rs), 6) if rs else 0.0,
        max_r=round(max(rs), 6) if rs else 0.0,
        avg_bars_held=round(mean(bars), 2) if bars else 0.0,
    )


def build_exit_diagnostics(plans: Iterable[RiskPlan], exits: Iterable[SimulatedExit]) -> list[ExitDiagnosticRow]:
    pairs = list(zip(plans, exits))
    if not pairs:
        return []

    rows: list[ExitDiagnosticRow] = [summarize("all", "all", pairs)]
    groups: dict[str, dict[str, list[tuple[RiskPlan, SimulatedExit]]]] = {
        "exit_reason": {},
        "setup_type": {},
        "risk_grade": {},
        "target_policy": {},
        "trend_context": {},
        "volatility_regime": {},
        "structure_type": {},
        "side": {},
        "symbol": {},
    }

    for plan, exit_result in pairs:
        keys = [
            ("exit_reason", exit_result.exit_reason),
            ("setup_type", plan.setup_type),
            ("risk_grade", plan.risk_grade),
            ("target_policy", plan.target_policy),
            ("trend_context", plan.trend_context),
            ("volatility_regime", plan.volatility_regime),
            ("structure_type", plan.structure_type),
            ("side", plan.side),
            ("symbol", plan.symbol),
        ]
        for group, value in keys:
            groups[group].setdefault(value, []).append((plan, exit_result))

    for group, values in groups.items():
        for value, group_pairs in sorted(values.items()):
            rows.append(summarize(group, value, group_pairs))
    return rows


def rows_as_dicts(rows: Iterable[ExitDiagnosticRow]) -> list[dict]:
    return [asdict(row) for row in rows]
