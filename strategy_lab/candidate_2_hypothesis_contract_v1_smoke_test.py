#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from strategy_lab.candidate_2_hypothesis_contract_v1 import (
    Candidate2Family,
    Candidate2Lifecycle,
    FamilyPolicyDecision,
    HorizonClass,
    PersistenceEvidence,
    PersistenceState,
    RegimeEvidence,
    RegimeState,
    TargetReachability,
    deterministic_digest,
    serialize_outcome_blind,
)


def main() -> None:
    t = datetime(2024, 7, 1, 12, 0, tzinfo=timezone.utc)
    start = t - timedelta(hours=4)

    regime = RegimeEvidence(
        evaluated_at=t,
        regime=RegimeState.TREND_PULLBACK_UP,
        directional_structure_alignment=0.7,
        structure_persistence=0.6,
        realized_volatility_state=0.2,
        directional_efficiency=0.5,
        displacement_persistence=0.4,
        liquidity_location_context=0.3,
        compression_expansion_state=0.1,
        evidence_ids=("structure_a", "vol_a", "liquidity_a"),
        causal_window_start=start,
        causal_window_end=t,
    )

    persistence = PersistenceEvidence(
        scenario_id="scenario_1",
        evaluated_at=t,
        accepted=True,
        persistence_state=PersistenceState.ACCEPTED,
        evidence_ids=("close_hold_1", "follow_through_1"),
        invalidation_ids=(),
        causal_window_start=t - timedelta(minutes=30),
        causal_window_end=t,
        retained_structure=True,
        follow_through_present=True,
        immediate_refailure=False,
        acceptance_measure=0.5,
    )

    target = TargetReachability(
        scenario_id="scenario_1",
        evaluated_at=t,
        target_id="target_1",
        target_price=110.0,
        structural_reason="next causal opposing liquidity structure",
        path_obstacle_ids=(),
        volatility_distance=1.2,
        horizon_class=HorizonClass.INTRADAY,
        reachable=True,
        rejection_reasons=(),
        evidence_ids=("target_level_1", "volatility_1"),
        causal_window_start=start,
        causal_window_end=t,
    )

    decision = FamilyPolicyDecision(
        scenario_id="scenario_1",
        evaluated_at=t,
        family=Candidate2Family.TREND_PULLBACK_CONTINUATION,
        direction="LONG",
        lifecycle=Candidate2Lifecycle.ENTRY_READY,
        regime_id=regime.regime_id,
        persistence_id=persistence.persistence_id,
        reachability_id=target.reachability_id,
        evidence_ids=(regime.regime_id, persistence.persistence_id, target.reachability_id),
        rejection_reasons=(),
    )

    for value in (regime, persistence, target, decision):
        payload = serialize_outcome_blind(value)
        assert isinstance(payload, dict)
        assert len(deterministic_digest(value)) == 64
        assert deterministic_digest(value) == deterministic_digest(value)

    # Future visibility must be rejected.
    try:
        RegimeEvidence(
            evaluated_at=t,
            regime=RegimeState.DISORDERED,
            directional_structure_alignment=0.0,
            structure_persistence=0.0,
            realized_volatility_state=0.0,
            directional_efficiency=0.0,
            displacement_persistence=0.0,
            liquidity_location_context=0.0,
            compression_expansion_state=0.0,
            evidence_ids=("x",),
            causal_window_start=t,
            causal_window_end=t + timedelta(minutes=5),
        )
        raise AssertionError("future causal window was not rejected")
    except ValueError:
        pass

    # ENTRY_READY without persistence/target provenance must be rejected.
    try:
        FamilyPolicyDecision(
            scenario_id="scenario_bad",
            evaluated_at=t,
            family=Candidate2Family.LIQUIDITY_RAID_REVERSAL,
            direction="SHORT",
            lifecycle=Candidate2Lifecycle.ENTRY_READY,
            regime_id=regime.regime_id,
            persistence_id=None,
            reachability_id=None,
            evidence_ids=(regime.regime_id,),
            rejection_reasons=(),
        )
        raise AssertionError("ENTRY_READY without causal gates was not rejected")
    except ValueError:
        pass

    # Accepted persistence cannot simultaneously carry immediate re-failure.
    try:
        PersistenceEvidence(
            scenario_id="scenario_bad",
            evaluated_at=t,
            accepted=True,
            persistence_state=PersistenceState.ACCEPTED,
            evidence_ids=("e",),
            invalidation_ids=("refailure",),
            causal_window_start=t - timedelta(minutes=5),
            causal_window_end=t,
            retained_structure=False,
            follow_through_present=False,
            immediate_refailure=True,
            acceptance_measure=-0.5,
        )
        raise AssertionError("contradictory persistence was not rejected")
    except ValueError:
        pass

    print("Candidate 2 hypothesis contract smoke tests: PASS")


if __name__ == "__main__":
    main()
