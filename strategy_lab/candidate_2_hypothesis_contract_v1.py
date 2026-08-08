#!/usr/bin/env python3
"""SMOKE CORE Candidate 2 causal hypothesis contracts.

C2-P1/P2 skeleton only. This module defines deterministic, outcome-blind typed
objects for regime, persistence/acceptance, target reachability and family
policy transport. It intentionally contains no profitability thresholds and no
outcome-derived tuning.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

CANDIDATE_2_ID = "SMOKE_CORE_1_0_CANDIDATE_2"
CONTRACT_ID = "SMOKE_CORE_CANDIDATE_2_HYPOTHESIS_CONTRACT_V1"

FORBIDDEN_OUTCOME_FRAGMENTS = (
    "pnl",
    "profit_factor",
    "future_return",
    "future_price",
    "trade_outcome",
    "tp_result",
    "sl_result",
    "exit_price",
    "exit_reason",
    "mfe",
    "mae",
    "drawdown",
    "holding_time_after_entry",
    "win_rate",
)


class RegimeState(str, Enum):
    TREND_EXPANSION_UP = "TREND_EXPANSION_UP"
    TREND_EXPANSION_DOWN = "TREND_EXPANSION_DOWN"
    TREND_PULLBACK_UP = "TREND_PULLBACK_UP"
    TREND_PULLBACK_DOWN = "TREND_PULLBACK_DOWN"
    BALANCED_RANGE = "BALANCED_RANGE"
    VOLATILITY_TRANSITION = "VOLATILITY_TRANSITION"
    DISORDERED = "DISORDERED"


class PersistenceState(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"


class HorizonClass(str, Enum):
    MICRO = "MICRO"
    INTRADAY = "INTRADAY"
    SWING = "SWING"
    UNRESOLVED = "UNRESOLVED"


class Candidate2Family(str, Enum):
    TREND_PULLBACK_CONTINUATION = "TREND_PULLBACK_CONTINUATION"
    LIQUIDITY_RAID_REVERSAL = "LIQUIDITY_RAID_REVERSAL"


class Candidate2Lifecycle(str, Enum):
    DISCOVERED = "DISCOVERED"
    CONTEXT_VALID = "CONTEXT_VALID"
    INTERACTION_ACTIVE = "INTERACTION_ACTIVE"
    STRUCTURE_CONFIRMED = "STRUCTURE_CONFIRMED"
    ACCEPTANCE_PENDING = "ACCEPTANCE_PENDING"
    ACCEPTANCE_CONFIRMED = "ACCEPTANCE_CONFIRMED"
    TARGET_VALIDATED = "TARGET_VALIDATED"
    ENTRY_READY = "ENTRY_READY"
    CANCELLED_REGIME = "CANCELLED_REGIME"
    CANCELLED_INTERACTION = "CANCELLED_INTERACTION"
    CANCELLED_STRUCTURE = "CANCELLED_STRUCTURE"
    CANCELLED_ACCEPTANCE = "CANCELLED_ACCEPTANCE"
    CANCELLED_TARGET = "CANCELLED_TARGET"
    CANCELLED_ECONOMICS = "CANCELLED_ECONOMICS"
    CANCELLED_RISK = "CANCELLED_RISK"
    EXPIRED = "EXPIRED"


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = "|".join(str(part) for part in parts)
    return f"{prefix}_{sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def _assert_causal_window(start: datetime, end: datetime, evaluated_at: datetime) -> None:
    if start > end:
        raise ValueError("causal window start must not exceed end")
    if end > evaluated_at:
        raise ValueError("causal window must not extend beyond evaluated_at")


def _assert_provenance(ids: Sequence[str], field: str) -> None:
    if not ids:
        raise ValueError(f"{field} must contain causal provenance")
    if any(not str(value).strip() for value in ids):
        raise ValueError(f"{field} contains empty provenance id")


@dataclass(frozen=True)
class RegimeEvidence:
    evaluated_at: datetime
    regime: RegimeState
    directional_structure_alignment: float
    structure_persistence: float
    realized_volatility_state: float
    directional_efficiency: float
    displacement_persistence: float
    liquidity_location_context: float
    compression_expansion_state: float
    evidence_ids: tuple[str, ...]
    causal_window_start: datetime
    causal_window_end: datetime

    def __post_init__(self) -> None:
        _assert_causal_window(self.causal_window_start, self.causal_window_end, self.evaluated_at)
        _assert_provenance(self.evidence_ids, "evidence_ids")
        for name in (
            "directional_structure_alignment",
            "structure_persistence",
            "realized_volatility_state",
            "directional_efficiency",
            "displacement_persistence",
            "liquidity_location_context",
            "compression_expansion_state",
        ):
            value = float(getattr(self, name))
            if not -1.0 <= value <= 1.0:
                raise ValueError(f"{name} must be normalized to [-1,1]")

    @property
    def regime_id(self) -> str:
        return _stable_id(
            "c2regime", self.evaluated_at.isoformat(), self.regime.value,
            *self.evidence_ids, self.causal_window_start.isoformat(), self.causal_window_end.isoformat(),
        )


@dataclass(frozen=True)
class PersistenceEvidence:
    scenario_id: str
    evaluated_at: datetime
    accepted: bool
    persistence_state: PersistenceState
    evidence_ids: tuple[str, ...]
    invalidation_ids: tuple[str, ...]
    causal_window_start: datetime
    causal_window_end: datetime
    retained_structure: bool
    follow_through_present: bool
    immediate_refailure: bool
    acceptance_measure: float

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id required")
        _assert_causal_window(self.causal_window_start, self.causal_window_end, self.evaluated_at)
        _assert_provenance(self.evidence_ids, "evidence_ids")
        if not -1.0 <= float(self.acceptance_measure) <= 1.0:
            raise ValueError("acceptance_measure must be normalized to [-1,1]")
        if self.accepted and self.persistence_state != PersistenceState.ACCEPTED:
            raise ValueError("accepted persistence must use ACCEPTED state")
        if self.immediate_refailure and self.accepted:
            raise ValueError("immediate refailure cannot be accepted")

    @property
    def persistence_id(self) -> str:
        return _stable_id(
            "c2persist", self.scenario_id, self.evaluated_at.isoformat(),
            self.persistence_state.value, *self.evidence_ids, *self.invalidation_ids,
        )


@dataclass(frozen=True)
class TargetReachability:
    scenario_id: str
    evaluated_at: datetime
    target_id: str
    target_price: float
    structural_reason: str
    path_obstacle_ids: tuple[str, ...]
    volatility_distance: float
    horizon_class: HorizonClass
    reachable: bool
    rejection_reasons: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    causal_window_start: datetime
    causal_window_end: datetime

    def __post_init__(self) -> None:
        if not self.scenario_id or not self.target_id or not self.structural_reason:
            raise ValueError("scenario_id, target_id and structural_reason are required")
        if self.target_price <= 0:
            raise ValueError("target_price must be positive")
        if self.volatility_distance < 0:
            raise ValueError("volatility_distance must be non-negative")
        _assert_causal_window(self.causal_window_start, self.causal_window_end, self.evaluated_at)
        _assert_provenance(self.evidence_ids, "evidence_ids")
        if self.reachable and self.rejection_reasons:
            raise ValueError("reachable target cannot have rejection reasons")
        if not self.reachable and not self.rejection_reasons:
            raise ValueError("unreachable target requires rejection reasons")

    @property
    def reachability_id(self) -> str:
        return _stable_id(
            "c2target", self.scenario_id, self.evaluated_at.isoformat(), self.target_id,
            self.horizon_class.value, self.reachable, *self.evidence_ids, *self.path_obstacle_ids,
        )


@dataclass(frozen=True)
class FamilyPolicyDecision:
    scenario_id: str
    evaluated_at: datetime
    family: Candidate2Family
    direction: str
    lifecycle: Candidate2Lifecycle
    regime_id: str
    persistence_id: str | None
    reachability_id: str | None
    evidence_ids: tuple[str, ...]
    rejection_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        if not self.scenario_id or not self.regime_id:
            raise ValueError("scenario_id and regime_id required")
        _assert_provenance(self.evidence_ids, "evidence_ids")
        if self.lifecycle == Candidate2Lifecycle.ENTRY_READY:
            if not self.persistence_id or not self.reachability_id:
                raise ValueError("ENTRY_READY requires persistence and reachability provenance")
            if self.rejection_reasons:
                raise ValueError("ENTRY_READY cannot have rejection reasons")

    @property
    def decision_id(self) -> str:
        return _stable_id(
            "c2policy", self.scenario_id, self.evaluated_at.isoformat(), self.family.value,
            self.direction, self.lifecycle.value, self.regime_id, self.persistence_id,
            self.reachability_id, *self.evidence_ids, *self.rejection_reasons,
        )


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


def serialize_outcome_blind(value: Any) -> dict[str, Any]:
    payload = _jsonable(value)
    if not isinstance(payload, dict):
        raise TypeError("top-level Candidate 2 transport must serialize to an object")
    text = json.dumps(payload, sort_keys=True, separators=(",", ":")).lower()
    for fragment in FORBIDDEN_OUTCOME_FRAGMENTS:
        if fragment in text:
            raise ValueError(f"forbidden outcome fragment in Candidate 2 transport: {fragment}")
    return payload


def deterministic_digest(value: Any) -> str:
    payload = serialize_outcome_blind(value)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256(raw).hexdigest()
