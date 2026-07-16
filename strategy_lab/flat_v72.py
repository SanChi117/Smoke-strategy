#!/usr/bin/env python3
"""Causal research port of the recovered Flat v7.2 Pine strategy.

The original complete Pine source was not found. This module preserves every
recovered rule and exposes unresolved coefficients as explicit research
parameters instead of silently claiming an exact reconstruction.

Research only. Closed candles only. No API keys and no order execution.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import timedelta
from math import isfinite
from statistics import mean
from typing import Iterable

from strategy_lab.closed_context import resample_closed_candles
from strategy_lab.market_data import Candle, group_candles_by_symbol


@dataclass(frozen=True)
class FlatV72Config:
    name: str
    range_length: int = 50
    atr_length: int = 14
    atr_touch_buffer: float = 0.30
    center_ban_low: float = 0.33
    min_range_width_pct: float = 2.0
    volume_length: int = 20
    narrow_width_pct: float = 3.0
    wide_width_pct: float = 5.0
    narrow_volume_multiplier: float = 1.60
    default_volume_multiplier: float = 1.80
    wide_volume_multiplier: float = 2.00
    dynamic_volume: bool = True
    fixed_volume_multiplier: float = 1.80
    use_60m_trend_filter: bool = True
    use_15m_ema200_filter: bool = True
    fractal_lookback: int = 7
    normal_stop_atr: float = 0.45
    wide_stop_atr: float = 0.65
    swing_lookback: int = 30
    target_atr_buffer: float = 0.40
    minimum_rr: float = 1.70
    weak_rr_cap: float = 2.20
    strong_rr_cap: float = 2.80
    use_dynamic_rr_cap: bool = True
    use_structural_target: bool = True
    fixed_target_rr: float = 1.70
    strong_body_atr: float = 0.60
    strong_volume_ratio: float = 2.00
    cooldown_bars: int = 4
    max_holding_bars: int = 96


@dataclass(frozen=True)
class FlatPlan:
    symbol: str
    side: str
    entry_time: object
    entry: float
    stop: float
    target: float
    target_rr: float
    stop_pct: float
    confidence_hint: float
    volatility_regime: str
    candle_type: str
    volume_ratio: float
    range_width_pct: float
    target_policy: str
    reason: str
    max_holding_bars: int


def _ema(values: list[float], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if length <= 0 or len(values) < length:
        return out
    seed = mean(values[:length])
    out[length - 1] = seed
    alpha = 2.0 / (length + 1.0)
    current = seed
    for index in range(length, len(values)):
        current = values[index] * alpha + current * (1.0 - alpha)
        out[index] = current
    return out


def _rma(values: list[float], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if length <= 0 or len(values) < length:
        return out
    current = mean(values[:length])
    out[length - 1] = current
    for index in range(length, len(values)):
        current = (current * (length - 1) + values[index]) / length
        out[index] = current
    return out


def _atr(rows: list[Candle], length: int) -> list[float | None]:
    tr: list[float] = []
    previous_close: float | None = None
    for candle in rows:
        if previous_close is None:
            value = candle.high - candle.low
        else:
            value = max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        tr.append(max(0.0, value))
        previous_close = candle.close
    return _rma(tr, length)


def _sma(values: list[float], length: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if length <= 0:
        return out
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= length:
            running -= values[index - length]
        if index >= length - 1:
            out[index] = running / length
    return out


def _candle_type(candle: Candle, atr: float) -> str:
    body = abs(candle.close - candle.open)
    if atr > 0 and body >= 0.60 * atr:
        return "bull_impulse" if candle.close > candle.open else "bear_impulse"
    if candle.close > candle.open:
        return "bull_rejection"
    if candle.close < candle.open:
        return "bear_rejection"
    return "neutral"


def _volatility_regime(atr: float, close: float) -> str:
    atr_pct = atr / close if close > 0 else 0.0
    if atr_pct >= 0.015:
        return "high"
    if atr_pct <= 0.005:
        return "low"
    return "normal"


def _volume_threshold(width_pct: float, cfg: FlatV72Config) -> float:
    if not cfg.dynamic_volume:
        return cfg.fixed_volume_multiplier
    if width_pct < cfg.narrow_width_pct:
        return cfg.narrow_volume_multiplier
    if width_pct >= cfg.wide_width_pct:
        return cfg.wide_volume_multiplier
    return cfg.default_volume_multiplier


def _closed_60m_ema_map(rows: list[Candle]) -> dict[object, tuple[float | None, float | None]]:
    hourly = resample_closed_candles(rows, 1)
    closes = [row.close for row in hourly]
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200)
    return {row.time: (ema50[index], ema200[index]) for index, row in enumerate(hourly)}


def generate_flat_v72_plans(
    candles: Iterable[Candle],
    cfg: FlatV72Config,
) -> tuple[list[FlatPlan], dict[str, object]]:
    """Generate long-only Flat v7.2 plans from information known at each bar close."""
    plans: list[FlatPlan] = []
    reasons: Counter[str] = Counter()
    symbols_seen = 0

    for symbol, rows in group_candles_by_symbol(candles).items():
        rows = sorted(rows, key=lambda row: row.time)
        if len(rows) < 900:
            reasons["insufficient_symbol_history"] += 1
            continue
        symbols_seen += 1
        closes = [row.close for row in rows]
        volumes = [row.volume for row in rows]
        ema200_15m = _ema(closes, 200)
        atr_values = _atr(rows, cfg.atr_length)
        volume_sma = _sma(volumes, cfg.volume_length)
        hourly_map = _closed_60m_ema_map(rows)
        hourly_times = sorted(hourly_map)
        hourly_index = -1
        latest_hourly: tuple[float | None, float | None] = (None, None)
        last_entry_index = -10**9

        warmup = max(
            cfg.range_length - 1,
            cfg.atr_length - 1,
            cfg.volume_length - 1,
            199 if cfg.use_15m_ema200_filter else 0,
            cfg.fractal_lookback - 1,
            cfg.swing_lookback - 1,
        )
        for index in range(warmup, len(rows)):
            candle = rows[index]
            while hourly_index + 1 < len(hourly_times) and hourly_times[hourly_index + 1] <= candle.time:
                hourly_index += 1
                latest_hourly = hourly_map[hourly_times[hourly_index]]

            atr = atr_values[index]
            vol_avg = volume_sma[index]
            if atr is None or atr <= 0 or vol_avg is None or vol_avg <= 0:
                reasons["indicator_warmup"] += 1
                continue
            if index + cfg.max_holding_bars >= len(rows):
                reasons["insufficient_future_bars"] += 1
                continue

            range_rows = rows[index - cfg.range_length + 1 : index + 1]
            dc_low = min(row.low for row in range_rows)
            dc_high = max(row.high for row in range_rows)
            if dc_low <= 0 or dc_high <= dc_low:
                reasons["invalid_range"] += 1
                continue
            width_pct = (dc_high - dc_low) / dc_low * 100.0
            if width_pct < cfg.min_range_width_pct:
                reasons["range_too_narrow"] += 1
                continue

            normalized = (candle.close - dc_low) / (dc_high - dc_low)
            if normalized > cfg.center_ban_low:
                reasons["center_ban"] += 1
                continue
            if candle.low > dc_low + atr * cfg.atr_touch_buffer:
                reasons["no_lower_boundary_touch"] += 1
                continue

            ema15 = ema200_15m[index]
            if cfg.use_15m_ema200_filter and (ema15 is None or candle.close <= ema15):
                reasons["below_15m_ema200"] += 1
                continue
            h50, h200 = latest_hourly
            if cfg.use_60m_trend_filter and (h50 is None or h200 is None or h50 <= h200):
                reasons["60m_trend_filter"] += 1
                continue

            volume_ratio = candle.volume / vol_avg
            required_volume = _volume_threshold(width_pct, cfg)
            if volume_ratio < required_volume:
                reasons["volume_filter"] += 1
                continue
            if index - last_entry_index < cfg.cooldown_bars:
                reasons["cooldown"] += 1
                continue

            fractal_rows = rows[index - cfg.fractal_lookback + 1 : index + 1]
            zone_low = min(dc_low, min(row.low for row in fractal_rows))
            stop_atr = cfg.wide_stop_atr if width_pct >= cfg.wide_width_pct else cfg.normal_stop_atr
            stop = zone_low - atr * stop_atr
            entry = candle.close
            risk = entry - stop
            if risk <= 0:
                reasons["invalid_stop"] += 1
                continue

            swing_rows = rows[index - cfg.swing_lookback + 1 : index + 1]
            structural_target = max(row.high for row in swing_rows) - atr * cfg.target_atr_buffer
            raw_rr = (structural_target - entry) / risk
            if cfg.use_structural_target and raw_rr < cfg.minimum_rr:
                reasons["minimum_rr"] += 1
                continue

            strong = (
                candle.close > candle.open
                and abs(candle.close - candle.open) >= atr * cfg.strong_body_atr
                and volume_ratio >= cfg.strong_volume_ratio
            )
            rr_cap = cfg.strong_rr_cap if cfg.use_dynamic_rr_cap and strong else cfg.weak_rr_cap
            if cfg.use_structural_target:
                target_rr = min(raw_rr, rr_cap)
                target = entry + risk * target_rr
                target_policy = "flat_structural_swing_cap"
            else:
                target_rr = cfg.fixed_target_rr
                target = entry + risk * target_rr
                target_policy = "flat_fixed_rr"
            if target_rr < cfg.minimum_rr or target <= entry:
                reasons["invalid_target"] += 1
                continue

            candle_type = _candle_type(candle, atr)
            volatility = _volatility_regime(atr, candle.close)
            stop_pct = risk / entry
            entry_time = candle.time + timedelta(minutes=15)
            reason = (
                f"flat_v72|dir=up|ctx_align=aligned|candle={candle_type}|liq=none|"
                f"vr={volume_ratio:.6f}|range_width={width_pct:.6f}|"
                f"volume_req={required_volume:.4f}|atr={atr:.8f}|"
                f"rr_raw={raw_rr:.6f}|rr_cap={rr_cap:.4f}|strong={str(strong).lower()}"
            )
            plans.append(
                FlatPlan(
                    symbol=symbol,
                    side="long",
                    entry_time=entry_time,
                    entry=round(entry, 8),
                    stop=round(stop, 8),
                    target=round(target, 8),
                    target_rr=round(target_rr, 6),
                    stop_pct=round(stop_pct, 8),
                    confidence_hint=60.0,
                    volatility_regime=volatility,
                    candle_type=candle_type,
                    volume_ratio=round(volume_ratio, 6),
                    range_width_pct=round(width_pct, 6),
                    target_policy=target_policy,
                    reason=reason,
                    max_holding_bars=cfg.max_holding_bars,
                )
            )
            last_entry_index = index
            reasons["plan_created"] += 1

    plans.sort(key=lambda plan: (plan.entry_time, plan.symbol))
    return plans, {
        "variant": cfg.name,
        "symbols_seen": symbols_seen,
        "plans": len(plans),
        "reason_counts": dict(sorted(reasons.items())),
        "explicit_research_assumptions": {
            "narrow_width_pct": cfg.narrow_width_pct,
            "wide_width_pct": cfg.wide_width_pct,
            "fractal_lookback": cfg.fractal_lookback,
            "normal_stop_atr": cfg.normal_stop_atr,
            "wide_stop_atr": cfg.wide_stop_atr,
            "strong_body_atr": cfg.strong_body_atr,
            "strong_volume_ratio": cfg.strong_volume_ratio,
            "max_holding_bars": cfg.max_holding_bars,
        },
    }


def simulate_flat_v72_rows(
    plans: Iterable[FlatPlan],
    candles: Iterable[Candle],
) -> list[dict[str, object]]:
    """Simulate exits after the signal bar; same-bar stop/target ambiguity is stop-first."""
    grouped = group_candles_by_symbol(candles)
    output: list[dict[str, object]] = []
    for plan in plans:
        symbol_rows = grouped.get(plan.symbol, [])
        future = [row for row in symbol_rows if row.time >= plan.entry_time][: plan.max_holding_bars]
        if not future:
            continue
        exit_price = plan.entry
        exit_time = future[-1].time + timedelta(minutes=15)
        exit_reason = "time_stop"
        bars_held = len(future)
        r_mult = 0.0
        risk = plan.entry - plan.stop
        for bar_no, candle in enumerate(future, start=1):
            if candle.low <= plan.stop:
                exit_price = plan.stop
                exit_time = candle.time + timedelta(minutes=15)
                exit_reason = "stop_loss"
                bars_held = bar_no
                r_mult = -1.0
                break
            if candle.high >= plan.target:
                exit_price = plan.target
                exit_time = candle.time + timedelta(minutes=15)
                exit_reason = "take_profit"
                bars_held = bar_no
                r_mult = plan.target_rr
                break
        else:
            exit_price = future[-1].close
            r_mult = (exit_price - plan.entry) / risk if risk > 0 else 0.0

        if not isfinite(r_mult):
            continue
        row = {
            "symbol": plan.symbol,
            "side": plan.side,
            "entry_time": plan.entry_time.isoformat(timespec="seconds"),
            "exit_time": exit_time.isoformat(timespec="seconds"),
            "entry": plan.entry,
            "stop": plan.stop,
            "exit": round(exit_price, 8),
            "r_mult": round(r_mult, 6),
            "source": "flat_v72_causal_port",
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
            "target_rr": plan.target_rr,
            "stop_pct": plan.stop_pct,
            "candle_type": plan.candle_type,
            "context_alignment": "aligned",
            "liquidity_state": "none",
            "volume_ratio": plan.volume_ratio,
            "range_width_pct": plan.range_width_pct,
        }
        output.append(row)
    output.sort(key=lambda row: (str(row["entry_time"]), str(row["symbol"])))
    return output


def config_as_dict(cfg: FlatV72Config) -> dict[str, object]:
    return asdict(cfg)
