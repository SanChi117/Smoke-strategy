#!/usr/bin/env python3
"""Honest pooled metrics for sparse strict-OOS research.

Averaging fold-level profit factors is invalid when some folds contain only wins
and use a sentinel PF such as 99. This module pools realised net P&L from all
executed trades before calculating profit factor.

Research only. No exchange access and no order execution.
"""
from __future__ import annotations

from statistics import mean, median
from typing import Iterable, Mapping


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def pnl_totals(events: Iterable[Mapping[str, object]]) -> dict[str, float | int]:
    values = [safe_float(row.get("net_pnl"), 0.0) for row in events if str(row.get("event", "")).upper() == "CLOSE"]
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = abs(sum(value for value in values if value < 0))
    net_pnl = sum(values)
    if gross_loss > 0:
        pooled_pf = gross_profit / gross_loss
    elif gross_profit > 0:
        pooled_pf = float("inf")
    else:
        pooled_pf = 0.0
    return {
        "trades": len(values),
        "gross_profit": round(gross_profit, 8),
        "gross_loss": round(gross_loss, 8),
        "net_pnl": round(net_pnl, 8),
        "pooled_pf": pooled_pf,
    }


def aggregate_oos(candidate: str, folds: list[dict[str, object]]) -> dict[str, object]:
    valid = [row for row in folds if row.get("status") == "OK"]
    returns = [safe_float(row.get("ret_pct"), 0.0) for row in valid]
    positive = [value for value in returns if value > 0]
    trades = sum(int(safe_float(row.get("executed_trades"), 0.0)) for row in valid)
    gross_profit = sum(safe_float(row.get("gross_profit"), 0.0) for row in valid)
    gross_loss = sum(safe_float(row.get("gross_loss"), 0.0) for row in valid)
    net_pnl = sum(safe_float(row.get("net_pnl"), 0.0) for row in valid)
    pooled_pf = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    avg_ret = mean(returns) if returns else 0.0
    median_ret = median(returns) if returns else 0.0
    worst_fold_ret = min(returns) if returns else 0.0
    worst_dd = max((abs(safe_float(row.get("max_dd_pct"), 0.0)) for row in valid), default=0.0)
    positive_pct = len(positive) / len(valid) * 100.0 if valid else 0.0

    if not valid:
        verdict = "BLOCK_NO_VALID_FOLDS"
    elif trades < 30:
        verdict = "WATCH_TOO_SPARSE"
    elif positive_pct >= 80.0 and pooled_pf >= 1.20 and avg_ret > 0 and worst_dd <= 10.0:
        verdict = "PASS_LONG_WFO"
    elif positive_pct >= 60.0 and pooled_pf >= 1.10 and avg_ret > 0 and worst_fold_ret > -2.5:
        verdict = "WATCH_PROMISING"
    else:
        verdict = "BLOCK_UNSTABLE"

    finite_pf = pooled_pf if pooled_pf != float("inf") else 10.0
    score = (
        avg_ret
        + min(finite_pf, 3.0) * 3.0
        - worst_dd * 0.5
        + positive_pct * 0.05
        - max(0, 30 - trades) * 0.15
        + min(trades, 60) * 0.02
    )
    return {
        "name": candidate,
        "verdict": verdict,
        "valid_folds": len(valid),
        "positive_folds": len(positive),
        "positive_pct": round(positive_pct, 2),
        "total_trades": trades,
        "avg_return_pct": round(avg_ret, 4),
        "median_return_pct": round(median_ret, 4),
        "worst_fold_return_pct": round(worst_fold_ret, 4),
        "pooled_pf": "inf" if pooled_pf == float("inf") else round(pooled_pf, 4),
        "gross_profit": round(gross_profit, 6),
        "gross_loss": round(gross_loss, 6),
        "net_pnl": round(net_pnl, 6),
        "worst_dd_pct": round(worst_dd, 4),
        "score": round(score, 4),
    }
