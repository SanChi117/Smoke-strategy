#!/usr/bin/env python3
"""Regression test: simultaneous candidates must not be chosen alphabetically."""

from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.config import RiskProfile
from strategy_lab.portfolio_simulator import simulate_dynamic_portfolio
from strategy_lab.rolling_symbol_strength import CostConfig, Trade


def main() -> int:
    entry_time = datetime(2026, 1, 1, 12, 0)
    exit_time = entry_time + timedelta(hours=1)
    weak_alphabetic_first = Trade(
        symbol="AAAUSDT", side="long", entry_time=entry_time, exit_time=exit_time,
        entry=100.0, stop=99.0, exit=99.0, r_mult=-1.0,
    )
    strong_ranked = Trade(
        symbol="ZZZUSDT", side="long", entry_time=entry_time, exit_time=exit_time,
        entry=100.0, stop=99.0, exit=102.0, r_mult=2.0,
    )
    profile = RiskProfile(
        name="priority_test", initial_cash=100.0, leverage=1.0,
        base_risk_pct=0.01, max_risk_pct=0.01,
        watch_risk_multiplier=1.0, take_risk_multiplier=1.0,
        max_positions=1, max_margin_pct=0.50, max_symbol_positions=1,
        daily_loss_limit_pct=1.0, weekly_loss_limit_pct=1.0,
        max_loss_streak_halt=99, reinvest=False, notes="test",
    )
    risks = {
        (weak_alphabetic_first.symbol, weak_alphabetic_first.side, entry_time): 0.01,
        (strong_ranked.symbol, strong_ranked.side, entry_time): 0.01,
    }
    priorities = {
        (weak_alphabetic_first.symbol, weak_alphabetic_first.side, entry_time): 10.0,
        (strong_ranked.symbol, strong_ranked.side, entry_time): 90.0,
    }
    result = simulate_dynamic_portfolio(
        [weak_alphabetic_first, strong_ranked],
        risks,
        profile,
        CostConfig(fee_rate=0.0, slippage_rate=0.0),
        "priority_test",
        priority_scores=priorities,
    )
    assert result.trades == 1, result
    assert result.ret_pct > 0, result
    print("portfolio_priority_smoke_test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
