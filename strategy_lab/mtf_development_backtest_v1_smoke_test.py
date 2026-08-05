#!/usr/bin/env python3
"""Deterministic smoke tests for frozen development accounting."""
from datetime import datetime, timedelta

from strategy_lab.market_data import Candle
from strategy_lab.mtf_development_backtest_v1 import TradeCandidate, contiguous_fold_bounds, resolve_trade, simulate_portfolio


def candle(at: datetime, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle("BTCUSDT", at, open_, high, low, close, 1.0)


def main() -> int:
    start = datetime(2025, 1, 1)
    end = datetime(2026, 7, 1)
    folds = contiguous_fold_bounds(start, end, 10)
    assert len(folds) == 10
    assert folds[0][0] == start and folds[-1][1] == end
    assert all(left < right for left, right in folds)
    assert all(folds[i][1] == folds[i + 1][0] for i in range(9))
    assert sum((right - left).days for left, right in folds) == 546

    at = datetime(2025, 1, 1)
    rows = [candle(at, 100, 103, 97, 101), candle(at + timedelta(minutes=5), 101, 105, 100, 104)]
    exit_time, exit_price, reason, gross, funding, net = resolve_trade(
        rows, symbol="BTCUSDT", side="long", entry_time=at, entry=100, stop=98,
        target=102, study_end=at + timedelta(minutes=10), funding={},
    )
    assert reason == "STOP" and exit_price == 98 and exit_time == at + timedelta(minutes=5)
    assert gross < -0.02 and funding == 0 and net == gross

    candidate = TradeCandidate(
        symbol="BTCUSDT", side="long", fold=0, entry_time=at, entry=100, stop=98, target=104,
        exit_time=at + timedelta(hours=1), exit_price=104, exit_reason="TARGET",
        gross_return_fraction=0.038, funding_return_fraction=0.0, net_return_fraction=0.038,
        structural_risk_fraction=0.02, event_risk_multiplier=1.0, planned_rr=2.0,
        quality_score=70.0, target_timeframe="1h", target_source="test",
    )
    trades, summary = simulate_portfolio([candidate])
    assert len(trades) == 1 and summary["accepted_trades"] == 1
    assert summary["ending_equity"] > summary["initial_equity"]
    assert summary["positive_folds"] == 1 and summary["portfolio_max_drawdown_pct"] >= 0.0
    print("SMOKE MTF V2 development backtest accounting: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
