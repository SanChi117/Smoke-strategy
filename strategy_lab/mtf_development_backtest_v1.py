#!/usr/bin/env python3
"""Frozen SMOKE MTF V2 development trade generation and portfolio accounting."""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from math import inf
from statistics import mean
from typing import Iterable, Sequence

from strategy_lab.market_data import Candle
from strategy_lab.mtf_dealing_range_v2 import MtfDealingRangeEngine
from strategy_lab.mtf_entry_model_v2 import MtfEntryModelV2
from strategy_lab.mtf_recognition_fast_runtime_v2 import install_fast_runtime


@dataclass(frozen=True)
class FundingRate:
    symbol: str
    time: datetime
    rate: float


@dataclass(frozen=True)
class TradeCandidate:
    symbol: str
    side: str
    fold: int
    entry_time: datetime
    entry: float
    stop: float
    target: float
    exit_time: datetime
    exit_price: float
    exit_reason: str
    gross_return_fraction: float
    funding_return_fraction: float
    net_return_fraction: float
    structural_risk_fraction: float
    event_risk_multiplier: float
    planned_rr: float
    quality_score: float
    target_timeframe: str
    target_source: str


@dataclass(frozen=True)
class AcceptedTrade:
    candidate: TradeCandidate
    equity_before: float
    risk_cash: float
    notional: float
    pnl_cash: float
    equity_after_exit: float


def contiguous_fold_bounds(start: datetime, end: datetime, folds: int = 10) -> list[tuple[datetime, datetime]]:
    if folds <= 0 or end <= start:
        raise ValueError("invalid fold request")
    total_days = (end - start).days
    if start + timedelta(days=total_days) != end:
        raise ValueError("development bounds must be whole UTC days")
    base_days, extra = divmod(total_days, folds)
    if base_days <= 0:
        raise ValueError("not enough days for requested folds")
    out: list[tuple[datetime, datetime]] = []
    cursor = start
    for index in range(folds):
        days = base_days + (1 if index < extra else 0)
        right = cursor + timedelta(days=days)
        out.append((cursor, right))
        cursor = right
    if cursor != end:
        raise AssertionError("fold construction did not cover the full period")
    return out


def _funding_map(rows: Iterable[FundingRate]) -> dict[str, tuple[list[datetime], list[float]]]:
    grouped: dict[str, list[FundingRate]] = {}
    for row in rows:
        grouped.setdefault(row.symbol.upper(), []).append(row)
    output: dict[str, tuple[list[datetime], list[float]]] = {}
    for symbol, values in grouped.items():
        values.sort(key=lambda item: item.time)
        output[symbol] = ([item.time for item in values], [float(item.rate) for item in values])
    return output


def funding_return(
    symbol: str,
    side: str,
    entry_time: datetime,
    exit_time: datetime,
    funding: dict[str, tuple[list[datetime], list[float]]],
) -> float:
    times, rates = funding.get(symbol.upper(), ([], []))
    left = bisect_left(times, entry_time)
    right = bisect_left(times, exit_time)
    signed = sum(rates[left:right])
    return -signed if side == "long" else signed


def _effective_return(
    side: str,
    entry: float,
    exit_price: float,
    commission_bps_per_side: float,
    slippage_bps_per_side: float,
) -> float:
    fee = commission_bps_per_side / 10000.0
    slip = slippage_bps_per_side / 10000.0
    if side == "long":
        entry_effective = entry * (1.0 + slip)
        exit_effective = exit_price * (1.0 - slip)
        price_return = (exit_effective - entry_effective) / entry_effective
    else:
        entry_effective = entry * (1.0 - slip)
        exit_effective = exit_price * (1.0 + slip)
        price_return = (entry_effective - exit_effective) / entry_effective
    exit_notional_ratio = exit_effective / entry_effective
    return price_return - fee * (1.0 + exit_notional_ratio)


def resolve_trade(
    symbol_candles: Sequence[Candle],
    *,
    symbol: str,
    side: str,
    entry_time: datetime,
    entry: float,
    stop: float,
    target: float,
    study_end: datetime,
    funding: dict[str, tuple[list[datetime], list[float]]],
    commission_bps_per_side: float = 4.0,
    slippage_bps_per_side: float = 1.0,
) -> tuple[datetime, float, str, float, float, float]:
    times = [row.time for row in symbol_candles]
    index = bisect_left(times, entry_time)
    if index >= len(symbol_candles) or symbol_candles[index].time != entry_time:
        raise ValueError(f"entry candle not found for {symbol} at {entry_time.isoformat()}")
    last: Candle | None = None
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason = ""
    for bar in symbol_candles[index:]:
        if bar.time >= study_end:
            break
        last = bar
        if side == "long":
            stop_hit = bar.low <= stop
            target_hit = bar.high >= target
        else:
            stop_hit = bar.high >= stop
            target_hit = bar.low <= target
        if stop_hit:
            exit_time = bar.time + timedelta(minutes=5)
            exit_price = stop
            exit_reason = "STOP"
            break
        if target_hit:
            exit_time = bar.time + timedelta(minutes=5)
            exit_price = target
            exit_reason = "TARGET"
            break
    if exit_time is None or exit_price is None:
        if last is None:
            raise ValueError(f"no outcome candles for {symbol} at {entry_time.isoformat()}")
        exit_time = min(study_end, last.time + timedelta(minutes=5))
        exit_price = last.close
        exit_reason = "STUDY_END"
    gross_after_costs = _effective_return(
        side, entry, exit_price, commission_bps_per_side, slippage_bps_per_side
    )
    funding_component = funding_return(symbol, side, entry_time, exit_time, funding)
    net = gross_after_costs + funding_component
    return exit_time, exit_price, exit_reason, gross_after_costs, funding_component, net


def generate_fold_candidates(
    candles: Sequence[Candle],
    *,
    fold: int,
    scan_start: datetime,
    scan_end: datetime,
    study_end: datetime,
    funding_rates: Iterable[FundingRate] = (),
    commission_bps_per_side: float = 4.0,
    slippage_bps_per_side: float = 1.0,
) -> tuple[list[TradeCandidate], dict]:
    symbols = {row.symbol.upper() for row in candles}
    if len(symbols) != 1:
        raise ValueError("one symbol per fold job is required")
    symbol = next(iter(symbols))
    rows = sorted(candles, key=lambda item: item.time)
    funding = _funding_map(funding_rates)
    engine = MtfDealingRangeEngine(rows)
    runtime = install_fast_runtime(engine)
    model = MtfEntryModelV2(engine)
    candidates: list[TradeCandidate] = []
    evaluated = 0
    entry_ready = 0
    for bar in engine.bars["15m"]:
        if bar.symbol != symbol or not (scan_start <= bar.open_time < scan_end):
            continue
        evaluated += 1
        for side in ("long", "short"):
            plan = model.evaluate(symbol, bar.open_time, side)
            if not plan.allowed:
                continue
            entry_ready += 1
            if None in (plan.entry, plan.stop, plan.target, plan.entry_time, plan.rr):
                raise AssertionError("allowed plan lacks frozen execution geometry")
            structural_risk = (
                (plan.entry - plan.stop) / plan.entry
                if side == "long"
                else (plan.stop - plan.entry) / plan.entry
            )
            if structural_risk <= 0:
                raise AssertionError("allowed plan has non-positive structural risk")
            exit_time, exit_price, exit_reason, gross_return, funding_component, net_return = resolve_trade(
                rows,
                symbol=symbol,
                side=side,
                entry_time=plan.entry_time,
                entry=plan.entry,
                stop=plan.stop,
                target=plan.target,
                study_end=study_end,
                funding=funding,
                commission_bps_per_side=commission_bps_per_side,
                slippage_bps_per_side=slippage_bps_per_side,
            )
            candidates.append(
                TradeCandidate(
                    symbol=symbol,
                    side=side,
                    fold=fold,
                    entry_time=plan.entry_time,
                    entry=plan.entry,
                    stop=plan.stop,
                    target=plan.target,
                    exit_time=exit_time,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    gross_return_fraction=round(gross_return, 12),
                    funding_return_fraction=round(funding_component, 12),
                    net_return_fraction=round(net_return, 12),
                    structural_risk_fraction=round(structural_risk, 12),
                    event_risk_multiplier=round(plan.event_risk_multiplier, 6),
                    planned_rr=float(plan.rr),
                    quality_score=float(plan.quality_score),
                    target_timeframe=str(plan.target_timeframe or ""),
                    target_source=str(plan.target_source or ""),
                )
            )
    candidates.sort(key=lambda item: (item.entry_time, item.symbol, item.side))
    summary = {
        "symbol": symbol,
        "fold": fold,
        "scan_start": scan_start.isoformat(),
        "scan_end": scan_end.isoformat(),
        "evaluated_15m_bars": evaluated,
        "evaluated_side_snapshots": evaluated * 2,
        "entry_ready_candidates": entry_ready,
        "candidate_count": len(candidates),
        "runtime": runtime.stats(),
    }
    return candidates, summary


def _settle_until(
    open_trades: list[AcceptedTrade],
    timestamp: datetime,
    realized_equity: float,
) -> tuple[list[AcceptedTrade], float, list[AcceptedTrade]]:
    due = sorted(
        [trade for trade in open_trades if trade.candidate.exit_time <= timestamp],
        key=lambda trade: (trade.candidate.exit_time, trade.candidate.symbol, trade.candidate.side),
    )
    remaining = [trade for trade in open_trades if trade.candidate.exit_time > timestamp]
    settled: list[AcceptedTrade] = []
    equity = realized_equity
    for trade in due:
        equity += trade.pnl_cash
        settled.append(
            AcceptedTrade(
                candidate=trade.candidate,
                equity_before=trade.equity_before,
                risk_cash=trade.risk_cash,
                notional=trade.notional,
                pnl_cash=trade.pnl_cash,
                equity_after_exit=equity,
            )
        )
    return remaining, equity, settled


def simulate_portfolio(
    candidates: Sequence[TradeCandidate],
    *,
    initial_equity: float = 10000.0,
    risk_per_trade_pct: float = 0.5,
    max_total_open_risk_pct: float = 2.0,
) -> tuple[list[AcceptedTrade], dict]:
    realized_equity = float(initial_equity)
    open_trades: list[AcceptedTrade] = []
    completed: list[AcceptedTrade] = []
    rejected_open_symbol = 0
    rejected_risk_cap = 0
    peak_conservative = realized_equity
    max_drawdown = 0.0

    def record_conservative() -> None:
        nonlocal peak_conservative, max_drawdown
        conservative = realized_equity - sum(trade.risk_cash for trade in open_trades)
        peak_conservative = max(peak_conservative, conservative)
        if peak_conservative > 0:
            max_drawdown = max(max_drawdown, (peak_conservative - conservative) / peak_conservative)

    for candidate in sorted(candidates, key=lambda item: (item.entry_time, item.symbol, item.side)):
        open_trades, realized_equity, settled = _settle_until(open_trades, candidate.entry_time, realized_equity)
        completed.extend(settled)
        record_conservative()
        if any(trade.candidate.symbol == candidate.symbol for trade in open_trades):
            rejected_open_symbol += 1
            continue
        risk_fraction = risk_per_trade_pct / 100.0 * max(0.0, min(1.0, candidate.event_risk_multiplier))
        risk_cash = realized_equity * risk_fraction
        open_risk = sum(trade.risk_cash for trade in open_trades)
        max_open_risk_cash = realized_equity * (max_total_open_risk_pct / 100.0)
        if open_risk + risk_cash > max_open_risk_cash + 1e-9:
            rejected_risk_cap += 1
            continue
        notional = risk_cash / candidate.structural_risk_fraction
        pnl_cash = notional * candidate.net_return_fraction
        open_trades.append(
            AcceptedTrade(
                candidate=candidate,
                equity_before=realized_equity,
                risk_cash=risk_cash,
                notional=notional,
                pnl_cash=pnl_cash,
                equity_after_exit=realized_equity,
            )
        )
        record_conservative()

    if open_trades:
        final_time = max(trade.candidate.exit_time for trade in open_trades)
        open_trades, realized_equity, settled = _settle_until(open_trades, final_time, realized_equity)
        completed.extend(settled)
        record_conservative()
    completed.sort(key=lambda trade: (trade.candidate.exit_time, trade.candidate.symbol, trade.candidate.side))
    profits = [trade.pnl_cash for trade in completed if trade.pnl_cash > 0]
    losses = [-trade.pnl_cash for trade in completed if trade.pnl_cash < 0]
    pooled_pf = sum(profits) / sum(losses) if losses else (inf if profits else 0.0)
    fold_pnl: dict[int, float] = {}
    for trade in completed:
        fold_pnl[trade.candidate.fold] = fold_pnl.get(trade.candidate.fold, 0.0) + trade.pnl_cash
    summary = {
        "initial_equity": initial_equity,
        "ending_equity": round(realized_equity, 8),
        "net_profit": round(realized_equity - initial_equity, 8),
        "net_return_pct": round((realized_equity / initial_equity - 1.0) * 100.0, 8),
        "accepted_trades": len(completed),
        "rejected_open_symbol": rejected_open_symbol,
        "rejected_total_open_risk": rejected_risk_cap,
        "pooled_profit_factor": None if pooled_pf == inf else round(pooled_pf, 8),
        "pooled_profit_factor_infinite": pooled_pf == inf,
        "average_trade_return_after_costs": round(mean([trade.candidate.net_return_fraction for trade in completed]), 12) if completed else 0.0,
        "positive_folds": sum(1 for fold in range(10) if fold_pnl.get(fold, 0.0) > 0),
        "fold_pnl": {str(fold): round(fold_pnl.get(fold, 0.0), 8) for fold in range(10)},
        "portfolio_max_drawdown_pct": round(max_drawdown * 100.0, 8),
        "drawdown_method": "conservative realized equity minus all active structural risk",
    }
    return completed, summary


def candidate_to_dict(candidate: TradeCandidate) -> dict:
    row = asdict(candidate)
    row["entry_time"] = candidate.entry_time.isoformat()
    row["exit_time"] = candidate.exit_time.isoformat()
    return row


def accepted_to_dict(trade: AcceptedTrade) -> dict:
    row = candidate_to_dict(trade.candidate)
    row.update(
        {
            "equity_before": round(trade.equity_before, 8),
            "risk_cash": round(trade.risk_cash, 8),
            "notional": round(trade.notional, 8),
            "pnl_cash": round(trade.pnl_cash, 8),
            "equity_after_exit": round(trade.equity_after_exit, 8),
        }
    )
    return row
