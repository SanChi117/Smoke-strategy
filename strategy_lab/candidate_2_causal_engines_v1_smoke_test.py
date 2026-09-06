#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from strategy_lab.market_data import Candle
from strategy_lab.candidate_2_hypothesis_contract_v1 import PersistenceState, RegimeState, serialize_outcome_blind
from strategy_lab.candidate_2_regime_engine_v1 import classify_regime
from strategy_lab.candidate_2_acceptance_engine_v1 import evaluate_persistence
from strategy_lab.candidate_2_target_reachability_v1 import evaluate_target


def candles_up(n: int = 64) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    px = 100.0
    for i in range(n):
        drift = 0.22 + (0.04 if i % 5 else -0.03)
        o = px
        c = px + drift
        rows.append(Candle("TESTUSDT", start + timedelta(minutes=5*i), o, max(o,c)+0.12, min(o,c)-0.08, c, 1000+i))
        px = c
    return rows


def test_no_future_regime() -> None:
    rows = candles_up()
    t = rows[-5].time
    a = classify_regime(rows, t)
    mutated = rows[:-4] + [Candle(c.symbol, c.time, c.open, c.high*5, c.low/5, c.close*3, c.volume*10) for c in rows[-4:]]
    b = classify_regime(mutated, t)
    assert a == b
    assert a.causal_window_end <= t
    assert a.regime in set(RegimeState)
    serialize_outcome_blind(a)


def test_acceptance_and_refailure() -> None:
    rows = candles_up()
    trigger = rows[-6].time
    accepted = evaluate_persistence(
        rows,
        scenario_id="s1",
        direction="LONG",
        trigger_time=trigger,
        evaluated_at=rows[-1].time,
        trigger_price=rows[-6].open,
        protected_price=rows[-6].open - 1.5,
    )
    assert accepted.persistence_state in {PersistenceState.ACCEPTED, PersistenceState.REJECTED}
    assert accepted.causal_window_end <= rows[-1].time
    serialize_outcome_blind(accepted)

    bad = list(rows)
    first = bad[-6]
    bad[-6] = Candle(first.symbol, first.time, first.open, first.open+0.05, first.open-2.0, first.open-0.8, first.volume)
    rejected = evaluate_persistence(
        bad,
        scenario_id="s2",
        direction="LONG",
        trigger_time=bad[-6].time,
        evaluated_at=bad[-1].time,
        trigger_price=bad[-6].open,
        protected_price=bad[-6].open-1.0,
    )
    assert rejected.accepted is False
    assert rejected.persistence_state == PersistenceState.INVALIDATED
    assert rejected.immediate_refailure is True


def test_target_reachability() -> None:
    rows = candles_up()
    entry = rows[-1].close
    near = evaluate_target(
        rows,
        scenario_id="s3",
        direction="LONG",
        evaluated_at=rows[-1].time,
        entry_price=entry,
        stop_price=entry-0.8,
        target_id="t-near",
        target_price=entry+1.8,
        structural_reason="causal_swing_liquidity",
    )
    assert near.causal_window_end <= rows[-1].time
    serialize_outcome_blind(near)

    far = evaluate_target(
        rows,
        scenario_id="s4",
        direction="LONG",
        evaluated_at=rows[-1].time,
        entry_price=entry,
        stop_price=entry-0.8,
        target_id="t-far",
        target_price=entry+50.0,
        structural_reason="distant_liquidity",
    )
    assert far.reachable is False
    assert "target_outside_causal_volatility_horizon" in far.rejection_reasons


def test_future_mutation_does_not_change_acceptance() -> None:
    rows = candles_up()
    evaluated = rows[-4].time
    base = evaluate_persistence(
        rows,
        scenario_id="s5",
        direction="LONG",
        trigger_time=rows[-8].time,
        evaluated_at=evaluated,
        trigger_price=rows[-8].open,
        protected_price=rows[-8].open-1.5,
    )
    changed = list(rows)
    for i in range(len(changed)-3, len(changed)):
        c = changed[i]
        changed[i] = Candle(c.symbol, c.time, c.open, c.high*4, c.low/4, c.close*2, c.volume)
    other = evaluate_persistence(
        changed,
        scenario_id="s5",
        direction="LONG",
        trigger_time=rows[-8].time,
        evaluated_at=evaluated,
        trigger_price=rows[-8].open,
        protected_price=rows[-8].open-1.5,
    )
    assert base == other


def main() -> int:
    test_no_future_regime()
    test_acceptance_and_refailure()
    test_target_reachability()
    test_future_mutation_does_not_change_acceptance()
    print("Candidate 2 causal engines smoke tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
