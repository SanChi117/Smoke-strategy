#!/usr/bin/env python3
"""P4 family-specific execution policy adapter for anchored local structure."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Any, Mapping

from strategy_lab.execution_structure_v1 import ExecutionMode, ExecutionState, LocalStructureV1


class ScenarioFamily(str, Enum):
    RAID_REVERSAL = "RAID_REVERSAL"
    TREND_CONTINUATION = "TREND_CONTINUATION"
    RANGE_ROTATION = "RANGE_ROTATION"


@dataclass(frozen=True)
class FamilyEntryPolicy:
    family: ScenarioFamily
    allowed_modes: tuple[ExecutionMode, ...]
    minimum_confidence: float
    expiry_5m_bars: int


FAMILY_ENTRY_POLICIES: Mapping[ScenarioFamily, FamilyEntryPolicy] = {
    ScenarioFamily.RAID_REVERSAL: FamilyEntryPolicy(
        ScenarioFamily.RAID_REVERSAL,
        (ExecutionMode.A_TEXTBOOK_BREAK, ExecutionMode.C_DISPLACEMENT_FAILED_RETEST),
        62.0,
        18,
    ),
    ScenarioFamily.TREND_CONTINUATION: FamilyEntryPolicy(
        ScenarioFamily.TREND_CONTINUATION,
        (
            ExecutionMode.A_TEXTBOOK_BREAK,
            ExecutionMode.B_ACCEPTANCE_RETEST,
            ExecutionMode.C_DISPLACEMENT_FAILED_RETEST,
        ),
        58.0,
        24,
    ),
    ScenarioFamily.RANGE_ROTATION: FamilyEntryPolicy(
        ScenarioFamily.RANGE_ROTATION,
        (ExecutionMode.B_ACCEPTANCE_RETEST, ExecutionMode.C_DISPLACEMENT_FAILED_RETEST),
        64.0,
        16,
    ),
}


@dataclass(frozen=True)
class FamilyPolicyDecisionV1:
    family: ScenarioFamily
    structure_id: str
    allowed: bool
    reason: str
    confidence_0_100: float
    dependencies: tuple[str, ...]
    conflicts: tuple[str, ...]


FORBIDDEN_KEY_FRAGMENTS = (
    "pnl", "future_return", "trade_outcome", "tp_result", "sl_result",
    "mfe", "mae", "profit_factor", "net_return", "drawdown", "exit_price",
)


def apply_family_policy(structure: LocalStructureV1, family: ScenarioFamily) -> FamilyPolicyDecisionV1:
    policy = FAMILY_ENTRY_POLICIES[family]
    conflicts = list(structure.conflicts)
    if structure.state != ExecutionState.CONFIRMED:
        return FamilyPolicyDecisionV1(
            family, structure.structure_id, False, "structure_not_confirmed",
            structure.confidence_0_100, structure.dependencies, tuple(conflicts),
        )
    if structure.confirmation_mode not in policy.allowed_modes:
        conflicts.append("confirmation_mode_not_allowed_for_family")
        return FamilyPolicyDecisionV1(
            family, structure.structure_id, False, "mode_not_allowed",
            structure.confidence_0_100, structure.dependencies, tuple(conflicts),
        )
    if structure.confidence_0_100 < policy.minimum_confidence:
        conflicts.append("below_family_minimum_confidence")
        return FamilyPolicyDecisionV1(
            family, structure.structure_id, False, "confidence_below_family_minimum",
            structure.confidence_0_100, structure.dependencies, tuple(conflicts),
        )
    return FamilyPolicyDecisionV1(
        family, structure.structure_id, True, "family_policy_pass",
        structure.confidence_0_100, structure.dependencies, tuple(conflicts),
    )


def family_policy_to_no_pnl_dict(decision: FamilyPolicyDecisionV1) -> dict[str, Any]:
    payload = asdict(decision)
    raw = str(payload).lower()
    if any(fragment in raw for fragment in FORBIDDEN_KEY_FRAGMENTS):
        raise ValueError("forbidden outcome field in P4 family policy export")
    return payload
