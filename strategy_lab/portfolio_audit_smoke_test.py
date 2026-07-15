#!/usr/bin/env python3
"""Regression test: audit collection must not change portfolio decisions or P&L."""

from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.config import RISK_PROFILES
from strategy_lab.portfolio_simulator import simulate_dynamic_portfolio
from strategy_lab.rolling_symbol_strength import CostConfig, Trade


def make_trade(symbol: str, hour: int, r_mult: float, duration: int = 2) -> Trade:
    entry_time = datetime(2026, 1, 1) + timedelta(hours=hour)
    entry = 100.0
    stop = 101.0
    exit_price = entry - r_mult
    return Trade(
        symbol=symbol,
        side="short",
        entry_time=entry_time,
        exit_time=entry_time + timedelta(hours=duration),
        entry=entry,
        stop=stop,
        exit=exit_price,
        r_mult=r_mult,
        source="audit_test",
        kind="pullback",
    )


def main() -> None:
    trades = [
        make_trade("AAAUSDT", 0, 1.0, 4),
        make_trade("BBBUSDT", 0, -1.0, 4),
        make_trade("CCCUSDT", 0, 1.5, 4),  # skipped by max positions
        make_trade("AAAUSDT", 1, 0.5, 2),  # skipped by max positions/symbol exposure
        make_trade("DDDUSDT", 5, 1.0, 2),
    ]
    risks = {(trade.symbol, trade.side, trade.entry_time): 0.005 for trade in trades}
    priorities = {
        ("AAAUSDT", "short", trades[0].entry_time): 80.0,
        ("BBBUSDT", "short", trades[1].entry_time): 70.0,
        ("CCCUSDT", "short", trades[2].entry_time): 60.0,
        ("AAAUSDT", "short", trades[3].entry_time): 90.0,
        ("DDDUSDT", "short", trades[4].entry_time): 50.0,
    }
    profile = RISK_PROFILES["research_500"]
    cost = CostConfig(fee_rate=0.001, slippage_rate=0.0002)
    plain = simulate_dynamic_portfolio(trades, risks, profile, cost, "plain", priority_scores=priorities)
    audit: list[dict] = []
    audited = simulate_dynamic_portfolio(
        trades, risks, profile, cost, "plain", priority_scores=priorities, audit_events=audit
    )
    assert plain == audited, "audit collection changed the portfolio result"
    closes = [row for row in audit if row["event"] == "CLOSE"]
    skips = [row for row in audit if row["event"] == "SKIP"]
    opens = [row for row in audit if row["event"] == "OPEN"]
    assert len(closes) == plain.trades
    assert len(opens) == plain.trades
    assert len(skips) == plain.skipped
    assert any(row["reason"] == "max_positions" for row in skips)
    assert all("net_pnl" in row and "total_fee" in row for row in closes)
    print("portfolio_audit_smoke_test: PASS")


if __name__ == "__main__":
    main()
