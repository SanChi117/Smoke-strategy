#!/usr/bin/env python3
"""SMOKE CORE 1.0 P7: outcome-blind pilot and recognition accounting.

This module consumes already-causal P6 scenario decisions and produces only
recognition diagnostics. It never reads market outcomes or future bars.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Any, Iterable, Mapping, Sequence

FORBIDDEN_KEY_FRAGMENTS = (
    "pnl", "profit_factor", "future_return", "trade_outcome", "mfe", "mae",
    "exit_price", "exit_reason", "drawdown", "net_return", "equity",
    "target_hit", "stop_hit", "tp_result", "sl_result",
)

ALLOWED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AAVEUSDT")
ALLOWED_DIRECTIONS = ("LONG", "SHORT")
COUNTED_DECISIONS = ("VALID_SETUP", "HIGH_CONFIDENCE_SETUP")
COUNTED_STATE = "ENTRY_READY"
RECOGNITION_MINIMUM = 60


class PilotStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class RecognitionObservation:
    symbol: str
    direction: str
    fold: int
    timestamp: datetime
    family: str
    decision: str
    lifecycle: str
    fingerprint: str
    rearm_parent: str | None
    poi_id: str
    liquidity_ids: tuple[str, ...]
    interaction_ids: tuple[str, ...]
    anchor_id: str | None
    structure_id: str | None
    evidence_ids: tuple[str, ...]
    evidence_cluster_ids: tuple[str, ...]
    economics_valid: bool
    risk_valid: bool
    block_reasons: tuple[str, ...]
    hard_blocks: tuple[str, ...]


@dataclass(frozen=True)
class PilotReport:
    status: PilotStatus
    total_rows: int
    counted_rows: int
    duplicate_rows: int
    invalid_lifecycle_rows: int
    unexplained_block_rows: int
    missing_provenance_rows: int
    forbidden_key_rows: int
    reproducible: bool
    block_counts: Mapping[str, int]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RecognitionReport:
    independent_entry_ready: int
    gate_pass: bool
    by_symbol: Mapping[str, int]
    by_direction: Mapping[str, int]
    by_fold: Mapping[int, int]
    duplicate_rows: int
    excluded_rows: int
    fingerprints: tuple[str, ...]


def _stable_digest(rows: Sequence[RecognitionObservation]) -> str:
    canonical = []
    for row in sorted(rows, key=lambda x: (x.timestamp, x.symbol, x.direction, x.fingerprint, x.fold)):
        payload = asdict(row)
        payload["timestamp"] = row.timestamp.isoformat()
        canonical.append(repr(sorted(payload.items())))
    return sha256("\n".join(canonical).encode("utf-8")).hexdigest()


def _contains_forbidden(value: Any, path: str = "") -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in FORBIDDEN_KEY_FRAGMENTS):
                return True
            if _contains_forbidden(nested, f"{path}.{key}"):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_forbidden(item, path) for item in value)
    return False


def _valid_lifecycle(row: RecognitionObservation) -> bool:
    if row.lifecycle == COUNTED_STATE:
        return row.economics_valid and row.risk_valid and row.decision in COUNTED_DECISIONS
    if row.decision in COUNTED_DECISIONS:
        return row.lifecycle == COUNTED_STATE
    return True


def _has_provenance(row: RecognitionObservation) -> bool:
    if not row.fingerprint or not row.poi_id or not row.evidence_ids or not row.evidence_cluster_ids:
        return False
    if row.lifecycle == COUNTED_STATE and (not row.anchor_id or not row.structure_id):
        return False
    return True


def _explained_blocks(row: RecognitionObservation) -> bool:
    allowed_prefixes = ("causal:", "data:", "economics:", "risk:")
    return all(reason.startswith(allowed_prefixes) for reason in row.hard_blocks)


def is_counted(row: RecognitionObservation) -> bool:
    return (
        row.symbol in ALLOWED_SYMBOLS
        and row.direction in ALLOWED_DIRECTIONS
        and 0 <= row.fold < 10
        and row.lifecycle == COUNTED_STATE
        and row.decision in COUNTED_DECISIONS
        and row.economics_valid
        and row.risk_valid
        and not row.hard_blocks
        and _has_provenance(row)
    )


def dedupe_global(rows: Iterable[RecognitionObservation]) -> tuple[tuple[RecognitionObservation, ...], int]:
    selected: dict[str, RecognitionObservation] = {}
    duplicates = 0
    for row in sorted(rows, key=lambda x: (x.timestamp, x.fold, x.symbol, x.direction)):
        previous = selected.get(row.fingerprint)
        if previous is None:
            selected[row.fingerprint] = row
            continue
        if row.rearm_parent == previous.fingerprint and row.timestamp > previous.timestamp:
            lineage_key = f"{row.fingerprint}:{row.timestamp.isoformat()}"
            selected[lineage_key] = row
        else:
            duplicates += 1
    output = tuple(sorted(selected.values(), key=lambda x: (x.timestamp, x.symbol, x.direction, x.fingerprint)))
    return output, duplicates


def run_pilot(rows: Iterable[RecognitionObservation]) -> PilotReport:
    source = tuple(rows)
    deduped, duplicates = dedupe_global(source)
    invalid_lifecycle = sum(not _valid_lifecycle(row) for row in source)
    unexplained_blocks = sum(not _explained_blocks(row) for row in source)
    missing_provenance = sum(not _has_provenance(row) for row in source)
    forbidden = sum(_contains_forbidden(asdict(row)) for row in source)
    digest_a = _stable_digest(deduped)
    digest_b = _stable_digest(tuple(reversed(deduped)))
    reproducible = digest_a == digest_b
    block_counts: dict[str, int] = {}
    for row in source:
        for reason in row.hard_blocks + row.block_reasons:
            block_counts[reason] = block_counts.get(reason, 0) + 1
    reasons: list[str] = []
    if duplicates:
        reasons.append(f"duplicates={duplicates}")
    if invalid_lifecycle:
        reasons.append(f"invalid_lifecycle={invalid_lifecycle}")
    if unexplained_blocks:
        reasons.append(f"unexplained_blocks={unexplained_blocks}")
    if missing_provenance:
        reasons.append(f"missing_provenance={missing_provenance}")
    if forbidden:
        reasons.append(f"forbidden_keys={forbidden}")
    if not reproducible:
        reasons.append("non_reproducible")
    status = PilotStatus.PASS if not reasons else PilotStatus.FAIL
    return PilotReport(
        status=status,
        total_rows=len(source),
        counted_rows=sum(is_counted(row) for row in deduped),
        duplicate_rows=duplicates,
        invalid_lifecycle_rows=invalid_lifecycle,
        unexplained_block_rows=unexplained_blocks,
        missing_provenance_rows=missing_provenance,
        forbidden_key_rows=forbidden,
        reproducible=reproducible,
        block_counts=dict(sorted(block_counts.items())),
        reasons=tuple(reasons),
    )


def run_full_recognition(rows: Iterable[RecognitionObservation]) -> RecognitionReport:
    source = tuple(rows)
    deduped, duplicates = dedupe_global(source)
    counted = tuple(row for row in deduped if is_counted(row))
    by_symbol = {symbol: sum(row.symbol == symbol for row in counted) for symbol in ALLOWED_SYMBOLS}
    by_direction = {direction: sum(row.direction == direction for row in counted) for direction in ALLOWED_DIRECTIONS}
    by_fold = {fold: sum(row.fold == fold for row in counted) for fold in range(10)}
    return RecognitionReport(
        independent_entry_ready=len(counted),
        gate_pass=len(counted) >= RECOGNITION_MINIMUM,
        by_symbol=by_symbol,
        by_direction=by_direction,
        by_fold=by_fold,
        duplicate_rows=duplicates,
        excluded_rows=len(source) - len(counted),
        fingerprints=tuple(sorted(row.fingerprint for row in counted)),
    )


def report_to_no_outcome_dict(report: PilotReport | RecognitionReport) -> dict[str, Any]:
    payload = asdict(report)
    if _contains_forbidden(payload):
        raise ValueError("forbidden outcome key in P7 report")
    return payload
