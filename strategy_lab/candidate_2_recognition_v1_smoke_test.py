#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from strategy_lab.candidate_2_hypothesis_contract_v1 import (
    HorizonClass, PersistenceEvidence, PersistenceState, RegimeEvidence, RegimeState, TargetReachability,
)
from strategy_lab.candidate_2_family_policy_v1 import evaluate_trend_pullback_policy
from strategy_lab.candidate_2_quality_model_v2 import QualityComponentsV2, score_quality
from strategy_lab.candidate_2_outcome_blind_recognition_v1 import assert_clean, from_policy, run_recognition


def build_row():
    t = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)
    regime = RegimeEvidence(t, RegimeState.TREND_PULLBACK_UP, 0.8, 0.7, 0.1, 0.6, 0.5, 0.3, 0.1, ("regime",), t-timedelta(hours=4), t)
    persistence = PersistenceEvidence("scenario", t, True, PersistenceState.ACCEPTED, ("persist",), (), t-timedelta(minutes=20), t, True, True, False, 0.8)
    target = TargetReachability("scenario", t, "target", 110.0, "opposing_liquidity", (), 2.0, HorizonClass.INTRADAY, True, (), ("target",), t-timedelta(hours=3), t)
    policy = evaluate_trend_pullback_policy(
        scenario_id="scenario", evaluated_at=t, direction="LONG", regime=regime,
        persistence=persistence, target=target, structure_valid=True, economics_pass=True, risk_pass=True,
    )
    q = score_quality(QualityComponentsV2(
        scenario_id="scenario", evaluated_at=t,
        regime_coherence=0.8, location_quality=0.7, interaction_quality=0.8,
        acceptance_persistence=0.9, structure_integrity=0.9, target_reachability=0.8,
        conflict_penalty=0.0,
        provenance={
            "regime_coherence": (regime.regime_id,), "location_quality": ("location",),
            "interaction_quality": ("interaction",), "acceptance_persistence": (persistence.persistence_id,),
            "structure_integrity": ("structure",), "target_reachability": (target.reachability_id,),
            "conflict_penalty": ("no_hard_conflict",),
        },
    ))
    return from_policy(symbol="BTCUSDT", fold=0, policy=policy, quality=q, economics_valid=True, risk_valid=True)


def main() -> int:
    row = build_row()
    report = run_recognition((row,))
    assert report.independent_entry_ready == 1
    assert report.by_symbol["BTCUSDT"] == 1
    assert report.by_direction["LONG"] == 1
    assert report.by_fold[0] == 1
    assert_clean(report)

    duplicate = run_recognition((row, row))
    assert duplicate.duplicate_rows == 1
    try:
        assert_clean(duplicate)
        raise AssertionError("duplicate recognition was not rejected")
    except AssertionError:
        pass

    assert run_recognition((row,)).fingerprints == run_recognition(tuple(reversed((row,)))).fingerprints
    print("Candidate 2 outcome-blind recognition smoke tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
