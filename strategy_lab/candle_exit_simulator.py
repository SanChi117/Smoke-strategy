#!/usr/bin/env python3
"""Candle-based exit simulator for research trades.

Simulates each RiskPlan against future candles until:
- stop loss hit
- target hit
- max holding time reached

If a candle touches both stop and target, the simulator uses conservative
ordering and counts stop first. This avoids optimistic same-candle bias.

Research only. No live trading. No exchange assumptions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from strategy_lab.market_data import Candle, group_candles_by_symbol
from strategy_lab.risk_model import RiskPlan
from strategy_lab.rolling_symbol_strength import Trade


@dataclass(frozen=True)
class SimulatedExit:
    symbol: str
    side: str
    entry_time: object
    exit_time: object
    entry: float
    stop: float
    target: float
    exit: float
    r_mult: float
    exit_reason: str
    bars_held: int


def r_multiple(plan: RiskPlan, exit_price: float) -> float:
    risk = abs(plan.entry - plan.stop)
    if risk <= 0:
        return 0.0
    if plan.side == "long":
        return (exit_price - plan.entry) / risk
    return (plan.entry - exit_price) / risk


def simulate_plan_exit(plan: RiskPlan, candles: list[Candle]) -> SimulatedExit:
    future = [c for c in candles if c.symbol == plan.symbol and c.time > plan.entry_time and c.time <= plan.exit_time]
    if not future:
        return SimulatedExit(
            symbol=plan.symbol,
            side=plan.side,
            entry_time=plan.entry_time,
            exit_time=plan.exit_time,
            entry=plan.entry,
            stop=plan.stop,
            target=plan.target,
            exit=plan.entry,
            r_mult=0.0,
            exit_reason="no_future_candles",
            bars_held=0,
        )

    for idx, candle in enumerate(future, start=1):
        if plan.side == "long":
            stop_hit = candle.low <= plan.stop
            target_hit = candle.high >= plan.target
            if stop_hit:
                return SimulatedExit(plan.symbol, plan.side, plan.entry_time, candle.time, plan.entry, plan.stop, plan.target, plan.stop, -1.0, "stop_loss", idx)
            if target_hit:
                return SimulatedExit(plan.symbol, plan.side, plan.entry_time, candle.time, plan.entry, plan.stop, plan.target, plan.target, plan.target_rr, "take_profit", idx)
        else:
            stop_hit = candle.high >= plan.stop
            target_hit = candle.low <= plan.target
            if stop_hit:
                return SimulatedExit(plan.symbol, plan.side, plan.entry_time, candle.time, plan.entry, plan.stop, plan.target, plan.stop, -1.0, "stop_loss", idx)
            if target_hit:
                return SimulatedExit(plan.symbol, plan.side, plan.entry_time, candle.time, plan.entry, plan.stop, plan.target, plan.target, plan.target_rr, "take_profit", idx)

    last = future[-1]
    r = r_multiple(plan, last.close)
    return SimulatedExit(
        symbol=plan.symbol,
        side=plan.side,
        entry_time=plan.entry_time,
        exit_time=last.time,
        entry=plan.entry,
        stop=plan.stop,
        target=plan.target,
        exit=round(last.close, 8),
        r_mult=round(r, 6),
        exit_reason="time_stop",
        bars_held=len(future),
    )


def simulate_plan_exits(plans: Iterable[RiskPlan], candles: Iterable[Candle]) -> list[SimulatedExit]:
    by_symbol = group_candles_by_symbol(candles)
    exits: list[SimulatedExit] = []
    for plan in plans:
        exits.append(simulate_plan_exit(plan, by_symbol.get(plan.symbol, [])))
    return exits


def exit_to_trade(plan: RiskPlan, exit_result: SimulatedExit) -> Trade:
    return Trade(
        symbol=plan.symbol,
        side=plan.side,
        entry_time=plan.entry_time,
        exit_time=exit_result.exit_time,
        entry=plan.entry,
        stop=plan.stop,
        exit=exit_result.exit,
        r_mult=round(exit_result.r_mult, 6),
        source="candle_exit_simulator",
        kind=plan.setup_type,
    )


def rows_as_dicts(rows: Iterable[SimulatedExit]) -> list[dict]:
    out = []
    for row in rows:
        item = asdict(row)
        item["entry_time"] = item["entry_time"].isoformat(timespec="seconds") if hasattr(item["entry_time"], "isoformat") else str(item["entry_time"])
        item["exit_time"] = item["exit_time"].isoformat(timespec="seconds") if hasattr(item["exit_time"], "isoformat") else str(item["exit_time"])
        out.append(item)
    return out
