#!/usr/bin/env python3
"""Regression test for indexed causal-history scoring.

The optimized implementation must be decision-identical to the transparent slow
reference, including overlapping trades, delayed exits and rolling-window expiry.
"""

from __future__ import annotations

from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta

from strategy_lab import structure_learning as structure
from strategy_lab import trade_quality_score as quality
from strategy_lab.causal_history import (
    score_quality_trades,
    score_structure_trades,
    structure_decision_for_scope,
)


def slow_quality(trades, cfg):
    ordered = sorted(trades, key=lambda t: (t.entry_time, t.symbol, t.side))
    out = []
    for trade in ordered:
        start = trade.entry_time - timedelta(days=cfg.lookback_days)
        history = [
            item for item in ordered
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
        out.append(quality.ScoredTrade(
            trade.symbol, trade.side, trade.entry_time.isoformat(),
            trade.exit_time.isoformat() if trade.exit_time else "", trade.kind, trade.source,
            trade.setup_type, trade.trend_context, trade.volatility_regime,
            round(trade.r_mult, 6), "win" if trade.r_mult > 0 else "loss" if trade.r_mult < 0 else "flat",
            round(stop_pct, 4), len(history), round(hp, 4), round(hw, 4), round(ha, 4), hs,
            round(ss, 2), round(ts, 2), round(vs, 2), round(trs, 2), round(es, 2), round(conf, 2),
            quality.decision(conf, cfg), quality.tp_mode(trade, conf), quality.risk_mod(conf, cfg),
        ))
    return out


def slow_structure(trades, cfg):
    ordered = sorted(trades, key=lambda row: (row.entry_time, row.symbol, row.side))
    completed = sorted(
        (row for row in ordered if row.exit_time is not None),
        key=lambda row: (row.exit_time, row.entry_time, row.symbol, row.side),
    )
    known = []
    pointer = 0
    out = []
    for trade in ordered:
        while pointer < len(completed) and completed[pointer].exit_time <= trade.entry_time:
            completed_trade = completed[pointer]
            if completed_trade is not trade:
                known.append(completed_trade)
            pointer += 1
        cutoff = trade.entry_time - timedelta(days=cfg.lookback_days)
        history = deque(
            item for item in known
            if cutoff <= item.entry_time < trade.entry_time
            and item.exit_time is not None
            and item.exit_time <= trade.entry_time
        )
        stats = structure.choose_history_stats(trade, history, cfg)
        decision, effective_score = structure_decision_for_scope(stats, cfg)
        out.append(structure.ScoredStructureTrade(
            trade.symbol, trade.side, trade.entry_time.isoformat(),
            trade.exit_time.isoformat() if trade.exit_time else "", trade.kind, trade.source,
            trade.setup_type, trade.trend_context, trade.volatility_regime, trade.structure_type,
            trade.risk_bucket, trade.session, round(trade.r_mult, 6),
            "win" if trade.r_mult > 0 else "loss" if trade.r_mult < 0 else "flat",
            structure.structure_key(trade), structure.fallback_key(trade), stats.key_scope,
            stats.trades, stats.pf, stats.winrate, stats.avg_r, stats.max_loss_streak,
            stats.score, decision, structure.target_policy(trade, effective_score),
            structure.risk_modifier(effective_score, cfg),
        ))
    return out


def make_rows():
    base = datetime(2026, 1, 1)
    qrows = []
    srows = []
    symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"]
    setups = ["pullback", "pullback_resumption", "breakout", "ignition"]
    for idx in range(120):
        entry = base + timedelta(hours=idx * 9)
        duration = (idx % 7 + 1) * 3
        exit_time = None if idx % 19 == 0 else entry + timedelta(hours=duration)
        symbol = symbols[idx % len(symbols)]
        side = "short" if idx % 3 else "long"
        setup = setups[idx % len(setups)]
        trend = "trend" if idx % 5 else "range"
        vol = ["normal", "low", "high"][idx % 3]
        result = [1.75, -1.0, 0.35, -0.45, 0.8][idx % 5]
        entry_price = 100.0 + idx * 0.1
        stop = entry_price * (1.016 if side == "short" else 0.984)
        exit_price = entry_price - result if side == "short" else entry_price + result
        qrows.append(quality.TradeRow(
            symbol, side, entry, exit_time, entry_price, stop, exit_price, result,
            kind=setup, source="synthetic", trend_context=trend,
            volatility_regime=vol, setup_type=setup,
        ))
        srows.append(structure.TradeRow(
            symbol, side, entry, exit_time, entry_price, stop, exit_price, result,
            kind=setup, source="synthetic", setup_type=setup, trend_context=trend,
            volatility_regime=vol,
            structure_type="trend_pullback" if "pullback" in setup else "breakout_continuation",
            risk_bucket=["tight", "normal", "wide"][idx % 3],
            session=["asia", "europe", "us"][idx % 3],
        ))
    return qrows, srows


def main() -> None:
    qrows, srows = make_rows()
    qcfg = quality.QualityConfig(lookback_days=12, min_history_trades=3, take_threshold=64, watch_threshold=52)
    scfg = structure.StructureLearningConfig(lookback_days=12, min_exact_trades=4, min_fallback_trades=7, take_threshold=63, watch_threshold=52)
    expected_q = [asdict(row) for row in slow_quality(qrows, qcfg)]
    actual_q = [asdict(row) for row in score_quality_trades(qrows, qcfg)]
    assert actual_q == expected_q, "optimized quality history changed decisions"
    expected_s = [asdict(row) for row in slow_structure(srows, scfg)]
    actual_s = [asdict(row) for row in score_structure_trades(srows, scfg)]
    assert actual_s == expected_s, "optimized structure history changed decisions"
    print("causal_history_fast_smoke_test: PASS")


if __name__ == "__main__":
    main()
