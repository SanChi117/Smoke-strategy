#!/usr/bin/env python3
"""Causal 5m soft timing/risk overlay for recovered Flat v7.2 entries.

The overlay never rejects a valid 15m signal. It uses only completed 5m candles
known at the decision timestamp, then either scales risk or delays one 5m bar
for the single preregistered delay candidate.

Research only. No API keys and no order execution.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite
from statistics import mean
from typing import Iterable

from strategy_lab.flat_v72 import FlatPlan
from strategy_lab.market_data import Candle, group_candles_by_symbol


@dataclass(frozen=True)
class MicroContext:
    state: str
    supportive_points: int
    adverse_points: int
    volume_ratio: float
    ema_fast: float
    ema_slow: float
    reason: str


@dataclass(frozen=True)
class OverlaySpec:
    name: str
    risk_supportive: float = 1.0
    risk_neutral: float = 1.0
    risk_adverse: float = 1.0
    risk_missing: float = 1.0
    delay_one_5m_if_adverse: bool = False

    def risk_for(self, state: str) -> float:
        if state == "supportive":
            return self.risk_supportive
        if state == "adverse":
            return self.risk_adverse
        if state == "missing":
            return self.risk_missing
        return self.risk_neutral


SPECS = [
    OverlaySpec("FLAT72_15M_BASELINE_CONTROL"),
    OverlaySpec("SOFT_RISK_075_ON_ADVERSE", risk_adverse=0.75),
    OverlaySpec("SOFT_RISK_050_ON_ADVERSE", risk_adverse=0.50),
    OverlaySpec("SOFT_DELAY_ONE_5M_IF_ADVERSE", delay_one_5m_if_adverse=True),
    OverlaySpec(
        "SOFT_SUPPORTIVE_110_ADVERSE_060",
        risk_supportive=1.10,
        risk_neutral=0.85,
        risk_adverse=0.60,
        risk_missing=0.85,
    ),
]


def _ema_last(values: list[float], length: int) -> float:
    if len(values) < length:
        return 0.0
    current = mean(values[:length])
    alpha = 2.0 / (length + 1.0)
    for value in values[length:]:
        current = value * alpha + current * (1.0 - alpha)
    return current


def _atr_last(rows: list[Candle], length: int = 14) -> float:
    if len(rows) < length + 1:
        return 0.0
    true_ranges: list[float] = []
    previous_close: float | None = None
    for row in rows:
        if previous_close is None:
            tr = row.high - row.low
        else:
            tr = max(
                row.high - row.low,
                abs(row.high - previous_close),
                abs(row.low - previous_close),
            )
        true_ranges.append(max(0.0, tr))
        previous_close = row.close
    current = mean(true_ranges[:length])
    for value in true_ranges[length:]:
        current = (current * (length - 1) + value) / length
    return current


def _bucket_15m(value: datetime) -> datetime:
    return value.replace(minute=(value.minute // 15) * 15, second=0, microsecond=0)


def resample_complete_5m_to_15m(candles: Iterable[Candle]) -> list[Candle]:
    """Build 15m bars only from the exact 0/5/10 minute source opens."""
    output: list[Candle] = []
    for symbol, rows in group_candles_by_symbol(candles).items():
        buckets: dict[datetime, list[Candle]] = {}
        for row in sorted(rows, key=lambda item: item.time):
            buckets.setdefault(_bucket_15m(row.time), []).append(row)
        for bucket, values in sorted(buckets.items()):
            values = sorted(values, key=lambda item: item.time)
            expected = {bucket + timedelta(minutes=offset) for offset in (0, 5, 10)}
            actual = {row.time for row in values}
            if not expected.issubset(actual):
                continue
            selected = [next(row for row in values if row.time == stamp) for stamp in sorted(expected)]
            output.append(
                Candle(
                    symbol=symbol,
                    time=bucket,
                    open=selected[0].open,
                    high=max(row.high for row in selected),
                    low=min(row.low for row in selected),
                    close=selected[-1].close,
                    volume=sum(row.volume for row in selected),
                )
            )
    return sorted(output, key=lambda row: (row.symbol, row.time))


def _classify(rows: list[Candle]) -> MicroContext:
    if len(rows) < 30:
        return MicroContext("missing", 0, 0, 0.0, 0.0, 0.0, "micro_missing_history")
    window = rows[-40:]
    closes = [row.close for row in window]
    ema9 = _ema_last(closes, 9)
    ema21 = _ema_last(closes, 21)
    last = window[-1]
    prior = window[-7:-1]
    atr = _atr_last(window, 14)
    volume_avg = mean(row.volume for row in window[-20:])
    volume_ratio = last.volume / volume_avg if volume_avg > 0 else 0.0
    prior_low = min(row.low for row in prior)
    body = abs(last.close - last.open)

    supportive = 0
    adverse = 0
    supportive += int(ema9 > ema21)
    supportive += int(last.close > ema9)
    supportive += int(last.close > last.open)
    supportive += int(volume_ratio >= 0.80)
    supportive += int(last.low < prior_low and last.close > prior_low)

    adverse += int(ema9 < ema21)
    adverse += int(last.close < ema9)
    adverse += int(last.close < last.open and atr > 0 and body >= 0.55 * atr)
    adverse += int(last.close < prior_low)
    adverse += int(volume_ratio < 0.60)

    if supportive >= 3 and adverse <= 1:
        state = "supportive"
    elif adverse >= 3 and supportive <= 1:
        state = "adverse"
    else:
        state = "neutral"
    reason = (
        f"micro_state={state}|micro_support={supportive}|micro_adverse={adverse}|"
        f"micro_vr={volume_ratio:.6f}|micro_ema9={ema9:.8f}|micro_ema21={ema21:.8f}"
    )
    return MicroContext(state, supportive, adverse, volume_ratio, ema9, ema21, reason)


def classify_at(
    symbol_rows: list[Candle],
    times: list[datetime],
    decision_time: datetime,
) -> MicroContext:
    cutoff_open = decision_time - timedelta(minutes=5)
    index = bisect_right(times, cutoff_open) - 1
    if index < 0:
        return MicroContext("missing", 0, 0, 0.0, 0.0, 0.0, "micro_missing_history")
    return _classify(symbol_rows[max(0, index - 39) : index + 1])


def _delayed_plan(
    plan: FlatPlan,
    symbol_rows: list[Candle],
    times: list[datetime],
) -> tuple[FlatPlan, str]:
    start_index = bisect_right(times, plan.entry_time - timedelta(microseconds=1))
    if start_index >= len(symbol_rows):
        return plan, "delay_fallback_missing_bar"
    source = symbol_rows[start_index]
    if source.time != plan.entry_time:
        return plan, "delay_fallback_gap"
    delayed_entry_time = source.time + timedelta(minutes=5)
    delayed_entry = source.close
    risk = delayed_entry - plan.stop
    reward = plan.target - delayed_entry
    if risk <= 0 or reward <= 0:
        return plan, "delay_fallback_invalid_levels"
    return (
        replace(
            plan,
            entry_time=delayed_entry_time,
            entry=round(delayed_entry, 8),
            target_rr=round(reward / risk, 6),
            stop_pct=round(risk / delayed_entry, 8),
            reason=plan.reason + "|entry_model=delayed_one_completed_5m_close",
        ),
        "delay_applied",
    )


def _simulate_one(plan: FlatPlan, rows: list[Candle]) -> dict[str, object] | None:
    times = [row.time for row in rows]
    start = bisect_right(times, plan.entry_time - timedelta(microseconds=1))
    future = rows[start : start + plan.max_holding_bars * 3]
    if not future:
        return None
    risk = plan.entry - plan.stop
    if risk <= 0:
        return None
    exit_price = future[-1].close
    exit_time = future[-1].time + timedelta(minutes=5)
    exit_reason = "time_stop"
    bars_held = len(future)
    r_mult = (exit_price - plan.entry) / risk
    for bar_no, candle in enumerate(future, start=1):
        if candle.low <= plan.stop:
            exit_price = plan.stop
            exit_time = candle.time + timedelta(minutes=5)
            exit_reason = "stop_loss"
            bars_held = bar_no
            r_mult = -1.0
            break
        if candle.high >= plan.target:
            exit_price = plan.target
            exit_time = candle.time + timedelta(minutes=5)
            exit_reason = "take_profit"
            bars_held = bar_no
            r_mult = (plan.target - plan.entry) / risk
            break
    if not isfinite(r_mult):
        return None
    return {
        "symbol": plan.symbol,
        "side": plan.side,
        "entry_time": plan.entry_time.isoformat(timespec="seconds"),
        "exit_time": exit_time.isoformat(timespec="seconds"),
        "entry": plan.entry,
        "stop": plan.stop,
        "exit": round(exit_price, 8),
        "r_mult": round(r_mult, 6),
        "source": "flat_v72_5m_soft_overlay",
        "kind": "flat_v72",
        "setup_type": "flat_v72",
        "trend_context": "trend",
        "volatility_regime": plan.volatility_regime,
        "structure_type": "flat_v72_range",
        "confidence_hint": plan.confidence_hint,
        "target_policy": plan.target_policy,
        "risk_grade": "B",
        "exit_reason": exit_reason,
        "bars_held": bars_held,
        "risk_plan_reason": plan.reason,
        "target_rr": round((plan.target - plan.entry) / risk, 6),
        "stop_pct": plan.stop_pct,
        "candle_type": plan.candle_type,
        "context_alignment": "aligned",
        "liquidity_state": "none",
        "volume_ratio": plan.volume_ratio,
        "range_width_pct": plan.range_width_pct,
    }


def build_overlay_rows(
    plans: Iterable[FlatPlan],
    micro_candles: Iterable[Candle],
    spec: OverlaySpec,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    grouped = group_candles_by_symbol(micro_candles)
    times_by_symbol = {symbol: [row.time for row in rows] for symbol, rows in grouped.items()}
    counts: Counter[str] = Counter()
    output: list[dict[str, object]] = []
    for original in plans:
        rows = grouped.get(original.symbol, [])
        times = times_by_symbol.get(original.symbol, [])
        context = classify_at(rows, times, original.entry_time)
        adjusted = original
        delay_status = "delay_not_requested"
        if spec.delay_one_5m_if_adverse and context.state == "adverse":
            adjusted, delay_status = _delayed_plan(original, rows, times)
        risk_multiplier = spec.risk_for(context.state)
        adjusted = replace(
            adjusted,
            reason=(
                adjusted.reason
                + f"|overlay={spec.name}|{context.reason}|risk_multiplier={risk_multiplier:.4f}|"
                + delay_status
            ),
        )
        row = _simulate_one(adjusted, rows)
        if row is None:
            counts["simulation_missing"] += 1
            continue
        row["micro_state"] = context.state
        row["micro_supportive_points"] = context.supportive_points
        row["micro_adverse_points"] = context.adverse_points
        row["micro_volume_ratio"] = round(context.volume_ratio, 6)
        row["risk_multiplier"] = risk_multiplier
        row["delay_status"] = delay_status
        output.append(row)
        counts[context.state] += 1
        counts[delay_status] += 1
    output.sort(key=lambda row: (str(row["entry_time"]), str(row["symbol"])))
    return output, {
        "candidate": spec.name,
        "generated_trades": len(output),
        "counts": dict(sorted(counts.items())),
    }
