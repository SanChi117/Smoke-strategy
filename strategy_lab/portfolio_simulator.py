#!/usr/bin/env python3
"""Portfolio simulator for the integrated Smoke Strategy pipeline.

Supports dynamic per-trade risk, max positions, max symbol concentration,
fees, slippage, daily loss halt and weekly loss halt.

Research only. No live trading. No API keys.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from strategy_lab.config import RiskProfile
from strategy_lab.rolling_symbol_strength import CostConfig, Trade, adjusted_return_pct, pf, risk_distance_pct, max_loss_streak


@dataclass(frozen=True)
class DynamicPortfolioResult:
    setup: str
    trades: int
    skipped: int
    skipped_no_risk: int
    skipped_max_positions: int
    skipped_symbol_limit: int
    skipped_cash: int
    skipped_daily_halt: int
    skipped_weekly_halt: int
    final_cash: float
    ret_pct: float
    max_dd_pct: float
    pf: float
    winrate: float
    max_loss_streak: int
    symbols_traded: int
    symbols_positive: int
    total_fees: float
    avg_risk_pct: float


def iso_week_key(day: date) -> tuple[int, int]:
    year, week, _weekday = day.isocalendar()
    return year, week


def simulate_dynamic_portfolio(
    trades: Sequence[Trade],
    risk_pcts: dict[tuple[str, str, object], float],
    profile: RiskProfile,
    cost: CostConfig,
    setup: str,
) -> DynamicPortfolioResult:
    ordered = sorted(trades, key=lambda t: (t.entry_time, t.symbol, t.side))
    cash = profile.initial_cash
    peak = profile.initial_cash
    max_dd = 0.0
    active: list[tuple[Trade, float, float, float, float]] = []
    taken: list[tuple[Trade, float]] = []
    pnl_values: list[float] = []
    risk_values: list[float] = []
    total_fees = 0.0

    skipped = 0
    skipped_no_risk = 0
    skipped_max_positions = 0
    skipped_symbol_limit = 0
    skipped_cash = 0
    skipped_daily_halt = 0
    skipped_weekly_halt = 0

    daily_pnl: dict[date, float] = {}
    weekly_pnl: dict[tuple[int, int], float] = {}

    def key_for(t: Trade) -> tuple[str, str, object]:
        return (t.symbol.upper(), t.side.lower(), t.entry_time)

    def mark_dd() -> None:
        nonlocal peak, max_dd
        equity = cash + sum(item[1] for item in active)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)

    def record_pnl(t: Trade, pnl: float) -> None:
        day = t.exit_time.date()
        daily_pnl[day] = daily_pnl.get(day, 0.0) + pnl
        wk = iso_week_key(day)
        weekly_pnl[wk] = weekly_pnl.get(wk, 0.0) + pnl

    def close_until(dt) -> None:
        nonlocal cash, active, total_fees
        remaining: list[tuple[Trade, float, float, float, float]] = []
        for t, margin, notional, opened_equity, risk_pct in active:
            if t.exit_time <= dt:
                gross_pnl = notional * adjusted_return_pct(t, cost)
                exit_fee = notional * cost.fee_rate
                total_fees += exit_fee
                pnl = gross_pnl - exit_fee
                cash += margin + pnl
                taken.append((t, pnl))
                pnl_values.append(pnl)
                risk_values.append(risk_pct)
                record_pnl(t, pnl)
                mark_dd()
            else:
                remaining.append((t, margin, notional, opened_equity, risk_pct))
        active = remaining

    def daily_halted(t: Trade) -> bool:
        limit = -profile.initial_cash * profile.daily_loss_limit_pct
        return daily_pnl.get(t.entry_time.date(), 0.0) <= limit

    def weekly_halted(t: Trade) -> bool:
        limit = -profile.initial_cash * profile.weekly_loss_limit_pct
        return weekly_pnl.get(iso_week_key(t.entry_time.date()), 0.0) <= limit

    for t in ordered:
        close_until(t.entry_time)
        risk_pct = float(risk_pcts.get(key_for(t), profile.base_risk_pct))
        risk_pct = max(0.0, min(profile.max_risk_pct, risk_pct))

        if risk_pct <= 0:
            skipped += 1
            skipped_no_risk += 1
            continue
        if daily_halted(t):
            skipped += 1
            skipped_daily_halt += 1
            continue
        if weekly_halted(t):
            skipped += 1
            skipped_weekly_halt += 1
            continue
        if len(active) >= profile.max_positions:
            skipped += 1
            skipped_max_positions += 1
            continue
        if sum(1 for item in active if item[0].symbol == t.symbol) >= profile.max_symbol_positions:
            skipped += 1
            skipped_symbol_limit += 1
            continue
        if cash <= 0:
            skipped += 1
            skipped_cash += 1
            continue

        dist = risk_distance_pct(t, cost)
        if dist <= 0 or not math.isfinite(dist):
            skipped += 1
            skipped_cash += 1
            continue

        used_margin = sum(item[1] for item in active)
        equity = cash + used_margin
        risk_base = equity if profile.reinvest else profile.initial_cash
        risk_amount = min(risk_base * risk_pct, equity * risk_pct)
        risk_based_notional = risk_amount / dist
        max_margin = equity * profile.max_margin_pct
        margin = min(max_margin, risk_based_notional / profile.leverage, cash)
        notional = margin * profile.leverage
        entry_fee = notional * cost.fee_rate

        if margin <= 1e-9 or notional <= 1e-9 or cash < margin + entry_fee:
            skipped += 1
            skipped_cash += 1
            continue

        cash -= margin + entry_fee
        total_fees += entry_fee
        active.append((t, margin, notional, equity, risk_pct))
        mark_dd()

    if ordered:
        close_until(max(t.exit_time for t in ordered))

    if active:
        for t, margin, notional, opened_equity, risk_pct in active:
            gross_pnl = notional * adjusted_return_pct(t, cost)
            exit_fee = notional * cost.fee_rate
            total_fees += exit_fee
            pnl = gross_pnl - exit_fee
            cash += margin + pnl
            taken.append((t, pnl))
            pnl_values.append(pnl)
            risk_values.append(risk_pct)
            record_pnl(t, pnl)
        active = []
    mark_dd()

    wins = sum(1 for v in pnl_values if v > 0)
    by_symbol: dict[str, float] = {}
    for t, pnl in taken:
        by_symbol[t.symbol] = by_symbol.get(t.symbol, 0.0) + pnl

    return DynamicPortfolioResult(
        setup=setup,
        trades=len(taken),
        skipped=skipped,
        skipped_no_risk=skipped_no_risk,
        skipped_max_positions=skipped_max_positions,
        skipped_symbol_limit=skipped_symbol_limit,
        skipped_cash=skipped_cash,
        skipped_daily_halt=skipped_daily_halt,
        skipped_weekly_halt=skipped_weekly_halt,
        final_cash=cash,
        ret_pct=(cash / profile.initial_cash - 1.0) * 100.0,
        max_dd_pct=max_dd,
        pf=pf(pnl_values),
        winrate=wins / len(pnl_values) * 100.0 if pnl_values else 0.0,
        max_loss_streak=max_loss_streak(pnl_values),
        symbols_traded=len(by_symbol),
        symbols_positive=sum(1 for v in by_symbol.values() if v > 0),
        total_fees=total_fees,
        avg_risk_pct=sum(risk_values) / len(risk_values) if risk_values else 0.0,
    )
