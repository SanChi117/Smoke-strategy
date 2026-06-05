#!/usr/bin/env python3
"""Universe selector for Smoke Strategy Lab.

The selector may receive a very wide coin pool. It does not assume all coins
are tradable. It ranks and classifies symbols from their historical trade
behavior so the strategy can decide what to allow.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Iterable, Any

from strategy_lab.rolling_symbol_strength import Trade, pf, max_loss_streak
from strategy_lab.schemas import CoinUniverseRow


@dataclass(frozen=True)
class UniverseConfig:
    min_trades: int = 20
    allow_top_n: int = 20
    trend_pf_min: float = 1.20
    clean_pf_min: float = 1.10
    chaotic_pf_max: float = 0.95
    max_loss_streak_clean: int = 5
    fallback_when_empty: bool = True
    fallback_min_pf: float = 0.90
    fallback_min_avg_r: float = -0.05


def classify_symbol(trades: list[Trade], cfg: UniverseConfig) -> CoinUniverseRow:
    vals = [float(t.r_mult) for t in trades]
    wins = sum(1 for v in vals if v > 0)
    pfx = pf(vals)
    avg_r = mean(vals) if vals else 0.0
    total_r = sum(vals)
    streak = max_loss_streak(vals)
    winrate = wins / len(vals) if vals else 0.0

    long_vals = [float(t.r_mult) for t in trades if t.side == "long"]
    short_vals = [float(t.r_mult) for t in trades if t.side == "short"]
    long_pf = pf(long_vals) if long_vals else 0.0
    short_pf = pf(short_vals) if short_vals else 0.0
    side_balance = min(long_pf, short_pf) if long_vals and short_vals else max(long_pf, short_pf)

    sample_score = min(20.0, len(vals) / max(cfg.min_trades, 1) * 20.0)
    pf_score = max(-25.0, min(35.0, (pfx - 1.0) * 25.0))
    avg_score = max(-20.0, min(30.0, avg_r * 30.0))
    win_score = (winrate - 0.50) * 30.0
    balance_score = max(-10.0, min(10.0, (side_balance - 1.0) * 10.0))
    streak_penalty = min(20.0, streak * 3.0)
    score = sample_score + pf_score + avg_score + win_score + balance_score - streak_penalty

    if len(vals) < cfg.min_trades:
        coin_class = "insufficient_history"
        allowed_setups = "none"
        risk_multiplier = 0.0
        reason = "not enough trades for reliable classification"
    elif pfx <= cfg.chaotic_pf_max or avg_r < 0 or streak > cfg.max_loss_streak_clean + 2:
        coin_class = "chaotic_avoid"
        allowed_setups = "none"
        risk_multiplier = 0.0
        reason = "poor PF/avgR or unstable loss streak"
    elif pfx >= cfg.trend_pf_min and avg_r > 0.15 and streak <= cfg.max_loss_streak_clean:
        coin_class = "trend_friendly"
        allowed_setups = "continuation,pullback,breakout,ignition"
        risk_multiplier = 1.0
        reason = "strong PF and positive average R"
    elif pfx >= cfg.clean_pf_min and avg_r > 0.05:
        coin_class = "volatile_clean"
        allowed_setups = "continuation,range_rotation"
        risk_multiplier = 0.75
        reason = "tradable but needs controlled risk"
    else:
        coin_class = "watch_only"
        allowed_setups = "watch"
        risk_multiplier = 0.35
        reason = "not bad enough to avoid, not strong enough for full risk"

    return CoinUniverseRow(
        symbol=trades[0].symbol if trades else "UNKNOWN",
        trades=len(vals),
        winrate=round(winrate, 4),
        avg_r=round(avg_r, 4),
        pf=round(pfx, 4),
        total_r=round(total_r, 4),
        score=round(score, 4),
        coin_class=coin_class,
        allowed_setups=allowed_setups,
        risk_multiplier=risk_multiplier,
        reason=reason,
    )


def rank_universe(trades: Iterable[Trade], cfg: UniverseConfig | None = None) -> list[CoinUniverseRow]:
    cfg = cfg or UniverseConfig()
    by_symbol: dict[str, list[Trade]] = {}
    for trade in trades:
        by_symbol.setdefault(trade.symbol, []).append(trade)
    rows = [classify_symbol(sorted(items, key=lambda t: t.entry_time), cfg) for items in by_symbol.values()]
    return sorted(rows, key=lambda r: (r.score, r.pf, r.avg_r, r.trades), reverse=True)


def allowed_symbols(rows: list[CoinUniverseRow], cfg: UniverseConfig | None = None) -> set[str]:
    cfg = cfg or UniverseConfig()
    allowed_classes = {"trend_friendly", "volatile_clean", "watch_only"}
    candidates = [row for row in rows if row.coin_class in allowed_classes and row.risk_multiplier > 0]
    if candidates:
        return {row.symbol for row in candidates[: cfg.allow_top_n]}

    if not cfg.fallback_when_empty:
        return set()

    # Research fallback: if strict classification blocks every symbol, allow the
    # best-ranked symbols that are not clearly broken. This prevents the whole
    # pipeline from producing zero executed trades while still avoiding the worst
    # coins. The ranking file keeps the original strict class visible.
    fallback = [
        row for row in rows
        if row.coin_class != "insufficient_history"
        and (row.pf >= cfg.fallback_min_pf or row.avg_r >= cfg.fallback_min_avg_r)
    ]
    return {row.symbol for row in fallback[: cfg.allow_top_n]}


def rows_as_dicts(rows: list[CoinUniverseRow]) -> list[dict[str, Any]]:
    return [asdict(row) for row in rows]
