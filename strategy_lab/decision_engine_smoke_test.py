#!/usr/bin/env python3
"""Smoke test for the layered validated-baseline decision engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from strategy_lab.decision_engine import HistoricalTrade, evaluate_candidate


@dataclass(frozen=True)
class Plan:
    symbol: str = "INJUSDT"
    side: str = "short"
    entry_time: datetime = datetime(2026, 6, 1, 12, 0)
    entry: float = 10.0
    stop: float = 10.16
    target: float = 9.744
    target_rr: float = 1.6
    setup_type: str = "pullback"
    trend_context: str = "trend"
    volatility_regime: str = "normal"
    structure_type: str = "trend_pullback"
    confidence_hint: float = 70.0
    reason: str = "setup=pullback|side=short|trend=trend|dir=down|structure=trend_pullback|vol=normal|vr=1.2|candle=neutral|liq=none"


def history() -> list[HistoricalTrade]:
    rows: list[HistoricalTrade] = []
    base = datetime(2026, 5, 1, 12, 0)
    for idx in range(24):
        entry = base + timedelta(hours=idx * 12)
        win = idx % 4 != 0
        rows.append(
            HistoricalTrade(
                symbol="INJUSDT",
                side="short",
                entry_time=entry,
                exit_time=entry + timedelta(hours=4),
                entry=10.0,
                stop=10.16,
                exit=9.744 if win else 10.16,
                r_mult=1.6 if win else -1.0,
                setup_type="pullback",
                trend_context="trend",
                volatility_regime="normal",
                structure_type="trend_pullback",
            )
        )
    return rows


def main() -> None:
    result = evaluate_candidate(
        Plan(),
        history(),
        data_fresh=True,
        candle_closed=True,
        universe_allowed=True,
    )
    assert result.ready, result.as_dict()
    assert result.final_status == "READY"
    names = {layer.layer for layer in result.layers}
    required = {"DATA_FRESHNESS", "CLOSED_CANDLE", "UNIVERSE", "SETUP", "DIRECTION", "QUALITY", "STRUCTURE_LEARNING", "RISK", "PORTFOLIO"}
    assert required.issubset(names)

    forming = evaluate_candidate(
        Plan(),
        history(),
        data_fresh=True,
        candle_closed=False,
        universe_allowed=True,
    )
    assert not forming.ready
    assert any(layer.layer == "CLOSED_CANDLE" and layer.status == "BLOCK" for layer in forming.layers)
    print("DECISION ENGINE SMOKE TEST OK")


if __name__ == "__main__":
    main()
