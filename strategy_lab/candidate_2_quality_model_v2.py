#!/usr/bin/env python3
"""SMOKE CORE Candidate 2 C2-P6 causal Quality Model V2.

Weights are fixed research constants defined before Candidate 2 outcome evaluation.
No outcome-derived fields or weights are accepted.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Mapping

MODEL_ID = "SMOKE_CORE_CANDIDATE_2_QUALITY_MODEL_V2"
WEIGHTS = {
    "regime_coherence": 0.20,
    "location_quality": 0.10,
    "interaction_quality": 0.15,
    "acceptance_persistence": 0.20,
    "structure_integrity": 0.15,
    "target_reachability": 0.20,
}
CONFLICT_PENALTY_WEIGHT = 0.15
FORBIDDEN = ("pnl", "profit", "outcome", "mfe", "mae", "drawdown", "future", "win_rate", "exit_")


@dataclass(frozen=True)
class QualityComponentsV2:
    scenario_id: str
    evaluated_at: datetime
    regime_coherence: float
    location_quality: float
    interaction_quality: float
    acceptance_persistence: float
    structure_integrity: float
    target_reachability: float
    conflict_penalty: float
    provenance: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("scenario_id required")
        for name in (*WEIGHTS.keys(), "conflict_penalty"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be normalized to [0,1]")
        required = set(WEIGHTS) | {"conflict_penalty"}
        if set(self.provenance) != required:
            raise ValueError("quality provenance must exactly cover every component")
        for key, ids in self.provenance.items():
            if not ids or any(not str(value).strip() for value in ids):
                raise ValueError(f"missing provenance for {key}")
        text = json.dumps({k: list(v) for k, v in self.provenance.items()}, sort_keys=True).lower()
        if any(fragment in text for fragment in FORBIDDEN):
            raise ValueError("outcome-derived provenance forbidden in Quality Model V2")


@dataclass(frozen=True)
class QualityScoreV2:
    scenario_id: str
    evaluated_at: datetime
    score_0_100: float
    positive_score_0_100: float
    conflict_penalty_0_100: float
    component_digest: str


def score_quality(components: QualityComponentsV2) -> QualityScoreV2:
    positive = sum(float(getattr(components, key)) * weight for key, weight in WEIGHTS.items()) * 100.0
    penalty = components.conflict_penalty * CONFLICT_PENALTY_WEIGHT * 100.0
    score = max(0.0, min(100.0, positive - penalty))
    payload = asdict(components)
    payload["evaluated_at"] = components.evaluated_at.isoformat()
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=list).encode("utf-8")
    digest = sha256(raw).hexdigest()
    return QualityScoreV2(
        scenario_id=components.scenario_id,
        evaluated_at=components.evaluated_at,
        score_0_100=round(score, 10),
        positive_score_0_100=round(positive, 10),
        conflict_penalty_0_100=round(penalty, 10),
        component_digest=digest,
    )
