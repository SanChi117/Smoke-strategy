#!/usr/bin/env python3
"""SMOKE CORE 1.0 P4: causal anchored 5m/15m execution structure.

Recognition-only layer. It derives local structure strictly from one exact P3
anchor event and closed bars. It never reads outcomes, never retro-fills a
confirmation, and does not calculate PnL, RR, sizing or leverage.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping, Sequence

from strategy_lab.interaction_engine_v1 import AnchorEventV1, InteractionState
from strategy_lab.mtf_dealing_range_v2 import ClosedBar
from strategy_lab.poi_imbalance_engine_v1 import Direction


class ExecutionMode(str, Enum):
    NONE = "NONE"
    A_TEXTBOOK_BREAK = "A_TEXTBOOK_BREAK"
    B_ACCEPTANCE_RETEST = "B_ACCEPTANCE_RETEST"
    C_DISPLACEMENT_FAILED_RETEST = "C_DISPLACEMENT_FAILED_RETEST"


class ExecutionState(str, Enum):
    NO_STRUCTURE = "NO_STRUCTURE"
    ARMED = "ARMED"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class ExecutionStructureConfig:
    atr_length: int = 14
    reaction_bars: int = 3
    displacement_body_atr: float = 0.55
    directional_close_location: float = 0.65
    acceptance_closes: int = 2
    retest_buffer_atr: float = 0.08
    failed_retest_buffer_atr: float = 0.05
    invalidation_buffer_atr: float = 0.05
    expiry_5m_bars: int = 18
    expiry_15m_bars: int = 8
    dirty_break_penalty: float = 18.0
    m15_stability_bonus: float = 8.0

    def __post_init__(self) -> None:
        if self.atr_length < 2:
            raise ValueError("atr_length must be >= 2")
        if self.reaction_bars < 2:
            raise ValueError("reaction_bars must be >= 2")
        if self.acceptance_closes < 2:
            raise ValueError("acceptance_closes must be >= 2")
        if self.expiry_5m_bars < 1 or self.expiry_15m_bars < 1:
            raise ValueError("expiry bars must be positive")


@dataclass(frozen=True)
class FamilyEntryPolicyV1:
    family: str
    allowed_modes: tuple[ExecutionMode, ...]
    entry_reference: str
    expiry_bars_5m: int
    expiry_bars_15m: int


FAMILY_ENTRY_POLICIES: tuple[FamilyEntryPolicyV1, ...] = (
    FamilyEntryPolicyV1(
        family="RAID_REVERSAL",
        allowed_modes=(ExecutionMode.A_TEXTBOOK_BREAK, ExecutionMode.C_DISPLACEMENT_FAILED_RETEST),
        entry_reference="confirmation_close_or_first_causal_retest",
        expiry_bars_5m=12,
        expiry_bars_15m=6,
    ),
    FamilyEntryPolicyV1(
        family="TREND_CONTINUATION",
        allowed_modes=(ExecutionMode.A_TEXTBOOK_BREAK, ExecutionMode.B_ACCEPTANCE_RETEST),
        entry_reference="accepted_boundary_retest",
        expiry_bars_5m=18,
        expiry_bars_15m=8,
    ),
    FamilyEntryPolicyV1(
        family="RANGE_ROTATION",
        allowed_modes=(ExecutionMode.B_ACCEPTANCE_RETEST, ExecutionMode.C_DISPLACEMENT_FAILED_RETEST),
        entry_reference="failed_reclaim_or_retest_close",
        expiry_bars_5m=10,
        expiry_bars_15m=5,
    ),
)


@dataclass(frozen=True)
class ExecutionStructureSnapshotV1:
    symbol: str
    evaluated_at: datetime
    anchor_id: str
    anchor_event_id: str
    direction: Direction
    state: ExecutionState
    mode: ExecutionMode
    confirmation_time: datetime | None
    confirmation_timeframe: str | None
    reaction_low: float | None
    reaction_high: float | None
    protected_swing: float | None
    weak_swing: float | None
    structure_boundary: float | None
    confidence_0_100: float
    dirty_break: bool
    source_poi_id: str | None
    source_liquidity_id: str | None
    evidence_ids: tuple[str, ...]
    dependencies: tuple[str, ...]
    conflicts: tuple[str, ...]
    hard_block: bool
    hard_block_reason: str | None
    valid_until: datetime
    reasons: tuple[str, ...]


FORBIDDEN_KEY_FRAGMENTS = (
    "pnl",
    "future_return",
    "trade_outcome",
    "tp_result",
    "sl_result",
    "mfe",
    "mae",
    "profit_factor",
    "net_return",
    "drawdown",
    "exit_price",
    "exit_reason",
)


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}_{sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _delta(timeframe: str) -> timedelta:
    return timedelta(minutes=15 if timeframe == "15m" else 5)


def _true_range(rows: Sequence[ClosedBar], index: int) -> float:
    current = rows[index]
    if index == 0:
        return max(0.0, current.high - current.low)
    previous = rows[index - 1]
    return max(
        current.high - current.low,
        abs(current.high - previous.close),
        abs(current.low - previous.close),
    )


def _atr_values(rows: Sequence[ClosedBar], length: int) -> list[float | None]:
    output: list[float | None] = []
    tr: list[float] = []
    for index in range(len(rows)):
        tr.append(_true_range(rows, index))
        output.append(sum(tr[-length:]) / length if len(tr) >= length else None)
    return output


def _close_location(bar: ClosedBar, direction: Direction) -> float:
    span = max(1e-12, bar.high - bar.low)
    if direction == Direction.LONG:
        return (bar.close - bar.low) / span
    if direction == Direction.SHORT:
        return (bar.high - bar.close) / span
    return 0.5


def _body(bar: ClosedBar) -> float:
    return abs(bar.close - bar.open)


def _directional(bar: ClosedBar, direction: Direction) -> bool:
    if direction == Direction.LONG:
        return bar.close > bar.open
    if direction == Direction.SHORT:
        return bar.close < bar.open
    return False


def _post_anchor(
    rows: Sequence[ClosedBar],
    anchor: AnchorEventV1,
    evaluated_at: datetime,
    timeframe: str,
) -> list[ClosedBar]:
    return sorted(
        [
            row
            for row in rows
            if row.symbol == anchor.symbol
            and row.timeframe == timeframe
            and row.close_time > anchor.confirmed_at
            and row.close_time <= evaluated_at
        ],
        key=lambda row: row.close_time,
    )


def _expiry(anchor: AnchorEventV1, config: ExecutionStructureConfig) -> datetime:
    return min(
        anchor.valid_until,
        anchor.confirmed_at + timedelta(minutes=5 * config.expiry_5m_bars),
        anchor.confirmed_at + timedelta(minutes=15 * config.expiry_15m_bars),
    )


def _boundary(reaction: Sequence[ClosedBar], direction: Direction) -> tuple[float, float, float, float]:
    reaction_low = min(row.low for row in reaction)
    reaction_high = max(row.high for row in reaction)
    if direction == Direction.LONG:
        protected = reaction_low
        weak = reaction_high
    else:
        protected = reaction_high
        weak = reaction_low
    return reaction_low, reaction_high, protected, weak


def _breaks(bar: ClosedBar, boundary: float, direction: Direction) -> bool:
    return bar.close > boundary if direction == Direction.LONG else bar.close < boundary


def _wick_breaks(bar: ClosedBar, boundary: float, direction: Direction) -> bool:
    return bar.high > boundary if direction == Direction.LONG else bar.low < boundary


def _touches_boundary(bar: ClosedBar, boundary: float, buffer_: float) -> bool:
    return bar.low <= boundary + buffer_ and bar.high >= boundary - buffer_


def _protected_invalidated(bar: ClosedBar, protected: float, direction: Direction, buffer_: float) -> bool:
    if direction == Direction.LONG:
        return bar.close < protected - buffer_
    return bar.close > protected + buffer_


def _evaluate_timeframe(
    rows: Sequence[ClosedBar],
    anchor: AnchorEventV1,
    evaluated_at: datetime,
    timeframe: str,
    config: ExecutionStructureConfig,
) -> Mapping[str, Any]:
    post = _post_anchor(rows, anchor, evaluated_at, timeframe)
    if len(post) < config.reaction_bars + 1:
        return {"mode": ExecutionMode.NONE, "rows": post}
    atrs = _atr_values(post, config.atr_length)
    reaction = post[: config.reaction_bars]
    reaction_low, reaction_high, protected, weak = _boundary(reaction, anchor.direction)
    later = post[config.reaction_bars :]
    dirty = False
    conflicts: list[str] = []

    for index, bar in enumerate(later, start=config.reaction_bars):
        atr = atrs[index] or max(1e-12, bar.high - bar.low)
        invalid_buffer = atr * config.invalidation_buffer_atr
        if _protected_invalidated(bar, protected, anchor.direction, invalid_buffer):
            return {
                "mode": ExecutionMode.NONE,
                "invalidated": True,
                "confirmation": bar.close_time,
                "reaction_low": reaction_low,
                "reaction_high": reaction_high,
                "protected": protected,
                "weak": weak,
                "boundary": weak,
                "rows": post,
            }

        if _wick_breaks(bar, weak, anchor.direction) and not _breaks(bar, weak, anchor.direction):
            dirty = True
            if "wick_only_break" not in conflicts:
                conflicts.append("wick_only_break")

        displacement = (
            _body(bar) >= atr * config.displacement_body_atr
            and _close_location(bar, anchor.direction) >= config.directional_close_location
            and _directional(bar, anchor.direction)
        )
        if _breaks(bar, weak, anchor.direction) and displacement:
            return {
                "mode": ExecutionMode.A_TEXTBOOK_BREAK,
                "confirmation": bar.close_time,
                "reaction_low": reaction_low,
                "reaction_high": reaction_high,
                "protected": protected,
                "weak": weak,
                "boundary": weak,
                "dirty": dirty,
                "conflicts": tuple(conflicts),
                "rows": post,
            }

    accepted_indexes: list[int] = []
    for index, bar in enumerate(later, start=config.reaction_bars):
        if _breaks(bar, weak, anchor.direction):
            accepted_indexes.append(index)
            if len(accepted_indexes) >= config.acceptance_closes and accepted_indexes[-1] - accepted_indexes[-2] == 1:
                last_accept = accepted_indexes[-1]
                atr = atrs[last_accept] or max(1e-12, post[last_accept].high - post[last_accept].low)
                for retest in post[last_accept + 1 :]:
                    if _touches_boundary(retest, weak, atr * config.retest_buffer_atr) and _directional(retest, anchor.direction):
                        return {
                            "mode": ExecutionMode.B_ACCEPTANCE_RETEST,
                            "confirmation": retest.close_time,
                            "reaction_low": reaction_low,
                            "reaction_high": reaction_high,
                            "protected": protected,
                            "weak": weak,
                            "boundary": weak,
                            "dirty": dirty,
                            "conflicts": tuple(conflicts),
                            "rows": post,
                        }
        else:
            accepted_indexes.clear()

    for index, bar in enumerate(later, start=config.reaction_bars):
        atr = atrs[index] or max(1e-12, bar.high - bar.low)
        displacement = (
            _body(bar) >= atr * config.displacement_body_atr
            and _close_location(bar, anchor.direction) >= config.directional_close_location
            and _directional(bar, anchor.direction)
            and _breaks(bar, weak, anchor.direction)
        )
        if not displacement:
            continue
        for retest in post[index + 1 :]:
            buffer_ = atr * config.failed_retest_buffer_atr
            if not _touches_boundary(retest, weak, buffer_):
                continue
            failed_reclaim = (
                retest.close >= weak - buffer_ if anchor.direction == Direction.LONG else retest.close <= weak + buffer_
            )
            if failed_reclaim and _directional(retest, anchor.direction):
                return {
                    "mode": ExecutionMode.C_DISPLACEMENT_FAILED_RETEST,
                    "confirmation": retest.close_time,
                    "reaction_low": reaction_low,
                    "reaction_high": reaction_high,
                    "protected": protected,
                    "weak": weak,
                    "boundary": weak,
                    "dirty": dirty,
                    "conflicts": tuple(conflicts),
                    "rows": post,
                }

    return {
        "mode": ExecutionMode.NONE,
        "reaction_low": reaction_low,
        "reaction_high": reaction_high,
        "protected": protected,
        "weak": weak,
        "boundary": weak,
        "dirty": dirty,
        "conflicts": tuple(conflicts),
        "rows": post,
    }


def build_execution_structure_snapshot(
    anchor: AnchorEventV1,
    bars_5m: Sequence[ClosedBar],
    bars_15m: Sequence[ClosedBar],
    evaluated_at: datetime,
    config: ExecutionStructureConfig | None = None,
) -> ExecutionStructureSnapshotV1:
    cfg = config or ExecutionStructureConfig()
    valid_until = _expiry(anchor, cfg)
    dependencies = (anchor.anchor_id, anchor.event_id)

    if anchor.state != InteractionState.CONFIRMED:
        return ExecutionStructureSnapshotV1(
            symbol=anchor.symbol,
            evaluated_at=evaluated_at,
            anchor_id=anchor.anchor_id,
            anchor_event_id=anchor.event_id,
            direction=anchor.direction,
            state=ExecutionState.INVALIDATED,
            mode=ExecutionMode.NONE,
            confirmation_time=None,
            confirmation_timeframe=None,
            reaction_low=None,
            reaction_high=None,
            protected_swing=None,
            weak_swing=None,
            structure_boundary=None,
            confidence_0_100=0.0,
            dirty_break=False,
            source_poi_id=anchor.source_poi_id,
            source_liquidity_id=anchor.source_liquidity_id,
            evidence_ids=anchor.evidence_ids,
            dependencies=dependencies,
            conflicts=("anchor_not_confirmed",),
            hard_block=True,
            hard_block_reason="anchor_not_confirmed",
            valid_until=valid_until,
            reasons=("exact_confirmed_anchor_required",),
        )

    if evaluated_at > valid_until:
        return ExecutionStructureSnapshotV1(
            symbol=anchor.symbol,
            evaluated_at=evaluated_at,
            anchor_id=anchor.anchor_id,
            anchor_event_id=anchor.event_id,
            direction=anchor.direction,
            state=ExecutionState.EXPIRED,
            mode=ExecutionMode.NONE,
            confirmation_time=None,
            confirmation_timeframe=None,
            reaction_low=None,
            reaction_high=None,
            protected_swing=None,
            weak_swing=None,
            structure_boundary=None,
            confidence_0_100=0.0,
            dirty_break=False,
            source_poi_id=anchor.source_poi_id,
            source_liquidity_id=anchor.source_liquidity_id,
            evidence_ids=anchor.evidence_ids,
            dependencies=dependencies,
            conflicts=("anchor_expired",),
            hard_block=False,
            hard_block_reason=None,
            valid_until=valid_until,
            reasons=("no_retroactive_confirmation_after_expiry",),
        )

    result_5m = _evaluate_timeframe(bars_5m, anchor, evaluated_at, "5m", cfg)
    result_15m = _evaluate_timeframe(bars_15m, anchor, evaluated_at, "15m", cfg)
    if result_5m.get("invalidated") or result_15m.get("invalidated"):
        source = result_15m if result_15m.get("invalidated") else result_5m
        return ExecutionStructureSnapshotV1(
            symbol=anchor.symbol,
            evaluated_at=evaluated_at,
            anchor_id=anchor.anchor_id,
            anchor_event_id=anchor.event_id,
            direction=anchor.direction,
            state=ExecutionState.INVALIDATED,
            mode=ExecutionMode.NONE,
            confirmation_time=source.get("confirmation"),
            confirmation_timeframe="15m" if result_15m.get("invalidated") else "5m",
            reaction_low=source.get("reaction_low"),
            reaction_high=source.get("reaction_high"),
            protected_swing=source.get("protected"),
            weak_swing=source.get("weak"),
            structure_boundary=source.get("boundary"),
            confidence_0_100=0.0,
            dirty_break=False,
            source_poi_id=anchor.source_poi_id,
            source_liquidity_id=anchor.source_liquidity_id,
            evidence_ids=anchor.evidence_ids,
            dependencies=dependencies,
            conflicts=("protected_swing_invalidated",),
            hard_block=True,
            hard_block_reason="protected_swing_invalidated",
            valid_until=valid_until,
            reasons=("local_structure_invalidated",),
        )

    candidates: list[tuple[str, Mapping[str, Any]]] = []
    if result_5m.get("mode") != ExecutionMode.NONE:
        candidates.append(("5m", result_5m))
    if result_15m.get("mode") != ExecutionMode.NONE:
        candidates.append(("15m", result_15m))
    candidates.sort(key=lambda item: item[1]["confirmation"])

    if not candidates:
        source = result_5m if result_5m.get("reaction_low") is not None else result_15m
        dirty = bool(result_5m.get("dirty") or result_15m.get("dirty"))
        conflicts = tuple(sorted(set(result_5m.get("conflicts", ()) + result_15m.get("conflicts", ()))))
        confidence = 42.0 - (cfg.dirty_break_penalty if dirty else 0.0)
        return ExecutionStructureSnapshotV1(
            symbol=anchor.symbol,
            evaluated_at=evaluated_at,
            anchor_id=anchor.anchor_id,
            anchor_event_id=anchor.event_id,
            direction=anchor.direction,
            state=ExecutionState.ARMED if source.get("reaction_low") is not None else ExecutionState.NO_STRUCTURE,
            mode=ExecutionMode.NONE,
            confirmation_time=None,
            confirmation_timeframe=None,
            reaction_low=source.get("reaction_low"),
            reaction_high=source.get("reaction_high"),
            protected_swing=source.get("protected"),
            weak_swing=source.get("weak"),
            structure_boundary=source.get("boundary"),
            confidence_0_100=round(_clamp(confidence), 4),
            dirty_break=dirty,
            source_poi_id=anchor.source_poi_id,
            source_liquidity_id=anchor.source_liquidity_id,
            evidence_ids=anchor.evidence_ids,
            dependencies=dependencies,
            conflicts=conflicts,
            hard_block=False,
            hard_block_reason=None,
            valid_until=valid_until,
            reasons=("waiting_for_causal_confirmation",),
        )

    timeframe, selected = candidates[0]
    dirty = bool(selected.get("dirty"))
    confidence = 72.0
    if selected["mode"] == ExecutionMode.B_ACCEPTANCE_RETEST:
        confidence += 8.0
    elif selected["mode"] == ExecutionMode.C_DISPLACEMENT_FAILED_RETEST:
        confidence += 5.0
    if timeframe == "15m":
        confidence += cfg.m15_stability_bonus
    if dirty:
        confidence -= cfg.dirty_break_penalty
    return ExecutionStructureSnapshotV1(
        symbol=anchor.symbol,
        evaluated_at=evaluated_at,
        anchor_id=anchor.anchor_id,
        anchor_event_id=anchor.event_id,
        direction=anchor.direction,
        state=ExecutionState.CONFIRMED,
        mode=selected["mode"],
        confirmation_time=selected["confirmation"],
        confirmation_timeframe=timeframe,
        reaction_low=selected["reaction_low"],
        reaction_high=selected["reaction_high"],
        protected_swing=selected["protected"],
        weak_swing=selected["weak"],
        structure_boundary=selected["boundary"],
        confidence_0_100=round(_clamp(confidence), 4),
        dirty_break=dirty,
        source_poi_id=anchor.source_poi_id,
        source_liquidity_id=anchor.source_liquidity_id,
        evidence_ids=anchor.evidence_ids,
        dependencies=dependencies,
        conflicts=tuple(selected.get("conflicts", ())),
        hard_block=False,
        hard_block_reason=None,
        valid_until=valid_until,
        reasons=(f"confirmed_by_{selected['mode'].value}", f"timeframe={timeframe}"),
    )


def snapshot_to_no_pnl_dict(snapshot: ExecutionStructureSnapshotV1) -> dict[str, Any]:
    payload = asdict(snapshot)
    raw_keys = " ".join(payload.keys()).lower()
    for forbidden in FORBIDDEN_KEY_FRAGMENTS:
        if forbidden in raw_keys:
            raise ValueError(f"forbidden outcome field: {forbidden}")
    return payload


def family_entry_policy(family: str) -> FamilyEntryPolicyV1:
    for policy in FAMILY_ENTRY_POLICIES:
        if policy.family == family:
            return policy
    raise KeyError(f"unknown family: {family}")
