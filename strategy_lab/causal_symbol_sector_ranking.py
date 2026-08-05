#!/usr/bin/env python3
"""Causal symbol/sector ranking for preregistered SMOKE studies.

At an entry timestamp the rank may use only shadow trades whose exit timestamp
is already known. All valid baseline signals stay in the common shadow book,
including signals a candidate later downweights or blocks. This keeps policies
comparable without future leakage.

Research only. No live execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class RankingPolicy:
    name: str
    mode: str


POLICIES: tuple[RankingPolicy, ...] = (
    RankingPolicy("RANK_CONTROL_NO_OVERLAY", "control"),
    RankingPolicy("RANK_SYMBOL_SOFT_RISK", "symbol_soft"),
    RankingPolicy("RANK_SECTOR_SOFT_RISK", "sector_soft"),
    RankingPolicy("RANK_HYBRID_SOFT_RISK", "hybrid_soft"),
    RankingPolicy("RANK_HYBRID_PRIORITY_ONLY", "hybrid_priority"),
    RankingPolicy("RANK_HYBRID_BOTTOM_QUARTILE_GATE", "hybrid_bottom_gate"),
)


def parse_dt(value: object) -> datetime:
    return datetime.fromisoformat(str(value).strip().replace("Z", ""))


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def load_sector_map(payload: Mapping[str, object]) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for raw in payload.get("symbols", []) or []:
        if not isinstance(raw, Mapping):
            continue
        symbol = str(raw.get("symbol") or "").strip().upper()
        sectors = tuple(
            str(item).strip()
            for item in (raw.get("sectors") or [])
            if str(item).strip()
        )
        if symbol:
            out[symbol] = sectors or ("untagged",)
    return out


def cost_adjusted_r(
    row: Mapping[str, object],
    fee_rate: float,
    slippage_rate: float,
) -> float:
    """Convert a completed shadow trade to net R using frozen costs."""
    entry = safe_float(row.get("entry"), 0.0)
    stop = safe_float(row.get("stop"), 0.0)
    gross_r = safe_float(row.get("r_mult"), 0.0)
    if entry <= 0:
        return gross_r
    risk_distance = abs(entry - stop) / entry
    if risk_distance <= 1e-12:
        return gross_r
    round_trip_cost = 2.0 * (
        max(0.0, fee_rate) + max(0.0, slippage_rate)
    )
    return gross_r - round_trip_cost / risk_distance


def shrunk_mean(values: Sequence[float], prior_strength: float) -> float:
    if not values:
        return 0.0
    return sum(values) / (len(values) + max(0.0, prior_strength))


def percentile(scores: Mapping[str, float], key: str) -> float | None:
    if key not in scores or not scores:
        return None
    value = scores[key]
    below = sum(1 for score in scores.values() if score < value)
    equal = sum(1 for score in scores.values() if score == value)
    return (below + 0.5 * equal) / len(scores)


def _eligible_history(
    rows: Sequence[Mapping[str, object]],
    as_of: datetime,
    lookback_days: int,
) -> list[Mapping[str, object]]:
    lower = as_of - timedelta(days=max(1, lookback_days))
    output: list[Mapping[str, object]] = []
    for row in rows:
        exit_time = parse_dt(row.get("exit_time"))
        if lower <= exit_time <= as_of:
            output.append(row)
    return output


def causal_snapshot(
    rows: Sequence[Mapping[str, object]],
    as_of: datetime,
    symbol: str,
    sector_map: Mapping[str, Sequence[str]],
    lookback_days: int,
    fee_rate: float,
    slippage_rate: float,
    min_symbol_trades: int = 3,
    min_sector_trades: int = 6,
    symbol_prior_strength: float = 5.0,
    sector_prior_strength: float = 10.0,
) -> dict[str, object]:
    """Return rank facts using completed shadow outcomes only."""
    history = _eligible_history(rows, as_of, lookback_days)
    symbol_values: dict[str, list[float]] = {}
    sector_values: dict[str, list[float]] = {}
    for row in history:
        row_symbol = str(row.get("symbol") or "").strip().upper()
        if not row_symbol:
            continue
        net_r = cost_adjusted_r(row, fee_rate, slippage_rate)
        symbol_values.setdefault(row_symbol, []).append(net_r)
        sectors = tuple(sector_map.get(row_symbol) or ("untagged",))
        for sector in sectors:
            sector_values.setdefault(str(sector), []).append(net_r)

    symbol_scores = {
        key: shrunk_mean(values, symbol_prior_strength)
        for key, values in symbol_values.items()
        if len(values) >= min_symbol_trades
    }
    sector_scores = {
        key: shrunk_mean(values, sector_prior_strength)
        for key, values in sector_values.items()
        if len(values) >= min_sector_trades
    }

    symbol = symbol.strip().upper()
    symbol_pct = percentile(symbol_scores, symbol)
    sector_pcts: list[float] = []
    for sector in tuple(sector_map.get(symbol) or ("untagged",)):
        value = percentile(sector_scores, str(sector))
        if value is not None:
            sector_pcts.append(value)
    sector_pct = mean(sector_pcts) if sector_pcts else None
    available = [
        value for value in (symbol_pct, sector_pct) if value is not None
    ]
    hybrid_pct = mean(available) if available else None
    if hybrid_pct is None:
        state = "missing"
    elif hybrid_pct >= 0.75:
        state = "top"
    elif hybrid_pct >= 0.50:
        state = "upper_mid"
    elif hybrid_pct >= 0.25:
        state = "lower_mid"
    else:
        state = "bottom"

    return {
        "as_of": as_of.isoformat(timespec="seconds"),
        "history_trades": len(history),
        "symbol_rank_pct": symbol_pct,
        "sector_rank_pct": sector_pct,
        "hybrid_rank_pct": hybrid_pct,
        "ranking_state": state,
        "symbol_history_trades": len(symbol_values.get(symbol, [])),
        "sector_history_trades": sum(
            len(sector_values.get(str(sector), []))
            for sector in tuple(sector_map.get(symbol) or ("untagged",))
        ),
    }


def annotate_rankings(
    rows: Iterable[Mapping[str, object]],
    sector_map: Mapping[str, Sequence[str]],
    lookback_days: int,
    fee_rate: float,
    slippage_rate: float,
) -> list[dict[str, object]]:
    """Attach causal rank facts to every baseline shadow signal."""
    source = [dict(row) for row in rows]
    ordered = sorted(
        source,
        key=lambda row: (
            parse_dt(row.get("entry_time")),
            str(row.get("symbol")),
        ),
    )
    output: list[dict[str, object]] = []
    for row in ordered:
        snapshot = causal_snapshot(
            source,
            parse_dt(row.get("entry_time")),
            str(row.get("symbol") or ""),
            sector_map,
            lookback_days,
            fee_rate,
            slippage_rate,
        )
        copy = dict(row)
        for key, value in snapshot.items():
            copy[key] = "" if value is None else value
        copy["ranking_lookback_days"] = lookback_days
        copy["ranking_shadow_book"] = (
            "all_valid_baseline_signals_completed_before_entry"
        )
        output.append(copy)
    return output


def _band_multiplier(
    value: float | None,
    missing: float,
    top: float,
    middle: float,
    bottom: float,
) -> float:
    if value is None:
        return missing
    if value >= 0.75:
        return top
    if value >= 0.25:
        return middle
    return bottom


def apply_policy(
    rows: Iterable[Mapping[str, object]],
    policy: RankingPolicy,
) -> list[dict[str, object]]:
    """Create one frozen policy view without changing entry/exit geometry."""
    output: list[dict[str, object]] = []
    for raw in rows:
        row = dict(raw)
        symbol_pct = (
            None
            if row.get("symbol_rank_pct") in ("", None)
            else safe_float(row.get("symbol_rank_pct"))
        )
        sector_pct = (
            None
            if row.get("sector_rank_pct") in ("", None)
            else safe_float(row.get("sector_rank_pct"))
        )
        hybrid_pct = (
            None
            if row.get("hybrid_rank_pct") in ("", None)
            else safe_float(row.get("hybrid_rank_pct"))
        )
        multiplier = 1.0
        blocked = False
        confidence = safe_float(row.get("confidence_hint"), 60.0)

        if policy.mode == "control":
            pass
        elif policy.mode == "symbol_soft":
            multiplier = _band_multiplier(
                symbol_pct, 0.85, 1.10, 0.85, 0.60
            )
        elif policy.mode == "sector_soft":
            multiplier = _band_multiplier(
                sector_pct, 0.85, 1.10, 0.85, 0.60
            )
        elif policy.mode == "hybrid_soft":
            if hybrid_pct is None:
                multiplier = 0.80
            elif hybrid_pct >= 0.75:
                multiplier = 1.10
            elif hybrid_pct >= 0.50:
                multiplier = 0.90
            elif hybrid_pct >= 0.25:
                multiplier = 0.70
            else:
                multiplier = 0.50
        elif policy.mode == "hybrid_priority":
            if hybrid_pct is not None:
                confidence += 20.0 * (hybrid_pct - 0.50)
        elif policy.mode == "hybrid_bottom_gate":
            blocked = hybrid_pct is not None and hybrid_pct < 0.25
            multiplier = 0.80 if hybrid_pct is None else 1.0
        else:
            raise ValueError(
                f"Unknown ranking policy mode: {policy.mode}"
            )

        row["ranking_policy"] = policy.name
        row["risk_multiplier"] = round(multiplier, 6)
        row["ranking_block"] = bool_text(blocked)
        row["confidence_hint"] = round(confidence, 6)
        reason = str(row.get("risk_plan_reason") or "")
        row["risk_plan_reason"] = (
            reason
            + f"|rank_policy={policy.name}"
            + f"|rank_state={row.get('ranking_state', 'missing')}"
            + f"|rank_risk={multiplier:.4f}"
            + f"|rank_block={bool_text(blocked)}"
        )
        output.append(row)
    return output
