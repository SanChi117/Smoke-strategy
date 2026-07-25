#!/usr/bin/env python3
"""SMOKE CORE 1.0 P4: anchored causal 5m/15m execution structure."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
from typing import Any, Mapping, Sequence

from strategy_lab.interaction_engine_v1 import AnchorEventV1, InteractionState
from strategy_lab.mtf_dealing_range_v2 import ClosedBar
from strategy_lab.poi_imbalance_engine_v1 import Direction


class ConfirmationMode(str, Enum):
    NONE = "NONE"
    A_TEXTBOOK_BREAK = "A_TEXTBOOK_BREAK"
    B_ACCEPTANCE_RETEST = "B_ACCEPTANCE_RETEST"
    C_DISPLACEMENT_FAILED_RETEST = "C_DISPLACEMENT_FAILED_RETEST"


class ExecutionState(str, Enum):
    WAIT_REACTION = "WAIT_REACTION"
    REACTION_DEFINED = "REACTION_DEFINED"
    BREAK_DETECTED = "BREAK_DETECTED"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class ScenarioFamily(str, Enum):
    RAID_REVERSAL = "RAID_REVERSAL"
    TREND_CONTINUATION = "TREND_CONTINUATION"
    RANGE_ROTATION = "RANGE_ROTATION"


@dataclass(frozen=True)
class FamilyEntryPolicy:
    family: ScenarioFamily
    allowed_modes: tuple[ConfirmationMode, ...]
    minimum_confidence: float
    expiry_bars_5m: int


FAMILY_ENTRY_POLICIES: Mapping[ScenarioFamily, FamilyEntryPolicy] = {
    ScenarioFamily.RAID_REVERSAL: FamilyEntryPolicy(ScenarioFamily.RAID_REVERSAL, (ConfirmationMode.A_TEXTBOOK_BREAK, ConfirmationMode.C_DISPLACEMENT_FAILED_RETEST), 62.0, 18),
    ScenarioFamily.TREND_CONTINUATION: FamilyEntryPolicy(ScenarioFamily.TREND_CONTINUATION, (ConfirmationMode.A_TEXTBOOK_BREAK, ConfirmationMode.B_ACCEPTANCE_RETEST, ConfirmationMode.C_DISPLACEMENT_FAILED_RETEST), 58.0, 24),
    ScenarioFamily.RANGE_ROTATION: FamilyEntryPolicy(ScenarioFamily.RANGE_ROTATION, (ConfirmationMode.B_ACCEPTANCE_RETEST, ConfirmationMode.C_DISPLACEMENT_FAILED_RETEST), 64.0, 16),
}


@dataclass(frozen=True)
class ExecutionStructureConfig:
    atr_length: int = 14
    reaction_window_bars_5m: int = 6
    reaction_window_bars_15m: int = 4
    break_buffer_atr: float = 0.05
    displacement_body_atr: float = 0.55
    displacement_range_atr: float = 0.85
    directional_close_location: float = 0.67
    acceptance_closes: int = 2
    failed_retest_bars: int = 4
    anchor_invalidation_buffer_atr: float = 0.05
    anchor_invalidation_closes: int = 2
    soft_unclean_penalty: float = 14.0
    m15_stability_bonus: float = 8.0

    def __post_init__(self) -> None:
        if self.atr_length < 2 or self.acceptance_closes < 2 or self.anchor_invalidation_closes < 2:
            raise ValueError("invalid P4 config")
        if not 0.5 <= self.directional_close_location <= 1.0:
            raise ValueError("directional_close_location must be in [0.5, 1]")


@dataclass(frozen=True)
class ReactionLegV1:
    start_time: datetime
    end_time: datetime
    low: float
    high: float
    protected_swing: float
    weak_swing: float
    boundary: float
    source_timeframe: str


@dataclass(frozen=True)
class ExecutionConfirmationV1:
    confirmation_id: str
    anchor_id: str
    symbol: str
    direction: Direction
    state: ExecutionState
    mode: ConfirmationMode
    family: ScenarioFamily
    confirmed_at: datetime | None
    valid_until: datetime
    reaction_leg: ReactionLegV1 | None
    confidence_0_100: float
    clean_structure: bool
    source_timeframe: str | None
    break_time: datetime | None
    retest_time: datetime | None
    evidence_ids: tuple[str, ...]
    dependencies: tuple[str, ...]
    conflicts: tuple[str, ...]
    reasons: tuple[str, ...]
    hard_block: bool
    hard_block_reason: str | None


FORBIDDEN_KEY_FRAGMENTS = ("pnl", "future_return", "trade_outcome", "tp_result", "sl_result", "mfe", "mae", "profit_factor", "net_return", "drawdown", "exit_price")


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}_{sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _tr(rows: Sequence[ClosedBar], index: int) -> float:
    row = rows[index]
    if index == 0:
        return row.high - row.low
    previous = rows[index - 1]
    return max(row.high - row.low, abs(row.high - previous.close), abs(row.low - previous.close))


def _atr(rows: Sequence[ClosedBar], index: int, length: int) -> float:
    start = max(0, index - length + 1)
    values = [_tr(rows, i) for i in range(start, index + 1)]
    return sum(values) / max(1, len(values))


def _directional_close(row: ClosedBar, direction: Direction) -> float:
    span = max(1e-12, row.high - row.low)
    return (row.close - row.low) / span if direction == Direction.LONG else (row.high - row.close) / span


def _is_displacement(row: ClosedBar, atr: float, direction: Direction, cfg: ExecutionStructureConfig) -> bool:
    directional = row.close > row.open if direction == Direction.LONG else row.close < row.open
    return directional and abs(row.close - row.open) >= atr * cfg.displacement_body_atr and (row.high - row.low) >= atr * cfg.displacement_range_atr and _directional_close(row, direction) >= cfg.directional_close_location


def _closed_rows(rows: Sequence[ClosedBar], anchor: AnchorEventV1, evaluated_at: datetime) -> list[ClosedBar]:
    return sorted([row for row in rows if row.symbol == anchor.symbol and row.close_time >= anchor.confirmed_at and row.close_time <= evaluated_at and row.timeframe in ("5m", "15m")], key=lambda row: (row.close_time, row.timeframe))


def _reaction(anchor: AnchorEventV1, rows: Sequence[ClosedBar], cfg: ExecutionStructureConfig) -> ReactionLegV1 | None:
    m5 = [row for row in rows if row.timeframe == "5m"][:cfg.reaction_window_bars_5m]
    m15 = [row for row in rows if row.timeframe == "15m"][:cfg.reaction_window_bars_15m]
    selected = m15 if len(m15) >= 2 else m5
    if len(selected) < 2:
        return None
    low, high = min(row.low for row in selected), max(row.high for row in selected)
    protected, weak, boundary = (low, high, high) if anchor.direction == Direction.LONG else (high, low, low)
    return ReactionLegV1(selected[0].open_time, selected[-1].close_time, low, high, protected, weak, boundary, selected[0].timeframe)


def _invalidated(anchor: AnchorEventV1, rows: Sequence[ClosedBar], cfg: ExecutionStructureConfig) -> bool:
    if anchor.state in (InteractionState.INVALIDATED, InteractionState.EXPIRED):
        return True
    m5 = [row for row in rows if row.timeframe == "5m"]
    if len(m5) < cfg.anchor_invalidation_closes:
        return False
    tail = m5[-cfg.anchor_invalidation_closes:]
    atr = _atr(m5, len(m5) - 1, cfg.atr_length)
    if anchor.direction == Direction.LONG:
        reference = min(row.low for row in m5[:max(1, cfg.reaction_window_bars_5m)])
        return all(row.close < reference - atr * cfg.anchor_invalidation_buffer_atr for row in tail)
    reference = max(row.high for row in m5[:max(1, cfg.reaction_window_bars_5m)])
    return all(row.close > reference + atr * cfg.anchor_invalidation_buffer_atr for row in tail)


def _breaks(row: ClosedBar, boundary: float, atr: float, direction: Direction, cfg: ExecutionStructureConfig) -> bool:
    return row.close > boundary + atr * cfg.break_buffer_atr if direction == Direction.LONG else row.close < boundary - atr * cfg.break_buffer_atr


def _retests(row: ClosedBar, boundary: float, atr: float) -> bool:
    return row.low <= boundary + atr * 0.10 and row.high >= boundary - atr * 0.10


def evaluate_execution_structure(anchor: AnchorEventV1, bars: Sequence[ClosedBar], evaluated_at: datetime, family: ScenarioFamily, config: ExecutionStructureConfig | None = None) -> ExecutionConfirmationV1:
    cfg = config or ExecutionStructureConfig()
    policy = FAMILY_ENTRY_POLICIES[family]
    valid_until = anchor.confirmed_at + timedelta(minutes=5 * policy.expiry_bars_5m)
    base = dict(anchor_id=anchor.anchor_id, symbol=anchor.symbol, direction=anchor.direction, family=family, valid_until=valid_until, evidence_ids=tuple(sorted(set(anchor.evidence_ids))), dependencies=(anchor.anchor_id, anchor.event_id))
    if anchor.state != InteractionState.CONFIRMED:
        return ExecutionConfirmationV1(_stable_id("exec", anchor.anchor_id, family.value, "blocked"), state=ExecutionState.INVALIDATED, mode=ConfirmationMode.NONE, confirmed_at=None, reaction_leg=None, confidence_0_100=0.0, clean_structure=False, source_timeframe=None, break_time=None, retest_time=None, conflicts=("anchor_not_confirmed",), reasons=("exact_anchor_is_not_active",), hard_block=True, hard_block_reason="anchor_not_confirmed", **base)
    rows = _closed_rows(bars, anchor, evaluated_at)
    if evaluated_at > valid_until:
        return ExecutionConfirmationV1(_stable_id("exec", anchor.anchor_id, family.value, "expired"), state=ExecutionState.EXPIRED, mode=ConfirmationMode.NONE, confirmed_at=None, reaction_leg=_reaction(anchor, rows, cfg), confidence_0_100=0.0, clean_structure=False, source_timeframe=None, break_time=None, retest_time=None, conflicts=(), reasons=("family_policy_expired_without_retro_fill",), hard_block=False, hard_block_reason=None, **base)
    if _invalidated(anchor, rows, cfg):
        return ExecutionConfirmationV1(_stable_id("exec", anchor.anchor_id, family.value, "invalid"), state=ExecutionState.INVALIDATED, mode=ConfirmationMode.NONE, confirmed_at=None, reaction_leg=_reaction(anchor, rows, cfg), confidence_0_100=0.0, clean_structure=False, source_timeframe=None, break_time=None, retest_time=None, conflicts=("anchor_price_invalidation",), reasons=("two_close_anchor_invalidation",), hard_block=True, hard_block_reason="anchor_invalidated", **base)
    reaction = _reaction(anchor, rows, cfg)
    if reaction is None:
        return ExecutionConfirmationV1(_stable_id("exec", anchor.anchor_id, family.value, "wait"), state=ExecutionState.WAIT_REACTION, mode=ConfirmationMode.NONE, confirmed_at=None, reaction_leg=None, confidence_0_100=0.0, clean_structure=False, source_timeframe=None, break_time=None, retest_time=None, conflicts=(), reasons=("insufficient_closed_bars_after_exact_anchor",), hard_block=False, hard_block_reason=None, **base)
    candidates = [row for row in rows if row.close_time > reaction.end_time]
    break_index = None
    break_row = None
    clean = False
    for index, row in enumerate(candidates):
        tf_rows = [item for item in rows if item.timeframe == row.timeframe and item.close_time <= row.close_time]
        atr = _atr(tf_rows, len(tf_rows) - 1, cfg.atr_length)
        if _breaks(row, reaction.boundary, atr, anchor.direction, cfg):
            break_index, break_row, clean = index, row, _is_displacement(row, atr, anchor.direction, cfg)
            break
    if break_row is None:
        return ExecutionConfirmationV1(_stable_id("exec", anchor.anchor_id, family.value, "defined"), state=ExecutionState.REACTION_DEFINED, mode=ConfirmationMode.NONE, confirmed_at=None, reaction_leg=reaction, confidence_0_100=42.0, clean_structure=False, source_timeframe=reaction.source_timeframe, break_time=None, retest_time=None, conflicts=(), reasons=("reaction_leg_defined_waiting_for_anchored_break",), hard_block=False, hard_block_reason=None, **base)
    mode, confirmed_at, retest_time = ConfirmationMode.NONE, None, None
    confidence = 68.0 if clean else 54.0
    if clean and ConfirmationMode.A_TEXTBOOK_BREAK in policy.allowed_modes:
        mode, confirmed_at, confidence = ConfirmationMode.A_TEXTBOOK_BREAK, break_row.close_time, confidence + 10.0
    after_break = candidates[(break_index or 0) + 1:]
    if mode == ConfirmationMode.NONE and ConfirmationMode.B_ACCEPTANCE_RETEST in policy.allowed_modes:
        closes: list[ClosedBar] = []
        for row in after_break:
            tf_rows = [item for item in rows if item.timeframe == row.timeframe and item.close_time <= row.close_time]
            atr = _atr(tf_rows, len(tf_rows) - 1, cfg.atr_length)
            closes = closes + [row] if _breaks(row, reaction.boundary, atr, anchor.direction, cfg) else []
            if len(closes) >= cfg.acceptance_closes:
                accepted_at = closes[-1].close_time
                for retest in [item for item in after_break if item.close_time > accepted_at]:
                    tf2 = [item for item in rows if item.timeframe == retest.timeframe and item.close_time <= retest.close_time]
                    atr2 = _atr(tf2, len(tf2) - 1, cfg.atr_length)
                    holds = retest.close >= reaction.boundary if anchor.direction == Direction.LONG else retest.close <= reaction.boundary
                    if _retests(retest, reaction.boundary, atr2) and holds:
                        mode, confirmed_at, retest_time, confidence = ConfirmationMode.B_ACCEPTANCE_RETEST, retest.close_time, retest.close_time, max(confidence, 72.0)
                        break
                break
    if mode == ConfirmationMode.NONE and clean and ConfirmationMode.C_DISPLACEMENT_FAILED_RETEST in policy.allowed_modes:
        for retest in after_break[:cfg.failed_retest_bars]:
            tf_rows = [item for item in rows if item.timeframe == retest.timeframe and item.close_time <= retest.close_time]
            atr = _atr(tf_rows, len(tf_rows) - 1, cfg.atr_length)
            holds = retest.close >= reaction.boundary if anchor.direction == Direction.LONG else retest.close <= reaction.boundary
            counter = retest.close < retest.open if anchor.direction == Direction.LONG else retest.close > retest.open
            if _retests(retest, reaction.boundary, atr) and holds and counter:
                mode, confirmed_at, retest_time, confidence = ConfirmationMode.C_DISPLACEMENT_FAILED_RETEST, retest.close_time, retest.close_time, max(confidence, 76.0)
                break
    conflicts: list[str] = []
    reasons = [f"exact_anchor={anchor.anchor_id}", f"reaction_tf={reaction.source_timeframe}"]
    if not clean:
        conflicts.append("unclean_bos_choch_soft_penalty")
        confidence -= cfg.soft_unclean_penalty
    if break_row.timeframe == "15m":
        confidence += cfg.m15_stability_bonus
        reasons.append("15m_stability_bonus")
    if mode == ConfirmationMode.NONE:
        return ExecutionConfirmationV1(_stable_id("exec", anchor.anchor_id, family.value, "break", break_row.close_time), state=ExecutionState.BREAK_DETECTED, mode=mode, confirmed_at=None, reaction_leg=reaction, confidence_0_100=round(max(0.0, min(100.0, confidence)), 4), clean_structure=clean, source_timeframe=break_row.timeframe, break_time=break_row.close_time, retest_time=None, conflicts=tuple(conflicts), reasons=tuple(reasons + ["break_not_yet_valid_for_family_policy"]), hard_block=False, hard_block_reason=None, **base)
    if confidence < policy.minimum_confidence:
        conflicts.append("below_family_minimum_confidence")
    return ExecutionConfirmationV1(_stable_id("exec", anchor.anchor_id, family.value, mode.value, confirmed_at), state=ExecutionState.CONFIRMED, mode=mode, confirmed_at=confirmed_at, reaction_leg=reaction, confidence_0_100=round(max(0.0, min(100.0, confidence)), 4), clean_structure=clean, source_timeframe=break_row.timeframe, break_time=break_row.close_time, retest_time=retest_time, conflicts=tuple(conflicts), reasons=tuple(reasons + [f"confirmed_mode={mode.value}"]), hard_block=False, hard_block_reason=None, **base)


def execution_to_no_pnl_dict(result: ExecutionConfirmationV1) -> dict[str, Any]:
    payload = asdict(result)
    raw = str(payload).lower()
    if any(fragment in raw for fragment in FORBIDDEN_KEY_FRAGMENTS):
        raise ValueError("forbidden outcome field in P4 export")
    return payload
