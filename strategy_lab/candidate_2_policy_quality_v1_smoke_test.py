#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from strategy_lab.candidate_2_hypothesis_contract_v1 import (
    Candidate2Lifecycle,
    HorizonClass,
    PersistenceEvidence,
    PersistenceState,
    RegimeEvidence,
    RegimeState,
    TargetReachability,
)
from strategy_lab.candidate_2_family_policy_v1 import evaluate_raid_reversal_policy, evaluate_trend_pullback_policy
from strategy_lab.candidate_2_quality_model_v2 import QualityComponentsV2, score_quality


def fixtures():
    t = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    regime = RegimeEvidence(t, RegimeState.TREND_PULLBACK_UP, 0.7, 0.6, 0.1, 0.5, 0.4, 0.2, 0.1, ("regime_e",), t-timedelta(hours=4), t)
    persistence = PersistenceEvidence("s1", t, True, PersistenceState.ACCEPTED, ("persist_e",), (), t-timedelta(minutes=20), t, True, True, False, 0.7)
    target = TargetReachability("s1", t, "t1", 110.0, "causal opposing liquidity", (), 2.0, HorizonClass.INTRADAY, True, (), ("target_e",), t-timedelta(hours=3), t)
    return t, regime, persistence, target


def main() -> int:
    t, regime, persistence, target = fixtures()
    good = evaluate_trend_pullback_policy(
        scenario_id="s1", evaluated_at=t, direction="LONG", regime=regime,
        persistence=persistence, target=target, structure_valid=True,
        economics_pass=True, risk_pass=True,
    )
    assert good.lifecycle == Candidate2Lifecycle.ENTRY_READY

    bad_regime = RegimeEvidence(t, RegimeState.TREND_EXPANSION_DOWN, -0.7, -0.6, 0.1, -0.5, -0.4, -0.2, 0.1, ("regime_down",), t-timedelta(hours=4), t)
    rejected = evaluate_trend_pullback_policy(
        scenario_id="s2", evaluated_at=t, direction="LONG", regime=bad_regime,
        persistence=persistence, target=target, structure_valid=True,
        economics_pass=True, risk_pass=True,
    )
    assert rejected.lifecycle == Candidate2Lifecycle.CANCELLED_REGIME
    assert "opposite_trend_regime_invalidates_continuation" in rejected.rejection_reasons

    neutral_regime = RegimeEvidence(t, RegimeState.DISORDERED, 0.05, 0.1, 0.2, 0.02, 0.0, 0.0, 0.0, ("regime_neutral",), t-timedelta(hours=4), t)
    neutral_accepted = evaluate_trend_pullback_policy(
        scenario_id="s2b", evaluated_at=t, direction="LONG", regime=neutral_regime,
        persistence=persistence, target=target, structure_valid=True,
        economics_pass=True, risk_pass=True,
    )
    assert neutral_accepted.lifecycle == Candidate2Lifecycle.ENTRY_READY

    rejected_persistence = PersistenceEvidence(
        "s2c", t, False, PersistenceState.REJECTED, ("persist_rejected",),
        ("weak_directional_closes",), t-timedelta(minutes=20), t,
        True, False, False, -0.2,
    )
    neutral_rejected = evaluate_trend_pullback_policy(
        scenario_id="s2c", evaluated_at=t, direction="LONG", regime=neutral_regime,
        persistence=rejected_persistence, target=target, structure_valid=True,
        economics_pass=True, risk_pass=True,
    )
    assert neutral_rejected.lifecycle == Candidate2Lifecycle.CANCELLED_ACCEPTANCE
    assert "persistence_not_accepted" in neutral_rejected.rejection_reasons

    raid = evaluate_raid_reversal_policy(scenario_id="s3", evaluated_at=t, direction="SHORT", regime=bad_regime)
    assert raid.lifecycle != Candidate2Lifecycle.ENTRY_READY
    assert "raid_causal_state_machine_incomplete" in raid.rejection_reasons

    components = QualityComponentsV2(
        scenario_id="s1", evaluated_at=t,
        regime_coherence=0.8, location_quality=0.7, interaction_quality=0.75,
        acceptance_persistence=0.9, structure_integrity=0.85,
        target_reachability=0.8, conflict_penalty=0.1,
        provenance={
            "regime_coherence": ("regime_e",),
            "location_quality": ("location_e",),
            "interaction_quality": ("interaction_e",),
            "acceptance_persistence": ("persist_e",),
            "structure_integrity": ("structure_e",),
            "target_reachability": ("target_e",),
            "conflict_penalty": ("conflict_e",),
        },
    )
    score = score_quality(components)
    assert 0.0 <= score.score_0_100 <= 100.0
    assert score.score_0_100 < score.positive_score_0_100
    assert len(score.component_digest) == 64

    try:
        QualityComponentsV2(
            scenario_id="bad", evaluated_at=t,
            regime_coherence=0.8, location_quality=0.7, interaction_quality=0.75,
            acceptance_persistence=0.9, structure_integrity=0.85,
            target_reachability=0.8, conflict_penalty=0.1,
            provenance={
                "regime_coherence": ("future_pnl",),
                "location_quality": ("location_e",), "interaction_quality": ("interaction_e",),
                "acceptance_persistence": ("persist_e",), "structure_integrity": ("structure_e",),
                "target_reachability": ("target_e",), "conflict_penalty": ("conflict_e",),
            },
        )
        raise AssertionError("outcome-derived quality provenance was not rejected")
    except ValueError:
        pass

    print("Candidate 2 family policy + quality model smoke tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
