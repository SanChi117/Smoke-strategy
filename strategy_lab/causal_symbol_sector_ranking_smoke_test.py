#!/usr/bin/env python3
"""Fast invariants for causal symbol/sector ranking."""
from __future__ import annotations

from datetime import datetime, timedelta

from strategy_lab.causal_symbol_sector_ranking import (
    POLICIES,
    annotate_rankings,
    apply_policy,
    causal_snapshot,
)


def trade(
    symbol: str,
    entry: datetime,
    exit_time: datetime,
    r_mult: float,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "side": "long",
        "entry_time": entry.isoformat(timespec="seconds"),
        "exit_time": exit_time.isoformat(timespec="seconds"),
        "entry": 100.0,
        "stop": 98.0,
        "exit": 100.0 + 2.0 * r_mult,
        "r_mult": r_mult,
        "confidence_hint": 60.0,
        "risk_plan_reason": "smoke",
    }


def main() -> int:
    start = datetime(2025, 1, 1)
    rows: list[dict[str, object]] = []
    outcomes = {
        "AUSDT": (1.5, 1.0, 0.8),
        "BUSDT": (-1.0, -0.8, -0.6),
        "CUSDT": (0.5, 0.4, 0.3),
        "DUSDT": (0.2, 0.1, 0.0),
    }
    for symbol, values in outcomes.items():
        for index, value in enumerate(values):
            entry = start + timedelta(days=index)
            rows.append(
                trade(
                    symbol,
                    entry,
                    entry + timedelta(hours=6),
                    value,
                )
            )

    # A large future BUSDT winner must not affect the rank at day 10.
    rows.append(
        trade(
            "BUSDT",
            start + timedelta(days=5),
            start + timedelta(days=20),
            50.0,
        )
    )
    decision_time = start + timedelta(days=10)
    sectors = {
        "AUSDT": ("sector_a",),
        "BUSDT": ("sector_b",),
        "CUSDT": ("sector_c",),
        "DUSDT": ("sector_d",),
    }
    a = causal_snapshot(
        rows,
        decision_time,
        "AUSDT",
        sectors,
        lookback_days=30,
        fee_rate=0.001,
        slippage_rate=0.0002,
        min_symbol_trades=3,
        min_sector_trades=3,
    )
    b = causal_snapshot(
        rows,
        decision_time,
        "BUSDT",
        sectors,
        lookback_days=30,
        fee_rate=0.001,
        slippage_rate=0.0002,
        min_symbol_trades=3,
        min_sector_trades=3,
    )
    assert int(a["history_trades"]) == 12
    assert int(b["history_trades"]) == 12
    assert float(a["symbol_rank_pct"]) > float(b["symbol_rank_pct"])
    assert float(a["sector_rank_pct"]) > float(b["sector_rank_pct"])

    current = [
        trade(
            symbol,
            decision_time,
            decision_time + timedelta(hours=2),
            0.0,
        )
        for symbol in sectors
    ]
    annotated = annotate_rankings(
        rows + current,
        sectors,
        lookback_days=30,
        fee_rate=0.001,
        slippage_rate=0.0002,
    )
    current_rows = [
        row for row in annotated
        if row["entry_time"] == decision_time.isoformat(timespec="seconds")
    ]
    assert len(current_rows) == 4
    by_name = {policy.name: policy for policy in POLICIES}
    control = apply_policy(current_rows, by_name["RANK_CONTROL_NO_OVERLAY"])
    gated = apply_policy(
        current_rows,
        by_name["RANK_HYBRID_BOTTOM_QUARTILE_GATE"],
    )
    for before, after in zip(current_rows, control):
        assert before["entry_time"] == after["entry_time"]
        assert before["exit_time"] == after["exit_time"]
        assert float(after["risk_multiplier"]) == 1.0
        assert after["ranking_block"] == "false"
    gated_by_symbol = {row["symbol"]: row for row in gated}
    assert gated_by_symbol["BUSDT"]["ranking_block"] == "true"
    assert gated_by_symbol["AUSDT"]["ranking_block"] == "false"
    print("causal symbol/sector ranking smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
