#!/usr/bin/env python3
"""Recheck historical SMOKE setup families with the current causal engine.

This compact adapter reuses the optimized twelve-month runner. Quality/Structure are
computed once for each threshold mode and fold; all historical setup variants then
reuse identical causal decisions and raw outcomes.

Research only. No API keys and no order execution.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import run_twelve_month_dual_direction_screening as engine
import run_causal_long_history_calibration_v3 as v3
from strategy_lab.config import PipelineConfig
from strategy_lab.rolling_symbol_strength import CostConfig, RollingConfig, build_rolling_trades, load_trades_csv
from strategy_lab.walk_forward_evaluation import bool_value, parse_dt, reason_values, trade_key

PULLBACK = ("pullback", "pullback_resumption", "pullback_resumption_strict")
TREND = ("breakout", "pullback", "pullback_resumption", "pullback_resumption_strict", "ignition")
REVERSAL = ("range_rotation", "liquidity_reclaim")
ALL = TREND + REVERSAL


def item(name, threshold, setups, min_volume=0.45, blocked_vol=(), rolling_top_n=0):
    return {
        "name": name,
        "threshold": threshold,
        "mode": name,
        "guard": "historical",
        "setups": setups,
        "min_volume": min_volume,
        "blocked_vol": blocked_vol,
        "rolling_top_n": rolling_top_n,
    }


VARIANTS = [
    item("HIST_HARD_PULLBACK_CONTROL", "hard", PULLBACK, 0.50, ("high",)),
    item("HIST_HARD_REGIME_ROUTER_ALL", "hard", ALL),
    item("HIST_SOFT_REGIME_ROUTER_ALL", "soft", ALL),
    item("HIST_SOFT_REGIME_ROUTER_ROLL5", "soft", ALL, rolling_top_n=5),
    item("HIST_SOFT_REGIME_ROUTER_ROLL8", "soft", ALL, rolling_top_n=8),
    item("HIST_SOFT_PULLBACK_FAMILY", "soft", PULLBACK, 0.50, ("high",)),
    item("HIST_SOFT_BREAKOUT", "soft", ("breakout",), 0.50),
    item("HIST_SOFT_IGNITION", "soft", ("ignition",), 0.50),
    item("HIST_SOFT_RANGE_ROTATION", "soft", ("range_rotation",), 0.45, ("high",)),
    item("HIST_SOFT_LIQUIDITY_RECLAIM", "soft", ("liquidity_reclaim",), 0.45),
    item("HIST_SOFT_TREND_ROUTER", "soft", TREND, 0.50),
    item("HIST_SOFT_REVERSAL_ROUTER", "soft", REVERSAL, 0.45),
]
BY_NAME = {str(row["name"]): row for row in VARIANTS}


def threshold_spec(name: str, mode: str) -> dict[str, object]:
    if mode == "hard":
        q_take, q_watch, s_take, s_watch = 61.0, 48.0, 60.0, 48.0
    elif mode == "soft":
        q_take, q_watch, s_take, s_watch = 65.0, 0.0, 64.0, 0.0
    else:
        raise ValueError(f"unknown threshold mode: {mode}")
    return {
        "name": name,
        "rolling_top_n": 8,
        "require_rolling_top": False,
        "require_universe_gate": False,
        "min_confidence": 40.0,
        "quality_take_threshold": q_take,
        "quality_watch_threshold": q_watch,
        "structure_take_threshold": s_take,
        "structure_watch_threshold": s_watch,
        "allowed_setup_types": (),
        "blocked_setup_types": ("watch_impulse",),
        "blocked_volatility_regimes": (),
        "blocked_liquidity_states": (),
        "blocked_candle_types": (),
        "allowed_direction_contexts": (),
        "min_volume_ratio": 0.0,
    }


def rolling_keys(path: Path, start, end, top_n: int):
    if top_n <= 0:
        return set()
    cfg = PipelineConfig()
    selected, _windows, _average = build_rolling_trades(
        load_trades_csv(path),
        start,
        end,
        RollingConfig(cfg.rolling_lookback_days, cfg.rolling_rebalance_days, top_n),
        CostConfig(fee_rate=cfg.fee_rate, slippage_rate=cfg.slippage_rate),
    )
    return {trade_key(row.symbol, row.side, row.entry_time) for row in selected}


def apply_variant_filter(run_dir: Path, validation_start, validation_end, mode: str, _guard: str) -> int:
    spec = BY_NAME[mode]
    decisions_path = run_dir / "pipeline_decisions.csv"
    generated_path = run_dir / "generated_trades.csv"
    decisions, fields = v3.read_csv(decisions_path)
    generated, _ = v3.read_csv(generated_path)
    by_key = {
        trade_key(row.get("symbol"), row.get("side"), row.get("entry_time")): row
        for row in generated
    }
    allowed = {str(value).lower() for value in spec["setups"]}
    blocked_vol = {str(value).lower() for value in spec["blocked_vol"]}
    top_n = int(spec["rolling_top_n"])
    selected_rolling = rolling_keys(generated_path, validation_start, validation_end, top_n)
    blocked = 0

    for row in decisions:
        entry_time = parse_dt(row.get("entry_time"))
        if not (validation_start <= entry_time < validation_end) or not bool_value(row.get("allowed")):
            continue
        key = trade_key(row.get("symbol"), row.get("side"), row.get("entry_time"))
        source = by_key.get(key, {})
        setup = str(source.get("setup_type") or row.get("setup_type") or "unknown").lower()
        volatility = str(source.get("volatility_regime") or row.get("volatility_regime") or "unknown").lower()
        meta = reason_values(source.get("risk_plan_reason") or source.get("reason"))
        try:
            volume = float(meta.get("vr", 0.0))
        except (TypeError, ValueError):
            volume = 0.0

        reason = ""
        if setup not in allowed:
            reason = "historical_setup_family_filtered"
        elif volatility in blocked_vol:
            reason = "historical_volatility_filtered"
        elif volume < float(spec["min_volume"]):
            reason = "historical_volume_filtered"
        elif top_n and key not in selected_rolling:
            reason = f"historical_not_in_rolling_top_{top_n}"
        if reason:
            row["allowed"] = "False"
            row["risk_pct"] = "0"
            row["reason"] = reason
            blocked += 1

    v3.write_csv(decisions_path, decisions, fields)
    return blocked


def development_gate(aggregate: dict[str, object], _sides: dict[str, dict[str, object]]) -> str:
    valid = int(aggregate.get("valid_folds", 0))
    positive = int(aggregate.get("positive_folds", 0))
    trades = int(aggregate.get("total_trades", 0))
    raw_pf = aggregate.get("pooled_pf", 0.0)
    pooled_pf = 10.0 if raw_pf == "inf" else float(raw_pf)
    avg_return = float(aggregate.get("avg_return_pct", 0.0))
    worst_fold = float(aggregate.get("worst_fold_return_pct", 0.0))
    worst_dd = float(aggregate.get("worst_dd_pct", 99.0))
    if (
        trades >= 60 and positive >= math.ceil(valid * 0.75)
        and pooled_pf >= 1.20 and avg_return > 0
        and worst_fold > -2.5 and worst_dd <= 8.0
    ):
        return "PASS_DEVELOPMENT_SCREEN"
    if (
        trades >= 30 and positive >= math.ceil(valid * 0.50)
        and pooled_pf >= 1.05 and avg_return > 0 and worst_dd <= 10.0
    ):
        return "WATCH_DEVELOPMENT"
    return "BLOCK_DEVELOPMENT"


def main() -> int:
    engine.VARIANTS = VARIANTS
    engine.threshold_spec = threshold_spec
    engine.apply_variant_filter = apply_variant_filter
    engine.development_gate = development_gate
    code = engine.main()

    # Mark the output explicitly as a retrospective screen, not a promotable baseline.
    import sys
    args = sys.argv[1:]
    out_dir = None
    for index, value in enumerate(args):
        if value == "--out-dir" and index + 1 < len(args):
            out_dir = Path(args[index + 1])
    if out_dir:
        result_path = out_dir / "result.json"
        if result_path.exists():
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            payload["mode"] = "SMOKE_HISTORICAL_HYPOTHESIS_RECHECK_V1"
            payload["promotion_allowed"] = False
            payload["limitations"] = [
                "Dynamic targets require a separate exit simulation.",
                "Flat v7.2, 5m timing, sector ranking and SMC components are scheduled for later waves.",
                "Any leader still requires a frozen external holdout."
            ]
            result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
