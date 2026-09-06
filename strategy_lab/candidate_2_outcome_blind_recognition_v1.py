#!/usr/bin/env python3
"""SMOKE CORE Candidate 2 C2-P7 outcome-blind recognition transport.

This layer records only causal recognition state. It does not read outcomes,
future candles, PnL, MAE/MFE, drawdown, or exit information.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any, Iterable, Mapping, Sequence

from strategy_lab.candidate_2_hypothesis_contract_v1 import Candidate2Lifecycle, FamilyPolicyDecision
from strategy_lab.candidate_2_quality_model_v2 import QualityScoreV2

RECOGNITION_ID = "SMOKE_CORE_CANDIDATE_2_OUTCOME_BLIND_RECOGNITION_V1"
ALLOWED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AAVEUSDT")
ALLOWED_DIRECTIONS = ("LONG", "SHORT")
COUNTED_STATE = Candidate2Lifecycle.ENTRY_READY.value
FORBIDDEN = (
    "pnl", "profit", "future", "outcome", "mfe", "mae", "drawdown", "equity",
    "exit_price", "exit_reason", "target_hit", "stop_hit", "win_rate", "holding_time_after_entry",
)


@dataclass(frozen=True)
class Candidate2RecognitionObservation:
    symbol: str
    direction: str
    fold: int
    timestamp: datetime
    family: str
    lifecycle: str
    scenario_id: str
    fingerprint: str
    rearm_parent: str | None
    regime_id: str
    persistence_id: str | None
    reachability_id: str | None
    quality_component_digest: str
    quality_score_0_100: float
    economics_valid: bool
    risk_valid: bool
    evidence_ids: tuple[str, ...]
    block_reasons: tuple[str, ...]


@dataclass(frozen=True)
class Candidate2RecognitionReport:
    total_rows: int
    independent_entry_ready: int
    duplicate_rows: int
    forbidden_rows: int
    missing_provenance_rows: int
    invalid_lifecycle_rows: int
    reproducible: bool
    by_symbol: Mapping[str, int]
    by_direction: Mapping[str, int]
    by_fold: Mapping[int, int]
    fingerprints: tuple[str, ...]


def stable_fingerprint(
    *, symbol: str, direction: str, family: str, scenario_id: str,
    regime_id: str, persistence_id: str, reachability_id: str,
) -> str:
    raw = "|".join((symbol, direction, family, scenario_id, regime_id, persistence_id, reachability_id))
    return f"c2fp_{sha256(raw.encode('utf-8')).hexdigest()[:28]}"


def from_policy(
    *,
    symbol: str,
    fold: int,
    policy: FamilyPolicyDecision,
    quality: QualityScoreV2,
    economics_valid: bool,
    risk_valid: bool,
    rearm_parent: str | None = None,
) -> Candidate2RecognitionObservation:
    if policy.scenario_id != quality.scenario_id:
        raise ValueError("policy/quality scenario mismatch")
    persistence_id = policy.persistence_id or ""
    reachability_id = policy.reachability_id or ""
    fingerprint = stable_fingerprint(
        symbol=symbol, direction=policy.direction, family=policy.family.value,
        scenario_id=policy.scenario_id, regime_id=policy.regime_id,
        persistence_id=persistence_id, reachability_id=reachability_id,
    )
    evidence = tuple(dict.fromkeys((*policy.evidence_ids, quality.component_digest)))
    return Candidate2RecognitionObservation(
        symbol=symbol.upper(), direction=policy.direction, fold=int(fold),
        timestamp=policy.evaluated_at, family=policy.family.value,
        lifecycle=policy.lifecycle.value, scenario_id=policy.scenario_id,
        fingerprint=fingerprint, rearm_parent=rearm_parent,
        regime_id=policy.regime_id, persistence_id=policy.persistence_id,
        reachability_id=policy.reachability_id,
        quality_component_digest=quality.component_digest,
        quality_score_0_100=quality.score_0_100,
        economics_valid=bool(economics_valid), risk_valid=bool(risk_valid),
        evidence_ids=evidence, block_reasons=policy.rejection_reasons,
    )


def _contains_forbidden(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in FORBIDDEN):
                return True
            if _contains_forbidden(nested):
                return True
    elif isinstance(value, (tuple, list)):
        return any(_contains_forbidden(v) for v in value)
    return False


def _has_provenance(row: Candidate2RecognitionObservation) -> bool:
    if not row.fingerprint or not row.scenario_id or not row.regime_id or not row.quality_component_digest or not row.evidence_ids:
        return False
    if row.lifecycle == COUNTED_STATE and (not row.persistence_id or not row.reachability_id):
        return False
    return True


def _valid_lifecycle(row: Candidate2RecognitionObservation) -> bool:
    if row.lifecycle == COUNTED_STATE:
        return row.economics_valid and row.risk_valid and bool(row.persistence_id) and bool(row.reachability_id) and not row.block_reasons
    return True


def is_counted(row: Candidate2RecognitionObservation) -> bool:
    return (
        row.symbol in ALLOWED_SYMBOLS and row.direction in ALLOWED_DIRECTIONS and 0 <= row.fold < 10
        and row.lifecycle == COUNTED_STATE and row.economics_valid and row.risk_valid
        and not row.block_reasons and _has_provenance(row)
    )


def dedupe_global(rows: Iterable[Candidate2RecognitionObservation]) -> tuple[tuple[Candidate2RecognitionObservation, ...], int]:
    selected: dict[str, Candidate2RecognitionObservation] = {}
    duplicates = 0
    for row in sorted(rows, key=lambda r: (r.timestamp, r.fold, r.symbol, r.direction, r.fingerprint)):
        if row.fingerprint not in selected:
            selected[row.fingerprint] = row
            continue
        previous = selected[row.fingerprint]
        if row.rearm_parent == previous.fingerprint and row.timestamp > previous.timestamp:
            selected[f"{row.fingerprint}:{row.timestamp.isoformat()}"] = row
        else:
            duplicates += 1
    return tuple(sorted(selected.values(), key=lambda r: (r.timestamp, r.symbol, r.direction, r.fingerprint))), duplicates


def _digest(rows: Sequence[Candidate2RecognitionObservation]) -> str:
    canonical = []
    for row in sorted(rows, key=lambda r: (r.timestamp, r.symbol, r.direction, r.fingerprint, r.fold)):
        payload = asdict(row); payload["timestamp"] = row.timestamp.isoformat()
        canonical.append(repr(sorted(payload.items())))
    return sha256("\n".join(canonical).encode("utf-8")).hexdigest()


def run_recognition(rows: Iterable[Candidate2RecognitionObservation]) -> Candidate2RecognitionReport:
    source = tuple(rows)
    deduped, duplicates = dedupe_global(source)
    counted = tuple(row for row in deduped if is_counted(row))
    forbidden = sum(_contains_forbidden(asdict(row)) for row in source)
    missing = sum(not _has_provenance(row) for row in source)
    invalid = sum(not _valid_lifecycle(row) for row in source)
    reproducible = _digest(deduped) == _digest(tuple(reversed(deduped)))
    return Candidate2RecognitionReport(
        total_rows=len(source), independent_entry_ready=len(counted), duplicate_rows=duplicates,
        forbidden_rows=forbidden, missing_provenance_rows=missing,
        invalid_lifecycle_rows=invalid, reproducible=reproducible,
        by_symbol={s: sum(r.symbol == s for r in counted) for s in ALLOWED_SYMBOLS},
        by_direction={d: sum(r.direction == d for r in counted) for d in ALLOWED_DIRECTIONS},
        by_fold={f: sum(r.fold == f for r in counted) for f in range(10)},
        fingerprints=tuple(sorted(r.fingerprint for r in counted)),
    )


def assert_clean(report: Candidate2RecognitionReport) -> None:
    if report.forbidden_rows:
        raise AssertionError(f"forbidden outcome rows: {report.forbidden_rows}")
    if report.missing_provenance_rows:
        raise AssertionError(f"missing provenance rows: {report.missing_provenance_rows}")
    if report.invalid_lifecycle_rows:
        raise AssertionError(f"invalid lifecycle rows: {report.invalid_lifecycle_rows}")
    if report.duplicate_rows:
        raise AssertionError(f"duplicate rows: {report.duplicate_rows}")
    if not report.reproducible:
        raise AssertionError("recognition transport is non-deterministic")
