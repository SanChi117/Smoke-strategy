#!/usr/bin/env python3
"""Causal replacements for adaptive research layers.

A result may influence a later decision only after the source trade has closed.
The original lookback meaning is preserved: the source trade entry must belong
to the configured lookback window, and its exit must already be known.

A structure veto is allowed only when the history is specific enough to the current
setup (exact or setup-level fallback). Loose/global history may reduce conviction,
but it cannot block a newly introduced setup merely because unrelated patterns were
weak.
"""

from __future__ import annotations

from collections import deque
from datetime import timedelta

from strategy_lab import rolling_symbol_strength as rolling
from strategy_lab import structure_learning as structure
from strategy_lab import trade_quality_score as quality


def score_quality_trades(trades: list[quality.TradeRow], cfg: quality.QualityConfig | None = None) -> list[quality.ScoredTrade]:
    cfg = cfg or quality.QualityConfig()
    ordered = sorted(trades, key=lambda t: (t.entry_time, t.symbol, t.side))
    out: list[quality.ScoredTrade] = []
    for trade in ordered:
        start = trade.entry_time - timedelta(days=cfg.lookback_days)
        history = [
            item
            for item in ordered
            if item is not trade
            and item.symbol == trade.symbol
            and item.exit_time is not None
            and start <= item.entry_time < trade.entry_time
            and item.exit_time <= trade.entry_time
        ]
        ss, hp, hw, ha, hs = quality.symbol_score(history, cfg)
        stop_pct = abs(trade.entry - trade.stop) / trade.entry * 100 if trade.entry > 0 else 0.0
        ts = quality.trend_score(trade.trend_context)
        vs = quality.volatility_score(trade.volatility_regime, stop_pct)
        trs = quality.target_score(trade, stop_pct)
        es = quality.entry_score(trade.setup_type, stop_pct)
        conf = quality.clamp(ss * 0.35 + ts * 0.20 + vs * 0.15 + trs * 0.15 + es * 0.15)
        out.append(
            quality.ScoredTrade(
                trade.symbol,
                trade.side,
                trade.entry_time.isoformat(),
                trade.exit_time.isoformat() if trade.exit_time else "",
                trade.kind,
                trade.source,
                trade.setup_type,
                trade.trend_context,
                trade.volatility_regime,
                round(trade.r_mult, 6),
                "win" if trade.r_mult > 0 else "loss" if trade.r_mult < 0 else "flat",
                round(stop_pct, 4),
                len(history),
                round(hp, 4),
                round(hw, 4),
                round(ha, 4),
                hs,
                round(ss, 2),
                round(ts, 2),
                round(vs, 2),
                round(trs, 2),
                round(es, 2),
                round(conf, 2),
                quality.decision(conf, cfg),
                quality.tp_mode(trade, conf),
                quality.risk_mod(conf, cfg),
            )
        )
    return out


def structure_decision_for_scope(stats: structure.StructureStats, cfg: structure.StructureLearningConfig) -> tuple[str, float]:
    """Return decision and effective score for risk/target policy.

    Exact and setup-level fallback histories are relevant enough to veto. Loose,
    global and cold-start histories are context only, so they produce WATCH rather
    than a hard SKIP. Their raw score is still reported for auditability.
    """

    if stats.key_scope in {"exact", "fallback"}:
        return structure.decision(stats.score, cfg), stats.score
    effective = max(float(stats.score), float(cfg.watch_threshold))
    return "WATCH", effective


def score_structure_trades(
    trades: list[structure.TradeRow],
    cfg: structure.StructureLearningConfig | None = None,
) -> list[structure.ScoredStructureTrade]:
    cfg = cfg or structure.StructureLearningConfig()
    ordered = sorted(trades, key=lambda row: (row.entry_time, row.symbol, row.side))
    completed = sorted(
        (row for row in ordered if row.exit_time is not None),
        key=lambda row: (row.exit_time, row.entry_time, row.symbol, row.side),
    )
    known: list[structure.TradeRow] = []
    pointer = 0
    out: list[structure.ScoredStructureTrade] = []

    for trade in ordered:
        while pointer < len(completed) and completed[pointer].exit_time <= trade.entry_time:
            completed_trade = completed[pointer]
            if completed_trade is not trade:
                known.append(completed_trade)
            pointer += 1

        cutoff = trade.entry_time - timedelta(days=cfg.lookback_days)
        history = deque(
            item
            for item in known
            if cutoff <= item.entry_time < trade.entry_time
            and item.exit_time is not None
            and item.exit_time <= trade.entry_time
        )
        stats = structure.choose_history_stats(trade, history, cfg)
        dec, effective_score = structure_decision_for_scope(stats, cfg)
        out.append(
            structure.ScoredStructureTrade(
                trade.symbol,
                trade.side,
                trade.entry_time.isoformat(),
                trade.exit_time.isoformat() if trade.exit_time else "",
                trade.kind,
                trade.source,
                trade.setup_type,
                trade.trend_context,
                trade.volatility_regime,
                trade.structure_type,
                trade.risk_bucket,
                trade.session,
                round(trade.r_mult, 6),
                "win" if trade.r_mult > 0 else "loss" if trade.r_mult < 0 else "flat",
                structure.structure_key(trade),
                structure.fallback_key(trade),
                stats.key_scope,
                stats.trades,
                stats.pf,
                stats.winrate,
                stats.avg_r,
                stats.max_loss_streak,
                stats.score,
                dec,
                structure.target_policy(trade, effective_score),
                structure.risk_modifier(effective_score, cfg),
            )
        )
    return out


def build_rolling_trades(
    trades,
    start,
    end,
    rcfg: rolling.RollingConfig,
    cost: rolling.CostConfig,
) -> tuple[list[rolling.Trade], int, float]:
    all_symbols = sorted({trade.symbol for trade in trades})
    eligible: list[rolling.Trade] = []
    seen = set()
    selected_counts: list[int] = []
    windows = 0

    cur = start + timedelta(days=rcfg.lookback_days)
    while cur < end:
        lb_start = cur - timedelta(days=rcfg.lookback_days)
        fwd_end = min(end, cur + timedelta(days=rcfg.rebalance_days))
        lookback = [
            trade
            for trade in trades
            if lb_start <= trade.entry_time < cur
            and trade.exit_time <= cur
        ]
        selected = set(rolling.select_symbols(lookback, all_symbols, rcfg.top_n, cost))
        selected_counts.append(len(selected))
        windows += 1
        for trade in rolling.trades_between(trades, cur, fwd_end):
            if trade.symbol not in selected:
                continue
            key = (trade.symbol, trade.entry_time, trade.side)
            if key in seen:
                continue
            seen.add(key)
            eligible.append(trade)
        cur = fwd_end

    avg_selected = sum(selected_counts) / len(selected_counts) if selected_counts else 0.0
    return sorted(eligible, key=lambda trade: (trade.entry_time, trade.symbol, trade.side)), windows, avg_selected


def apply_causal_patches() -> None:
    """Patch the existing public modules in one explicit place."""
    quality.score_trades = score_quality_trades
    structure.score_structure_trades = score_structure_trades
    rolling.build_rolling_trades = build_rolling_trades
