#!/usr/bin/env python3
"""Fixed preregistered outcome-blind P7 pilot.

The fixture contains only causal P6 inputs and evidence known at each evaluation
instant. It emits recognition diagnostics without market outcomes or PnL.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from strategy_lab.outcome_blind_recognition_v1 import (
    PilotStatus,
    RecognitionObservation,
    report_to_no_outcome_dict,
    run_pilot,
)
from strategy_lab.scenario_fusion_v1 import (
    Decision,
    Direction,
    EvidenceInput,
    EvidenceRelation,
    FusionInput,
    ScenarioFamily,
    fuse_scenario,
)

PILOT_ID = "SMOKE_CORE_P7_PILOT_FIXED_V1"
BASE = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AAVEUSDT")
FAMILIES = (
    ScenarioFamily.LIQUIDITY_RAID_REVERSAL,
    ScenarioFamily.TREND_PULLBACK_CONTINUATION,
    ScenarioFamily.RANGE_BOUNDARY_ROTATION,
)


def _nodes(family: ScenarioFamily) -> tuple[str, ...]:
    if family == ScenarioFamily.LIQUIDITY_RAID_REVERSAL:
        return ("location", "raid", "poi", "return_acceptance", "structure", "economics", "risk")
    if family == ScenarioFamily.TREND_PULLBACK_CONTINUATION:
        return ("trend", "poi", "htf_protection", "mitigation", "resumption", "economics", "risk")
    return ("range", "boundary_liquidity", "poi_rejection", "acceptance", "space", "economics", "risk")


def _evidence(case_id: int, family: ScenarioFamily, at: datetime) -> tuple[EvidenceInput, ...]:
    return tuple(
        EvidenceInput(
            evidence_id=f"ev:{case_id}:{node}",
            cluster_id=f"cluster:{case_id}:{node}",
            node=node,
            relation=EvidenceRelation.PRIMARY,
            strength_0_100=92.0,
            confirmed_at=at - timedelta(minutes=5),
        )
        for node in _nodes(family)
    )


def _observation(case_id: int, *, state: str) -> RecognitionObservation:
    symbol = SYMBOLS[case_id % len(SYMBOLS)]
    side = Direction.LONG if case_id % 2 == 0 else Direction.SHORT
    family = FAMILIES[case_id % len(FAMILIES)]
    at = BASE + timedelta(hours=case_id * 3)
    flags = {
        "armed": state in {"ARMED", "REACTION_DETECTED", "CONFIRMED", "ENTRY_READY"},
        "reaction_detected": state in {"REACTION_DETECTED", "CONFIRMED", "ENTRY_READY"},
        "structure_confirmed": state in {"CONFIRMED", "ENTRY_READY"},
        "economics_valid": state == "ENTRY_READY",
        "risk_valid": state == "ENTRY_READY",
        "economics_cancelled": state == "CANCELLED_BY_ECONOMICS",
        "risk_cancelled": state == "CANCELLED_BY_RISK",
        "expired": state == "EXPIRED",
        "invalidated": state == "INVALIDATED",
    }
    hard_blocks: tuple[str, ...] = ()
    if state == "CANCELLED_BY_ECONOMICS":
        hard_blocks = ("economics:net_rr_below_floor",)
    elif state == "CANCELLED_BY_RISK":
        hard_blocks = ("risk:portfolio_open_risk_limit",)
    elif state == "INVALIDATED":
        hard_blocks = ("causal:anchor_invalidated",)
    decision = fuse_scenario(
        FusionInput(
            symbol=symbol,
            side=side,
            family=family,
            evaluated_at=at,
            target_level_id=f"liq:{case_id}",
            poi_id=f"poi:{case_id}",
            anchor_id=f"anchor:{case_id}",
            structure_id=f"structure:{case_id}",
            protected_swing_id=f"swing:{case_id}",
            poi_lifecycle_id=f"poi-life:{case_id}",
            hard_blocks=hard_blocks,
            **flags,
        ),
        _evidence(case_id, family, at),
    )
    scenario = decision.scenario
    return RecognitionObservation(
        symbol=scenario.symbol,
        direction=scenario.side.value,
        fold=case_id % 10,
        timestamp=scenario.evaluated_at,
        family=scenario.family.value,
        decision=decision.decision.value,
        lifecycle=scenario.state.value,
        fingerprint=scenario.fingerprint,
        rearm_parent=None,
        poi_id=scenario.poi_id,
        liquidity_ids=(scenario.target_level_id,),
        interaction_ids=(f"interaction:{case_id}",),
        anchor_id=scenario.anchor_id,
        structure_id=scenario.structure_id,
        evidence_ids=scenario.evidence_ids,
        evidence_cluster_ids=scenario.evidence_cluster_ids,
        economics_valid=flags["economics_valid"],
        risk_valid=flags["risk_valid"],
        block_reasons=tuple(decision.reasons),
        hard_blocks=hard_blocks,
    )


def fixed_rows() -> tuple[RecognitionObservation, ...]:
    states = (
        "ENTRY_READY", "ENTRY_READY", "ENTRY_READY", "ENTRY_READY", "ENTRY_READY",
        "ARMED", "REACTION_DETECTED", "CONFIRMED",
        "CANCELLED_BY_ECONOMICS", "CANCELLED_BY_RISK", "EXPIRED", "INVALIDATED",
    )
    return tuple(_observation(index, state=state) for index, state in enumerate(states))


def main() -> int:
    rows = fixed_rows()
    first = run_pilot(rows)
    second = run_pilot(tuple(reversed(rows)))
    assert first == second, "pilot replay is not deterministic"
    assert first.status == PilotStatus.PASS, first
    assert first.duplicate_rows == 0
    assert first.invalid_lifecycle_rows == 0
    assert first.unexplained_block_rows == 0
    assert first.missing_provenance_rows == 0
    assert first.forbidden_key_rows == 0
    assert first.reproducible

    output = {
        "pilot_id": PILOT_ID,
        "fixture_start": rows[0].timestamp.isoformat(),
        "fixture_end": rows[-1].timestamp.isoformat(),
        "report": report_to_no_outcome_dict(first),
    }
    path = Path("research_outputs/p7_outcome_blind_pilot_v1.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(output, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
