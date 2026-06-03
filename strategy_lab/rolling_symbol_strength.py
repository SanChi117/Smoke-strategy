#!/usr/bin/env python3
"""
Standalone Rolling Symbol Strength engine.

Input: normalized trade CSV.
Output: rolling symbol selection + capital simulation metrics.

Research only. No live execution. Not financial advice.
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


@dataclass(frozen=True)
class Trade:
    symbol: str
    side: str
    entry_time: datetime
    exit_time: datetime
    entry: float
    stop: float
    exit: float
    r_mult: float
    source: str = ""
    kind: str = ""


@dataclass(frozen=True)
class CostConfig:
    fee_rate: float = 0.0008
    slippage_rate: float = 0.0


@dataclass(frozen=True)
class CapitalConfig:
    initial_cash: float = 500.0
    risk_pct: float = 0.02
    leverage: float = 20.0
    max_positions: int = 2
    max_margin_pct: float = 0.20
    reinvest: bool = False


@dataclass(frozen=True)
class RollingConfig:
    lookback_days: int
    rebalance_days: int
    top_n: int


@dataclass
class Result:
    setup: str
    trades: int
    skipped: int
    final_cash: float
    ret_pct: float
    max_dd_pct: float
    pf: float
    winrate: float
    max_loss_streak: int
    symbols_traded: int
    symbols_positive: int
    avg_selected: float
    windows: int


def parse_dt(value: str) -> datetime:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1]
    return datetime.fromisoformat(value)


def load_trades_csv(path: str | Path) -> List[Trade]:
    trades: List[Trade] = []
    with Path(path).open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"symbol", "side", "entry_time", "exit_time", "entry", "stop", "exit", "r_mult"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing required CSV columns: {sorted(missing)}")
        for row in reader:
            trades.append(
                Trade(
                    symbol=row["symbol"].strip().upper(),
                    side=row["side"].strip().lower(),
                    entry_time=parse_dt(row["entry_time"]),
                    exit_time=parse_dt(row["exit_time"]),
                    entry=float(row["entry"]),
                    stop=float(row["stop"]),
                    exit=float(row["exit"]),
                    r_mult=float(row["r_mult"]),
                    source=row.get("source", ""),
                    kind=row.get("kind", ""),
                )
            )
    return sorted(trades, key=lambda t: (t.entry_time, t.symbol, t.side))


def pf(values: Sequence[float]) -> float:
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses <= 0:
        return 99.0 if gains > 0 else 0.0
    return gains / losses


def max_loss_streak(values: Sequence[float]) -> int:
    best = 0
    cur = 0
    for v in values:
        if v < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def trades_between(trades: Sequence[Trade], start: datetime, end: datetime) -> List[Trade]:
    return [t for t in trades if start <= t.entry_time < end]


def score_symbol(symbol: str, lookback_trades: Sequence[Trade], cost: CostConfig) -> Tuple[float, Dict[str, float]]:
    sym = [t for t in lookback_trades if t.symbol == symbol]
    if len(sym) < 3:
        return -999.0, {"trades": len(sym), "pf": 0.0, "win": 0.0, "avg_r": 0.0, "score": -999.0}

    cost_penalty = (cost.fee_rate * 2.0 + cost.slippage_rate * 2.0) * 10.0
    vals = [float(t.r_mult) - cost_penalty for t in sym]
    wins = sum(1 for v in vals if v > 0)
    pfx = pf(vals)
    avg_r = sum(vals) / len(vals)

    long_vals = [float(t.r_mult) - cost_penalty for t in sym if t.side == "long"]
    short_vals = [float(t.r_mult) - cost_penalty for t in sym if t.side == "short"]

    sample_score = min(25.0, len(vals) * 2.0)
    pf_score = min(40.0, max(-30.0, (pfx - 1.0) * 18.0)) if pfx < 20 else 40.0
    avg_score = max(-25.0, min(35.0, avg_r * 18.0))
    balance_penalty = 0.0
    if long_vals and pf(long_vals) < 1.0:
        balance_penalty -= 6.0
    if short_vals and pf(short_vals) < 1.0:
        balance_penalty -= 6.0
    score = sample_score + pf_score + avg_score + balance_penalty
    return score, {"trades": len(vals), "pf": pfx, "win": wins / len(vals) * 100.0, "avg_r": avg_r, "score": score}


def select_symbols(lookback_trades: Sequence[Trade], all_symbols: Sequence[str], top_n: int, cost: CostConfig) -> List[str]:
    scored = []
    for sym in all_symbols:
        score, info = score_symbol(sym, lookback_trades, cost)
        scored.append((score, info["pf"], info["avg_r"], info["trades"], sym))
    scored.sort(reverse=True)
    return [sym for _, _, _, trades, sym in scored[:top_n] if trades >= 3]


def build_rolling_trades(trades: Sequence[Trade], start: datetime, end: datetime, rcfg: RollingConfig, cost: CostConfig) -> Tuple[List[Trade], int, float]:
    all_symbols = sorted({t.symbol for t in trades})
    eligible: List[Trade] = []
    seen = set()
    selected_counts: List[int] = []
    windows = 0

    cur = start + timedelta(days=rcfg.lookback_days)
    while cur < end:
        lb_start = cur - timedelta(days=rcfg.lookback_days)
        fwd_end = min(end, cur + timedelta(days=rcfg.rebalance_days))
        lookback = trades_between(trades, lb_start, cur)
        selected = set(select_symbols(lookback, all_symbols, rcfg.top_n, cost))
        selected_counts.append(len(selected))
        windows += 1
        for t in trades_between(trades, cur, fwd_end):
            if t.symbol not in selected:
                continue
            key = (t.symbol, t.entry_time, t.side)
            if key in seen:
                continue
            seen.add(key)
            eligible.append(t)
        cur = fwd_end

    avg_selected = sum(selected_counts) / len(selected_counts) if selected_counts else 0.0
    return sorted(eligible, key=lambda t: (t.entry_time, t.symbol, t.side)), windows, avg_selected


def adjusted_return_pct(trade: Trade, cost: CostConfig) -> float:
    slip = cost.slippage_rate
    if trade.entry <= 0:
        return 0.0
    if trade.side == "long":
        entry = trade.entry * (1.0 + slip)
        exit_p = trade.exit * (1.0 - slip)
        return (exit_p - entry) / entry
    entry = trade.entry * (1.0 - slip)
    exit_p = trade.exit * (1.0 + slip)
    return (entry - exit_p) / entry


def risk_distance_pct(trade: Trade, cost: CostConfig) -> float:
    slip = cost.slippage_rate
    if trade.entry <= 0:
        return 0.0
    if trade.side == "long":
        entry = trade.entry * (1.0 + slip)
        stop = trade.stop * (1.0 - slip)
    else:
        entry = trade.entry * (1.0 - slip)
        stop = trade.stop * (1.0 + slip)
    return abs(entry - stop) / entry


def simulate_capital(trades: Sequence[Trade], cap: CapitalConfig, cost: CostConfig, setup: str, windows: int = 0, avg_selected: float = 0.0) -> Result:
    ordered = sorted(trades, key=lambda t: (t.entry_time, t.symbol, t.side))
    cash = cap.initial_cash
    peak = cap.initial_cash
    max_dd = 0.0
    active: List[Tuple[Trade, float, float, float]] = []
    taken: List[Tuple[Trade, float]] = []
    skipped = 0
    pnl_values: List[float] = []

    def mark_dd() -> None:
        nonlocal peak, max_dd
        equity = cash + sum(x[1] for x in active)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)

    def close_until(dt: datetime) -> None:
        nonlocal cash, active
        remaining = []
        for t, margin, notional, opened_equity in active:
            if t.exit_time <= dt:
                gross_pnl = notional * adjusted_return_pct(t, cost)
                exit_fee = notional * cost.fee_rate
                pnl = gross_pnl - exit_fee
                cash += margin + pnl
                taken.append((t, pnl))
                pnl_values.append(pnl)
                mark_dd()
            else:
                remaining.append((t, margin, notional, opened_equity))
        active = remaining

    for t in ordered:
        close_until(t.entry_time)
        if any(a[0].symbol == t.symbol for a in active):
            skipped += 1
            continue
        if len(active) >= cap.max_positions:
            skipped += 1
            continue
        if cash <= 0:
            skipped += 1
            continue
        dist = risk_distance_pct(t, cost)
        if dist <= 0 or not math.isfinite(dist):
            skipped += 1
            continue
        used_margin = sum(x[1] for x in active)
        equity = cash + used_margin
        risk_base = equity if cap.reinvest else cap.initial_cash
        risk_amount = min(risk_base * cap.risk_pct, equity * cap.risk_pct)
        risk_based_notional = risk_amount / dist
        max_margin = equity * cap.max_margin_pct
        margin = min(max_margin, risk_based_notional / cap.leverage, cash)
        notional = margin * cap.leverage
        entry_fee = notional * cost.fee_rate
        if margin <= 1e-9 or notional <= 1e-9 or cash < margin + entry_fee:
            skipped += 1
            continue
        cash -= margin + entry_fee
        active.append((t, margin, notional, equity))
        mark_dd()

    if ordered:
        close_until(max(t.exit_time for t in ordered))
    if active:
        for t, margin, notional, opened_equity in active:
            gross_pnl = notional * adjusted_return_pct(t, cost)
            exit_fee = notional * cost.fee_rate
            pnl = gross_pnl - exit_fee
            cash += margin + pnl
            taken.append((t, pnl))
            pnl_values.append(pnl)
        active = []
    mark_dd()

    wins = sum(1 for v in pnl_values if v > 0)
    by_symbol: Dict[str, float] = {}
    for t, pnl in taken:
        by_symbol[t.symbol] = by_symbol.get(t.symbol, 0.0) + pnl
    return Result(
        setup=setup,
        trades=len(taken),
        skipped=skipped,
        final_cash=cash,
        ret_pct=(cash / cap.initial_cash - 1.0) * 100.0,
        max_dd_pct=max_dd,
        pf=pf(pnl_values),
        winrate=wins / len(pnl_values) * 100.0 if pnl_values else 0.0,
        max_loss_streak=max_loss_streak(pnl_values),
        symbols_traded=len(by_symbol),
        symbols_positive=sum(1 for v in by_symbol.values() if v > 0),
        avg_selected=avg_selected,
        windows=windows,
    )


def run_rolling(trades: Sequence[Trade], start: datetime, end: datetime, rcfg: RollingConfig, cap: CapitalConfig, cost: CostConfig) -> Result:
    rolling_trades, windows, avg_selected = build_rolling_trades(trades, start, end, rcfg, cost)
    setup = f"ROLL_L{rcfg.lookback_days}_R{rcfg.rebalance_days}_T{rcfg.top_n}"
    return simulate_capital(rolling_trades, cap, cost, setup, windows, avg_selected)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--trades-csv", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--lookback-days", type=int, default=30)
    p.add_argument("--rebalance-days", type=int, default=7)
    p.add_argument("--top-n", type=int, default=8)
    p.add_argument("--initial-cash", type=float, default=500.0)
    p.add_argument("--risk-pct", type=float, default=0.005)
    p.add_argument("--leverage", type=float, default=20.0)
    p.add_argument("--max-positions", type=int, default=2)
    p.add_argument("--fee", type=float, default=0.0008)
    p.add_argument("--slippage", type=float, default=0.0)
    p.add_argument("--reinvest", action="store_true")
    args = p.parse_args()

    trades = load_trades_csv(args.trades_csv)
    result = run_rolling(
        trades,
        parse_dt(args.start),
        parse_dt(args.end),
        RollingConfig(args.lookback_days, args.rebalance_days, args.top_n),
        CapitalConfig(args.initial_cash, args.risk_pct, args.leverage, args.max_positions, reinvest=args.reinvest),
        CostConfig(args.fee, args.slippage),
    )
    print(
        f"{result.setup} trades={result.trades} skipped={result.skipped} final=${result.final_cash:.2f} "
        f"ret={result.ret_pct:.2f}% DD={result.max_dd_pct:.2f}% PF={result.pf:.2f} win={result.winrate:.2f}% "
        f"LS={result.max_loss_streak} sym+={result.symbols_positive}/{result.symbols_traded} "
        f"windows={result.windows} avgSelected={result.avg_selected:.2f}"
    )


if __name__ == "__main__":
    main()
