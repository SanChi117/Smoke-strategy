#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from strategy_lab.p9_development_profitability_v1 import ResolvedOutcome, resolve_outcome, simulate_portfolio, summarize_portfolio


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float


def record(direction: str = "LONG", stop: float = 98.0, target: float = 101.0) -> dict:
    return {
        "observation_key": "BTCUSDT|LONG|0|2024-01-01T00:00:00+00:00|LIQUIDITY_RAID_REVERSAL|fp_test",
        "observation": {"symbol": "BTCUSDT", "direction": direction, "fold": 0,
                        "timestamp": "2024-01-01T00:00:00+00:00", "family": "LIQUIDITY_RAID_REVERSAL",
                        "decision": "HIGH_CONFIDENCE_SETUP", "fingerprint": "fp_test"},
        "reference_geometry": {"entry_price": 100.0, "stop_price": stop, "target_price": target},
        "p5": {"economics": {"net_rr": 1.5, "stop_move_pct": 2.0, "effective_net_loss_pct": 2.15},
               "position": {"margin_pct_equity": 1.25}},
        "p6": {"score_0_100": 85.0},
    }


def outcome(i: int, signal: datetime, exit_time: datetime, direction: str = "LONG", net_return_pct: float = 1.0) -> ResolvedOutcome:
    return ResolvedOutcome(
        observation_key=f"key-{i}", fingerprint=f"fp-{i}", symbol="BTCUSDT", direction=direction,
        fold=i % 10, family="LIQUIDITY_RAID_REVERSAL", decision="HIGH_CONFIDENCE_SETUP",
        signal_time=signal.isoformat(), executable_status="EXECUTABLE", raw_entry_price=100.0,
        entry_fill_price=100.02, stop_price=99.0, target_price=102.0, raw_exit_price=102.0,
        exit_fill_price=101.9796, exit_time=exit_time.isoformat(), exit_reason="TARGET",
        bars_held=2, minutes_held=10, same_bar_ambiguity=False, gross_return_pct=1.95,
        net_return_pct=net_return_pct, net_r=net_return_pct / 1.15, mae_pct=0.2, mfe_pct=2.0,
        p5_net_rr=1.7, p6_score_0_100=85.0, reference_stop_move_pct=1.0,
        reference_margin_pct_equity=2.5,
    )


def main() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    positive = resolve_outcome(record(), [Bar(start, 100.0, 102.0, 99.5, 101.5)])
    assert positive.executable_status == "EXECUTABLE"
    assert positive.exit_reason == "TARGET"
    assert positive.net_return_pct is not None and positive.net_return_pct > 0

    ambiguous = resolve_outcome(record(), [Bar(start, 100.0, 102.0, 97.0, 100.0)])
    assert ambiguous.exit_reason == "STOP_FIRST"
    assert ambiguous.same_bar_ambiguity is True
    assert ambiguous.net_return_pct is not None and ambiguous.net_return_pct < 0

    gap = resolve_outcome(record(), [Bar(start, 102.0, 103.0, 101.0, 102.5)])
    assert gap.executable_status == "NON_EXECUTABLE_GAP"

    ended = resolve_outcome(record(target=110.0), [
        Bar(start, 100.0, 100.5, 99.5, 100.2),
        Bar(start + timedelta(minutes=5), 100.2, 100.6, 99.8, 100.4),
    ])
    assert ended.exit_reason == "END_OF_DATA"
    assert ended.bars_held == 2

    batch = [outcome(i, start, start + timedelta(hours=1), direction="LONG" if i % 2 == 0 else "SHORT") for i in range(6)]
    portfolio = simulate_portfolio(batch)
    assert portfolio["executed_count"] == 4
    assert portfolio["capacity_rejected_count"] == 2
    summary = summarize_portfolio(portfolio)
    assert summary["executed_count"] == 4
    assert summary["ending_equity"] > 10000.0
    assert summary["max_drawdown_pct"] == 0.0

    reversed_portfolio = simulate_portfolio(tuple(reversed(batch)))
    assert portfolio["ending_equity"] == reversed_portfolio["ending_equity"]
    assert [row["fingerprint"] for row in portfolio["executed"]] == [row["fingerprint"] for row in reversed_portfolio["executed"]]
    print("p9 development profitability smoke tests: PASS")


if __name__ == "__main__":
    main()
