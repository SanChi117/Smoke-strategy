#!/usr/bin/env python3
"""SMOKE CORE Candidate 2 C2-P5 family-specific causal admission policy."""
from __future__ import annotations

from datetime import datetime

from strategy_lab.candidate_2_hypothesis_contract_v1 import (
    Candidate2Family,
    Candidate2Lifecycle,
    FamilyPolicyDecision,
    PersistenceEvidence,
    RegimeEvidence,
    RegimeState,
    TargetReachability,
)

POLICY_ID = "SMOKE_CORE_CANDIDATE_2_FAMILY_POLICY_V1"

TREND_LONG_REGIMES = frozenset({RegimeState.TREND_EXPANSION_UP, RegimeState.TREND_PULLBACK_UP})
TREND_SHORT_REGIMES = frozenset({RegimeState.TREND_EXPANSION_DOWN, RegimeState.TREND_PULLBACK_DOWN})
NEUTRAL_TRANSITION_REGIMES = frozenset({
    RegimeState.BALANCED_RANGE,
    RegimeState.VOLATILITY_TRANSITION,
    RegimeState.DISORDERED,
})


def evaluate_trend_pullback_policy(
    *,
    scenario_id: str,
    evaluated_at: datetime,
    direction: str,
    regime: RegimeEvidence,
    persistence: PersistenceEvidence | None,
    target: TargetReachability | None,
    structure_valid: bool,
    economics_pass: bool,
    risk_pass: bool,
    hard_conflicts: tuple[str, ...] = (),
) -> FamilyPolicyDecision:
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    if regime.evaluated_at > evaluated_at:
        raise ValueError("regime evidence cannot come from the future")
    if persistence is not None and persistence.evaluated_at > evaluated_at:
        raise ValueError("persistence evidence cannot come from the future")
    if target is not None and target.evaluated_at > evaluated_at:
        raise ValueError("target evidence cannot come from the future")

    allowed = TREND_LONG_REGIMES if direction == "LONG" else TREND_SHORT_REGIMES
    opposite = TREND_SHORT_REGIMES if direction == "LONG" else TREND_LONG_REGIMES
    reasons: list[str] = []
    lifecycle = Candidate2Lifecycle.ACCEPTANCE_PENDING

    # The P7 trend trigger is already created only when the frozen HTF context is
    # directionally aligned with the anchor. Candidate 2 therefore treats a later
    # neutral/transition 5m regime as unresolved rather than as proof that the HTF
    # continuation thesis is invalid. Entry is still impossible until the local
    # regime becomes directionally compatible. Only an explicit opposite trend
    # state is an immediate regime cancellation.
    if regime.regime in opposite:
        lifecycle = Candidate2Lifecycle.CANCELLED_REGIME
        reasons.append("opposite_trend_regime_invalidates_continuation")
    elif regime.regime in NEUTRAL_TRANSITION_REGIMES:
        lifecycle = Candidate2Lifecycle.ACCEPTANCE_PENDING
        reasons.append("local_regime_not_yet_directionally_committed")
    elif regime.regime not in allowed:
        lifecycle = Candidate2Lifecycle.CANCELLED_REGIME
        reasons.append("unsupported_regime_state")
    elif not structure_valid:
        lifecycle = Candidate2Lifecycle.CANCELLED_STRUCTURE
        reasons.append("protected_structure_invalid")
    elif persistence is None or not persistence.accepted:
        lifecycle = Candidate2Lifecycle.CANCELLED_ACCEPTANCE if persistence is not None else Candidate2Lifecycle.ACCEPTANCE_PENDING
        if persistence is not None:
            reasons.append("persistence_not_accepted")
    elif target is None or not target.reachable:
        lifecycle = Candidate2Lifecycle.CANCELLED_TARGET if target is not None else Candidate2Lifecycle.ACCEPTANCE_CONFIRMED
        if target is not None:
            reasons.append("target_not_reachable")
    elif not economics_pass:
        lifecycle = Candidate2Lifecycle.CANCELLED_ECONOMICS
        reasons.append("economics_failed")
    elif not risk_pass:
        lifecycle = Candidate2Lifecycle.CANCELLED_RISK
        reasons.append("risk_failed")
    elif hard_conflicts:
        lifecycle = Candidate2Lifecycle.CANCELLED_INTERACTION
        reasons.extend(f"hard_conflict:{value}" for value in hard_conflicts)
    else:
        lifecycle = Candidate2Lifecycle.ENTRY_READY

    evidence = [regime.regime_id, f"{POLICY_ID}:direction:{direction}"]
    if persistence is not None:
        evidence.append(persistence.persistence_id)
    if target is not None:
        evidence.append(target.reachability_id)
    return FamilyPolicyDecision(
        scenario_id=scenario_id,
        evaluated_at=evaluated_at,
        family=Candidate2Family.TREND_PULLBACK_CONTINUATION,
        direction=direction,
        lifecycle=lifecycle,
        regime_id=regime.regime_id,
        persistence_id=persistence.persistence_id if persistence is not None else None,
        reachability_id=target.reachability_id if target is not None else None,
        evidence_ids=tuple(evidence),
        rejection_reasons=tuple(reasons),
    )


def evaluate_raid_reversal_policy(
    *,
    scenario_id: str,
    evaluated_at: datetime,
    direction: str,
    regime: RegimeEvidence,
) -> FamilyPolicyDecision:
    """Explicitly keep Raid as research-only until its causal state machine exists.

    This is not a PnL blacklist. The research specification requires failed
    continuation + value re-acceptance + opposite displacement + persistence;
    those typed evidences do not yet exist, so ENTRY_READY is impossible.
    """
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    return FamilyPolicyDecision(
        scenario_id=scenario_id,
        evaluated_at=evaluated_at,
        family=Candidate2Family.LIQUIDITY_RAID_REVERSAL,
        direction=direction,
        lifecycle=Candidate2Lifecycle.CANCELLED_ACCEPTANCE,
        regime_id=regime.regime_id,
        persistence_id=None,
        reachability_id=None,
        evidence_ids=(regime.regime_id, f"{POLICY_ID}:raid_research_only"),
        rejection_reasons=("raid_causal_state_machine_incomplete",),
    )
