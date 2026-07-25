#!/usr/bin/env python3
"""SMOKE CORE 1.0 P4: causal anchored 5m/15m execution structure.

Recognition-only. It consumes one exact confirmed P3 anchor and closed 5m/15m
bars, derives a local reaction leg and protected/weak swings, and emits one of
three fixed confirmation modes. No trade outcome, PnL, RR, sizing or execution.
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
    DISCOVERED = "DISCOVERED"
    ARMED = "ARMED"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class ExecutionConfig:
    atr_length: int = 14
    reaction_window_bars: int = 6
    pivot_left: int = 1
    pivot_right: int = 1
    break_buffer_atr: float = 0.05
    displacement_body_atr: float = 0.55
    displacement_range_atr: float = 0.85
    directional_close_location: float = 0.65
    acceptance_closes: int = 2
    retest_buffer_atr: float = 0.08
    failed_retest_buffer_atr: float = 0.05
    expiry_5m_bars: int = 24
    expiry_15m_bars: int = 8
    invalidation_buffer_atr: float = 0.05
    invalidation_closes: int = 2
    soft_unclean_penalty: float = 12.0

    def __post_init__(self) -> None:
        if self.atr_length < 2:
            raise ValueError("atr_length must be >= 2")
        if self.acceptance_closes < 2:
            raise ValueError("acceptance_closes must be >= 2")
        if self.invalidation_closes < 2:
            raise ValueError("invalidation_closes must be >= 2")
        if not 0.5 <= self.directional_close_location <= 1.0:
            raise ValueError("directional_close_location must be in [0.5, 1]")


@dataclass(frozen=True)
class LocalStructureV1:
    structure_id: str
    symbol: str
    anchor_id: str
    direction: Direction
    anchor_confirmed_at: datetime
    evaluated_at: datetime
    reaction_low: float
    reaction_high: float
    protected_swing: float
    weak_swing: float
    boundary: float
    confirmation_mode: ExecutionMode
    state: ExecutionState
    confirmed_at: datetime | None
    entry_time: datetime | None
    valid_until: datetime
    confidence_0_100: float
    clean_structure: bool
    source_timeframe: str | None
    source_bar_close: datetime | None
    dependencies: tuple[str, ...]
    conflicts: tuple[str, ...]
    reasons: tuple[str, ...]


FORBIDDEN_KEY_FRAGMENTS = (
    "pnl", "future_return", "trade_outcome", "tp_result", "sl_result",
    "mfe", "mae", "profit_factor", "net_return", "drawdown",
    "exit_price", "exit_reason",
)


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return f"{prefix}_{sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _true_range(rows: Sequence[ClosedBar], i: int) -> float:
    b = rows[i]
    if i == 0:
        return max(0.0, b.high - b.low)
    p = rows[i - 1]
    return max(b.high - b.low, abs(b.high - p.close), abs(b.low - p.close))


def _atr(rows: Sequence[ClosedBar], length: int) -> list[float | None]:
    out: list[float | None] = []
    tr: list[float] = []
    for i in range(len(rows)):
        tr.append(_true_range(rows, i))
        out.append(sum(tr[-length:]) / length if len(tr) >= length else None)
    return out


def _close_location(bar: ClosedBar, direction: Direction) -> float:
    span = max(1e-12, bar.high - bar.low)
    if direction == Direction.LONG:
        return (bar.close - bar.low) / span
    return (bar.high - bar.close) / span


def _directional(bar: ClosedBar, direction: Direction) -> bool:
    return bar.close > bar.open if direction == Direction.LONG else bar.close < bar.open


def _displacement(bar: ClosedBar, atr: float, direction: Direction, cfg: ExecutionConfig) -> bool:
    return (
        _directional(bar, direction)
        and abs(bar.close - bar.open) >= atr * cfg.displacement_body_atr
        and (bar.high - bar.low) >= atr * cfg.displacement_range_atr
        and _close_location(bar, direction) >= cfg.directional_close_location
    )


def _closed_rows(
    bars_by_tf: Mapping[str, Sequence[ClosedBar]],
    symbol: str,
    anchor_time: datetime,
    evaluated_at: datetime,
) -> dict[str, list[ClosedBar]]:
    out: dict[str, list[ClosedBar]] = {}
    for tf in ("5m", "15m"):
        out[tf] = sorted(
            [
                b for b in bars_by_tf.get(tf, ())
                if b.symbol == symbol and anchor_time <= b.close_time <= evaluated_at
            ],
            key=lambda b: b.close_time,
        )
    return out


def _reaction_bounds(rows: Sequence[ClosedBar], limit: int) -> tuple[float, float]:
    sample = rows[: max(1, min(limit, len(rows)))]
    return min(b.low for b in sample), max(b.high for b in sample)


def _invalidation_count(
    merged: Sequence[ClosedBar],
    direction: Direction,
    protected: float,
    buffer_: float,
) -> int:
    run = 0
    best = 0
    for bar in merged:
        invalid = (
            bar.close < protected - buffer_
            if direction == Direction.LONG
            else bar.close > protected + buffer_
        )
        run = run + 1 if invalid else 0
        best = max(best, run)
    return best


def _mode_a(rows: Sequence[ClosedBar], atrs: Sequence[float | None], boundary: float, direction: Direction, cfg: ExecutionConfig) -> tuple[ClosedBar, float] | None:
    for i, bar in enumerate(rows):
        atr = atrs[i] or max(1e-12, bar.high - bar.low)
        broken = bar.close > boundary + atr * cfg.break_buffer_atr if direction == Direction.LONG else bar.close < boundary - atr * cfg.break_buffer_atr
        if broken and _displacement(bar, atr, direction, cfg):
            return bar, atr
    return None


def _mode_b(rows: Sequence[ClosedBar], atrs: Sequence[float | None], boundary: float, direction: Direction, cfg: ExecutionConfig) -> tuple[ClosedBar, float] | None:
    accepted = 0
    accepted_at: int | None = None
    for i, bar in enumerate(rows):
        atr = atrs[i] or max(1e-12, bar.high - bar.low)
        beyond = bar.close > boundary + atr * cfg.break_buffer_atr if direction == Direction.LONG else bar.close < boundary - atr * cfg.break_buffer_atr
        accepted = accepted + 1 if beyond else 0
        if accepted >= cfg.acceptance_closes:
            accepted_at = i
            break
    if accepted_at is None:
        return None
    for i in range(accepted_at + 1, len(rows)):
        bar = rows[i]
        atr = atrs[i] or max(1e-12, bar.high - bar.low)
        touched = bar.low <= boundary + atr * cfg.retest_buffer_atr if direction == Direction.LONG else bar.high >= boundary - atr * cfg.retest_buffer_atr
        held = bar.close >= boundary if direction == Direction.LONG else bar.close <= boundary
        if touched and held:
            return bar, atr
    return None


def _mode_c(rows: Sequence[ClosedBar], atrs: Sequence[float | None], boundary: float, direction: Direction, cfg: ExecutionConfig) -> tuple[ClosedBar, float] | None:
    displacement_i: int | None = None
    for i, bar in enumerate(rows):
        atr = atrs[i] or max(1e-12, bar.high - bar.low)
        left = bar.close > boundary + atr * cfg.break_buffer_atr if direction == Direction.LONG else bar.close < boundary - atr * cfg.break_buffer_atr
        if left and _displacement(bar, atr, direction, cfg):
            displacement_i = i
            break
    if displacement_i is None:
        return None
    for i in range(displacement_i + 1, len(rows)):
        bar = rows[i]
        atr = atrs[i] or max(1e-12, bar.high - bar.low)
        counter = not _directional(bar, direction)
        failed = (
            bar.low <= boundary + atr * cfg.failed_retest_buffer_atr and bar.close > boundary
            if direction == Direction.LONG
            else bar.high >= boundary - atr * cfg.failed_retest_buffer_atr and bar.close < boundary
        )
        if counter and failed:
            return bar, atr
    return None


def evaluate_execution_structure(anchor: AnchorEventV1, bars_by_tf: Mapping[str, Sequence[ClosedBar]], evaluated_at: datetime, config: ExecutionConfig | None = None) -> LocalStructureV1:
    cfg = config or ExecutionConfig()
    symbol = anchor.symbol
    sid = _stable_id("structure", anchor.anchor_id, evaluated_at.isoformat())

    def blocked(state: ExecutionState, reason: str) -> LocalStructureV1:
        return LocalStructureV1(
            structure_id=sid, symbol=symbol, anchor_id=anchor.anchor_id,
            direction=anchor.direction, anchor_confirmed_at=anchor.confirmed_at,
            evaluated_at=evaluated_at, reaction_low=0.0, reaction_high=0.0,
            protected_swing=0.0, weak_swing=0.0, boundary=0.0,
            confirmation_mode=ExecutionMode.NONE, state=state,
            confirmed_at=None, entry_time=None, valid_until=anchor.valid_until,
            confidence_0_100=0.0, clean_structure=False, source_timeframe=None,
            source_bar_close=None, dependencies=(anchor.anchor_id,),
            conflicts=(reason,), reasons=(reason,),
        )

    if anchor.state != InteractionState.CONFIRMED:
        return blocked(ExecutionState.INVALIDATED, "anchor_not_confirmed")
    if evaluated_at < anchor.confirmed_at:
        return blocked(ExecutionState.INVALIDATED, "evaluation_before_anchor_confirmation")
    if evaluated_at > anchor.valid_until:
        return blocked(ExecutionState.EXPIRED, "anchor_expired")

    closed = _closed_rows(bars_by_tf, symbol, anchor.confirmed_at, evaluated_at)
    if not closed["5m"] and not closed["15m"]:
        return blocked(ExecutionState.DISCOVERED, "no_closed_execution_bars")

    seed = closed["5m"] or closed["15m"]
    reaction_low, reaction_high = _reaction_bounds(seed, cfg.reaction_window_bars)
    if anchor.direction == Direction.LONG:
        protected, weak, boundary = reaction_low, reaction_high, reaction_high
    else:
        protected, weak, boundary = reaction_high, reaction_low, reaction_low

    merged = sorted(closed["5m"] + closed["15m"], key=lambda b: (b.close_time, b.timeframe))
    reference_atr = max(1e-12, sum(b.high - b.low for b in seed[:cfg.atr_length]) / min(len(seed), cfg.atr_length))
    invalidated = _invalidation_count(merged, anchor.direction, protected, reference_atr * cfg.invalidation_buffer_atr) >= cfg.invalidation_closes
    if invalidated:
        state = ExecutionState.INVALIDATED
        mode = ExecutionMode.NONE
        hit = None
        tf = None
        confidence = 0.0
        conflicts = ("protected_swing_invalidated",)
        reasons = ("two_closed_candles_beyond_protected_swing",)
    else:
        selected: tuple[ExecutionMode, ClosedBar, str, float] | None = None
        for tf in ("15m", "5m"):
            rows = closed[tf]
            if not rows:
                continue
            atrs = _atr(rows, cfg.atr_length)
            a = _mode_a(rows, atrs, boundary, anchor.direction, cfg)
            b = _mode_b(rows, atrs, boundary, anchor.direction, cfg)
            c = _mode_c(rows, atrs, boundary, anchor.direction, cfg)
            candidates = []
            if a:
                candidates.append((ExecutionMode.A_TEXTBOOK_BREAK, a[0], tf, 86.0))
            if b:
                candidates.append((ExecutionMode.B_ACCEPTANCE_RETEST, b[0], tf, 82.0))
            if c:
                candidates.append((ExecutionMode.C_DISPLACEMENT_FAILED_RETEST, c[0], tf, 78.0))
            if candidates:
                candidates.sort(key=lambda x: (x[1].close_time, -x[3]))
                selected = candidates[0]
                break
        if selected:
            mode, hit, tf, confidence = selected
            state = ExecutionState.CONFIRMED
            clean = mode == ExecutionMode.A_TEXTBOOK_BREAK and tf == "15m"
            conflicts = () if clean else ("unclean_structure_soft_penalty",)
            if conflicts:
                confidence -= cfg.soft_unclean_penalty
            reasons = (f"confirmed_{mode.value.lower()}", f"source_timeframe={tf}")
        else:
            mode, hit, tf, confidence = ExecutionMode.NONE, None, None, 45.0
            state = ExecutionState.ARMED
            conflicts = ()
            reasons = ("anchored_structure_armed_waiting_confirmation",)

    clean = not conflicts
    source_close = hit.close_time if hit else None
    valid_until = min(anchor.valid_until, anchor.confirmed_at + timedelta(minutes=max(cfg.expiry_5m_bars * 5, cfg.expiry_15m_bars * 15)))
    if evaluated_at > valid_until and state not in (ExecutionState.CONFIRMED, ExecutionState.INVALIDATED):
        state = ExecutionState.EXPIRED
        confidence = 0.0
        reasons = ("execution_structure_expired",)

    return LocalStructureV1(
        structure_id=sid, symbol=symbol, anchor_id=anchor.anchor_id,
        direction=anchor.direction, anchor_confirmed_at=anchor.confirmed_at,
        evaluated_at=evaluated_at, reaction_low=reaction_low, reaction_high=reaction_high,
        protected_swing=protected, weak_swing=weak, boundary=boundary,
        confirmation_mode=mode, state=state,
        confirmed_at=source_close if state == ExecutionState.CONFIRMED else None,
        entry_time=source_close if state == ExecutionState.CONFIRMED else None,
        valid_until=valid_until, confidence_0_100=round(max(0.0, min(100.0, confidence)), 4),
        clean_structure=clean, source_timeframe=tf, source_bar_close=source_close,
        dependencies=tuple(sorted(set((anchor.anchor_id,) + anchor.dependencies))),
        conflicts=tuple(conflicts), reasons=tuple(reasons),
    )


def structure_to_no_pnl_dict(value: LocalStructureV1) -> dict[str, Any]:
    payload = asdict(value)
    payload["direction"] = value.direction.value
    payload["confirmation_mode"] = value.confirmation_mode.value
    payload["state"] = value.state.value

    def inspect(obj: Any, path: str = "root") -> None:
        if isinstance(obj, Mapping):
            for key, item in obj.items():
                lowered = str(key).lower()
                if any(fragment in lowered for fragment in FORBIDDEN_KEY_FRAGMENTS):
                    raise ValueError(f"forbidden outcome key at {path}.{key}")
                inspect(item, f"{path}.{key}")
        elif isinstance(obj, (list, tuple)):
            for i, item in enumerate(obj):
                inspect(item, f"{path}[{i}]")
    inspect(payload)
    return payload
