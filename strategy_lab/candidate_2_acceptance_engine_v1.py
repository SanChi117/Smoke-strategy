#!/usr/bin/env python3
"""SMOKE CORE Candidate 2 C2-P3 causal acceptance/persistence engine."""
from __future__ import annotations

from datetime import datetime
from statistics import mean
from typing import Sequence

from strategy_lab.market_data import Candle
from strategy_lab.candidate_2_hypothesis_contract_v1 import PersistenceEvidence, PersistenceState

ENGINE_ID = "SMOKE_CORE_CANDIDATE_2_ACCEPTANCE_ENGINE_V1"
MIN_CONFIRM_BARS = 3
MAX_CONFIRM_BARS = 8
FOLLOW_THROUGH_ATR = 0.35
MAX_PULLBACK_FRACTION = 0.55
MIN_DIRECTIONAL_CLOSE_FRACTION = 0.60


def _atr(rows: Sequence[Candle], length: int = 14) -> float:
    selected = rows[-max(2, length + 1):]
    trs = []
    for prev, cur in zip(selected[:-1], selected[1:]):
        trs.append(max(cur.high - cur.low, abs(cur.high - prev.close), abs(cur.low - prev.close)))
    return mean(trs) if trs else max(1e-12, rows[-1].high - rows[-1].low)


def evaluate_persistence(
    candles: Sequence[Candle],
    *,
    scenario_id: str,
    direction: str,
    trigger_time: datetime,
    evaluated_at: datetime,
    trigger_price: float,
    protected_price: float,
) -> PersistenceEvidence:
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if trigger_time > evaluated_at:
        raise ValueError("trigger_time cannot be after evaluated_at")
    causal = sorted((c for c in candles if trigger_time <= c.time <= evaluated_at), key=lambda c: c.time)
    history = sorted((c for c in candles if c.time <= evaluated_at), key=lambda c: c.time)
    if len(causal) < MIN_CONFIRM_BARS:
        state = PersistenceState.PENDING
        accepted = False
        immediate_refailure = False
        retained = True
        follow = False
        measure = 0.0
        invalidation_ids: tuple[str, ...] = ()
    else:
        causal = causal[:MAX_CONFIRM_BARS]
        atr = _atr(history)
        if direction == "LONG":
            retained = min(c.low for c in causal) > protected_price
            directional = sum(c.close > c.open for c in causal) / len(causal)
            excursion = max(c.high for c in causal) - trigger_price
            adverse = max(0.0, trigger_price - min(c.low for c in causal))
            immediate_refailure = causal[0].close < trigger_price and causal[0].low <= protected_price
        else:
            retained = max(c.high for c in causal) < protected_price
            directional = sum(c.close < c.open for c in causal) / len(causal)
            excursion = trigger_price - min(c.low for c in causal)
            adverse = max(0.0, max(c.high for c in causal) - trigger_price)
            immediate_refailure = causal[0].close > trigger_price and causal[0].high >= protected_price
        follow = excursion >= FOLLOW_THROUGH_ATR * atr
        pullback_ok = adverse <= MAX_PULLBACK_FRACTION * max(excursion, atr * 0.25)
        accepted = retained and follow and pullback_ok and directional >= MIN_DIRECTIONAL_CLOSE_FRACTION and not immediate_refailure
        measure = max(-1.0, min(1.0, (directional - 0.5) * 1.2 + (excursion / max(atr, 1e-12)) * 0.25 - (adverse / max(atr, 1e-12)) * 0.25))
        if immediate_refailure or not retained:
            state = PersistenceState.INVALIDATED
        elif accepted:
            state = PersistenceState.ACCEPTED
        else:
            state = PersistenceState.REJECTED
        reasons = []
        if immediate_refailure: reasons.append("immediate_refailure")
        if not retained: reasons.append("protected_structure_lost")
        if not follow: reasons.append("insufficient_follow_through")
        if not pullback_ok: reasons.append("excessive_pullback")
        if directional < MIN_DIRECTIONAL_CLOSE_FRACTION: reasons.append("weak_directional_closes")
        invalidation_ids = tuple(f"{ENGINE_ID}:{r}" for r in reasons)

    evidence_ids = (
        f"{ENGINE_ID}:trigger:{trigger_time.isoformat()}",
        f"{ENGINE_ID}:evaluated:{evaluated_at.isoformat()}",
        f"{ENGINE_ID}:direction:{direction}",
    )
    return PersistenceEvidence(
        scenario_id=scenario_id,
        evaluated_at=evaluated_at,
        accepted=accepted,
        persistence_state=state,
        evidence_ids=evidence_ids,
        invalidation_ids=invalidation_ids,
        causal_window_start=trigger_time,
        causal_window_end=min(evaluated_at, causal[-1].time if causal else evaluated_at),
        retained_structure=retained,
        follow_through_present=follow,
        immediate_refailure=immediate_refailure,
        acceptance_measure=round(measure, 10),
    )
