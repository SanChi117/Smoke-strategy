#!/usr/bin/env python3
"""Regression tests for no-lookahead adaptive history."""

from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.rolling_symbol_strength import CostConfig, RollingConfig, Trade, build_rolling_trades
from strategy_lab.structure_learning import StructureLearningConfig, TradeRow as StructureTrade, score_structure_trades
from strategy_lab.trade_quality_score import QualityConfig, TradeRow as QualityTrade, score_trades


def main() -> None:
    base = datetime(2026, 1, 1, 10, 0)

    quality = [
        QualityTrade("AAAUSDT", "long", base, base + timedelta(hours=8), 100, 98, 104, 2.0, setup_type="pullback", trend_context="trend", volatility_regime="normal"),
        QualityTrade("AAAUSDT", "long", base + timedelta(hours=2), base + timedelta(hours=3), 100, 98, 98, -1.0, setup_type="pullback", trend_context="trend", volatility_regime="normal"),
        QualityTrade("AAAUSDT", "long", base + timedelta(hours=9), base + timedelta(hours=10), 100, 98, 104, 2.0, setup_type="pullback", trend_context="trend", volatility_regime="normal"),
    ]
    q_rows = score_trades(quality, QualityConfig(min_history_trades=1))
    assert q_rows[1].history_trades == 0, "open overlapping outcome leaked into quality history"
    assert q_rows[2].history_trades == 2, "closed outcomes missing from quality history"

    structure = [
        StructureTrade("AAAUSDT", "long", base, base + timedelta(hours=8), 100, 98, 104, 2.0, setup_type="pullback", trend_context="trend", volatility_regime="normal", structure_type="continuation", risk_bucket="normal", session="europe"),
        StructureTrade("AAAUSDT", "long", base + timedelta(hours=2), base + timedelta(hours=3), 100, 98, 98, -1.0, setup_type="pullback", trend_context="trend", volatility_regime="normal", structure_type="continuation", risk_bucket="normal", session="europe"),
        StructureTrade("AAAUSDT", "long", base + timedelta(hours=9), base + timedelta(hours=10), 100, 98, 104, 2.0, setup_type="pullback", trend_context="trend", volatility_regime="normal", structure_type="continuation", risk_bucket="normal", session="europe"),
    ]
    s_rows = score_structure_trades(structure, StructureLearningConfig(min_exact_trades=1, min_fallback_trades=1))
    assert s_rows[1].history_trades == 0, "open overlapping outcome leaked into structure history"
    assert s_rows[2].history_trades == 2, "closed outcomes missing from structure history"

    rolling: list[Trade] = []
    for idx in range(3):
        entry = base + timedelta(days=idx)
        rolling.append(Trade("AAAUSDT", "long", entry, base + timedelta(days=40 + idx), 100, 98, 104, 2.0))
        rolling.append(Trade("BBBUSDT", "long", entry, entry + timedelta(hours=1), 100, 98, 104, 2.0))
    rolling.append(Trade("AAAUSDT", "long", base + timedelta(days=31), base + timedelta(days=31, hours=2), 100, 98, 104, 2.0))
    rolling.append(Trade("BBBUSDT", "long", base + timedelta(days=31), base + timedelta(days=31, hours=2), 100, 98, 104, 2.0))
    selected, _windows, _avg = build_rolling_trades(
        rolling,
        base,
        base + timedelta(days=40),
        RollingConfig(lookback_days=30, rebalance_days=7, top_n=1),
        CostConfig(),
    )
    assert any(t.symbol == "BBBUSDT" for t in selected), "closed winner was not selectable"
    assert not any(t.symbol == "AAAUSDT" and t.entry_time >= base + timedelta(days=30) for t in selected), "open future result leaked into rolling selector"
    print("CAUSAL HISTORY SMOKE TEST OK")


if __name__ == "__main__":
    main()
