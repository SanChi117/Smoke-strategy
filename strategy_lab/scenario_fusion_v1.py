#!/usr/bin/env python3
"""SMOKE CORE 1.0 P6: causal scenario fusion and family-specific scoring."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Any, Iterable, Mapping, Sequence


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class ScenarioFamily(str, Enum):
    LIQUIDITY_RAID_REVERSAL = "LIQUIDITY_RAID_REVERSAL"
    TREND_PULLBACK_CONTINUATION = "TREND_PULLBACK_CONTINUATION"
    RANGE_BOUNDARY_ROTATION = "RANGE_BOUNDARY_ROTATION"


class ScenarioState(str, Enum):
    DISCOVERED = "DISCOVERED"
    ARMED = "ARMED"
    REACTION_DETECTED = "REACTION_DETECTED"
    CONFIRMED = "CONFIRMED"
    ENTRY_READY = "ENTRY_READY"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"
    CANCELLED_BY_ECONOMICS = "CANCELLED_BY_ECONOMICS"
    CANCELLED_BY_RISK = "CANCELLED_BY_RISK"


class Decision(str, Enum):
    NO_SETUP = "NO_SETUP"
    WATCH = "WATCH"
    VALID_SETUP = "VALID_SETUP"
    HIGH_CONFIDENCE_SETUP = "HIGH_CONFIDENCE_SETUP"


class EvidenceRelation(str, Enum):
    PRIMARY = "PRIMARY"
    DERIVED = "DERIVED"
    CORROBORATING = "CORROBORATING"
    CONFLICTING = "CONFLICTING"


FAMILY_NODE_WEIGHTS: Mapping[ScenarioFamily, Mapping[str, float]] = {
    ScenarioFamily.LIQUIDITY_RAID_REVERSAL: {
        "location": 15.0, "raid": 25.0, "poi": 15.0,
        "return_acceptance": 20.0, "structure": 10.0,
        "economics": 10.0, "risk": 5.0,
    },
    ScenarioFamily.TREND_PULLBACK_CONTINUATION: {
        "trend": 20.0, "poi": 25.0, "htf_protection": 10.0,
        "mitigation": 15.0, "resumption": 15.0,
        "economics": 10.0, "risk": 5.0,
    },
    ScenarioFamily.RANGE_BOUNDARY_ROTATION: {
        "range": 20.0, "boundary_liquidity": 20.0,
        "poi_rejection": 15.0, "acceptance": 15.0,
        "space": 20.0, "economics": 5.0, "risk": 5.0,
    },
}

FORBIDDEN_KEY_FRAGMENTS = (
    "pnl", "profit_factor", "future_return", "trade_outcome", "mfe", "mae",
    "exit_price", "exit_reason", "drawdown", "net_return",
)


@dataclass(frozen=True)
class EvidenceInput:
    evidence_id: str
    cluster_id: str
    node: str
    relation: EvidenceRelation
    strength_0_100: float
    confirmed_at: datetime


@dataclass(frozen=True)
class FusionInput:
    symbol: str
    side: Direction
    family: ScenarioFamily
    evaluated_at: datetime
    target_level_id: str
    poi_id: str
    anchor_id: str | None
    structure_id: str | None
    protected_swing_id: str | None
    poi_lifecycle_id: str
    discovered: bool = True
    armed: bool = False
    reaction_detected: bool = False
    structure_confirmed: bool = False
    economics_valid: bool = False
    risk_valid: bool = False
    economics_cancelled: bool = False
    risk_cancelled: bool = False
    expired: bool = False
    invalidated: bool = False
    consumed: bool = False
    hard_blocks: tuple[str, ...] = ()
    critical_conflicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class NodeScore:
    node: str
    maximum: float
    awarded: float
    cluster_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class ScenarioCandidate:
    scenario_id: str
    fingerprint: str
    family: ScenarioFamily
    symbol: str
    side: Direction
    state: ScenarioState
    evaluated_at: datetime
    target_level_id: str
    poi_id: str
    anchor_id: str | None
    structure_id: str | None
    protected_swing_id: str | None
    poi_lifecycle_id: str
    node_scores: tuple[NodeScore, ...]
    total_score_0_100: float
    evidence_cluster_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    hard_blocks: tuple[str, ...]
    critical_conflicts: tuple[str, ...]


@dataclass(frozen=True)
class SetupDecision:
    decision: Decision
    scenario: ScenarioCandidate
    reasons: tuple[str, ...]


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}_{sha256(raw.encode()).hexdigest()[:20]}"


def build_fingerprint(data: FusionInput) -> str:
    return _stable_id(
        "fp", data.symbol.upper(), data.family.value, data.side.value,
        data.target_level_id, data.poi_id, data.anchor_id or "none",
        data.structure_id or "none", data.protected_swing_id or "none",
        data.poi_lifecycle_id,
    )


def _lifecycle(data: FusionInput) -> ScenarioState:
    if data.consumed:
        return ScenarioState.CONSUMED
    if data.invalidated:
        return ScenarioState.INVALIDATED
    if data.expired:
        return ScenarioState.EXPIRED
    if data.economics_cancelled:
        return ScenarioState.CANCELLED_BY_ECONOMICS
    if data.risk_cancelled:
        return ScenarioState.CANCELLED_BY_RISK
    if data.structure_confirmed and data.economics_valid and data.risk_valid:
        return ScenarioState.ENTRY_READY
    if data.structure_confirmed:
        return ScenarioState.CONFIRMED
    if data.reaction_detected:
        return ScenarioState.REACTION_DETECTED
    if data.armed:
        return ScenarioState.ARMED
    return ScenarioState.DISCOVERED


def _score_nodes(family: ScenarioFamily, evidence: Sequence[EvidenceInput], evaluated_at: datetime) -> tuple[NodeScore, ...]:
    weights = FAMILY_NODE_WEIGHTS[family]
    used_clusters: set[str] = set()
    cluster_total: dict[str, float] = {}
    output: list[NodeScore] = []
    for node, maximum in weights.items():
        rows = [item for item in evidence if item.node == node and item.confirmed_at <= evaluated_at]
        grouped: dict[str, list[EvidenceInput]] = {}
        for item in rows:
            grouped.setdefault(item.cluster_id, []).append(item)
        awarded = 0.0
        node_clusters: list[str] = []
        node_evidence: list[str] = []
        for cluster_id in sorted(grouped):
            if cluster_id in used_clusters:
                continue
            items = grouped[cluster_id]
            primary = max((x.strength_0_100 for x in items if x.relation == EvidenceRelation.PRIMARY), default=0.0)
            secondary = sum(x.strength_0_100 for x in items if x.relation == EvidenceRelation.CORROBORATING)
            conflicting = sum(x.strength_0_100 for x in items if x.relation == EvidenceRelation.CONFLICTING)
            raw_pct = max(0.0, primary + 0.35 * secondary - 0.35 * conflicting)
            contribution = maximum * min(100.0, raw_pct) / 100.0
            remaining_cluster_cap = max(0.0, 30.0 - cluster_total.get(cluster_id, 0.0))
            contribution = min(contribution, remaining_cluster_cap, maximum - awarded)
            if contribution <= 0:
                continue
            awarded += contribution
            cluster_total[cluster_id] = cluster_total.get(cluster_id, 0.0) + contribution
            used_clusters.add(cluster_id)
            node_clusters.append(cluster_id)
            node_evidence.extend(x.evidence_id for x in items)
        output.append(NodeScore(node, maximum, round(awarded, 4), tuple(node_clusters), tuple(sorted(set(node_evidence)))))
    return tuple(output)


def fuse_scenario(data: FusionInput, evidence: Iterable[EvidenceInput]) -> SetupDecision:
    rows = tuple(evidence)
    fingerprint = build_fingerprint(data)
    node_scores = _score_nodes(data.family, rows, data.evaluated_at)
    total = round(min(100.0, sum(item.awarded for item in node_scores)), 4)
    state = _lifecycle(data)
    scenario = ScenarioCandidate(
        scenario_id=_stable_id("scenario", fingerprint, data.evaluated_at.isoformat()),
        fingerprint=fingerprint, family=data.family, symbol=data.symbol.upper(), side=data.side,
        state=state, evaluated_at=data.evaluated_at, target_level_id=data.target_level_id,
        poi_id=data.poi_id, anchor_id=data.anchor_id, structure_id=data.structure_id,
        protected_swing_id=data.protected_swing_id, poi_lifecycle_id=data.poi_lifecycle_id,
        node_scores=node_scores, total_score_0_100=total,
        evidence_cluster_ids=tuple(sorted({c for n in node_scores for c in n.cluster_ids})),
        evidence_ids=tuple(sorted({e for n in node_scores for e in n.evidence_ids})),
        hard_blocks=tuple(data.hard_blocks), critical_conflicts=tuple(data.critical_conflicts),
    )
    reasons: list[str] = [f"state={state.value}", f"score={total:.4f}"]
    terminal_no_setup = state in {ScenarioState.INVALIDATED, ScenarioState.EXPIRED, ScenarioState.CANCELLED_BY_ECONOMICS, ScenarioState.CANCELLED_BY_RISK}
    if data.hard_blocks or terminal_no_setup or total < 60.0:
        decision = Decision.NO_SETUP
    elif state != ScenarioState.ENTRY_READY or total < 70.0:
        decision = Decision.WATCH
    elif total >= 80.0 and not data.critical_conflicts:
        decision = Decision.HIGH_CONFIDENCE_SETUP
    else:
        decision = Decision.VALID_SETUP
    if data.hard_blocks:
        reasons.extend(f"hard_block:{x}" for x in data.hard_blocks)
    if data.critical_conflicts:
        reasons.extend(f"critical_conflict:{x}" for x in data.critical_conflicts)
    return SetupDecision(decision, scenario, tuple(reasons))


def can_rearm(previous: ScenarioCandidate, current: FusionInput) -> bool:
    if previous.fingerprint != build_fingerprint(current):
        return True
    return False


def scenario_to_no_pnl_dict(decision: SetupDecision) -> dict[str, Any]:
    payload = asdict(decision)
    def normalize(value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {k: normalize(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        return value
    normalized = normalize(payload)
    stack = [normalized]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                lowered = key.lower()
                if any(fragment in lowered for fragment in FORBIDDEN_KEY_FRAGMENTS):
                    raise ValueError(f"forbidden outcome field: {key}")
                stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
    return normalized
