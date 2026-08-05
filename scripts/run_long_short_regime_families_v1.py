#!/usr/bin/env python3
"""Strict-OOS development screen for preregistered LONG/SHORT regime families."""
from __future__ import annotations

import json
from pathlib import Path

import run_twelve_month_dual_direction_screening as engine
import run_causal_long_history_calibration_v3 as v3
from strategy_lab.causal_regime_families import POLICIES, build_regime_points, policy_decision, regime_asof
from strategy_lab.market_data import read_candles_csv, validate_candles
from strategy_lab.walk_forward_evaluation import bool_value, parse_dt


def item(name: str) -> dict[str, object]:
    return {"name": name, "threshold": "soft", "mode": name, "guard": "regime"}


VARIANTS = [item(name) for name in POLICIES]
_REGIME_POINTS = []


def threshold_spec(name: str, _mode: str) -> dict[str, object]:
    return {
        "name": name, "rolling_top_n": 8, "require_rolling_top": False,
        "require_universe_gate": False, "min_confidence": 40.0,
        "quality_take_threshold": 65.0, "quality_watch_threshold": 0.0,
        "structure_take_threshold": 64.0, "structure_watch_threshold": 0.0,
        "allowed_setup_types": (), "blocked_setup_types": ("watch_impulse",),
        "blocked_volatility_regimes": (), "blocked_liquidity_states": (),
        "blocked_candle_types": (), "allowed_direction_contexts": (),
        "min_volume_ratio": 0.0,
    }


def apply_variant_filter(run_dir: Path, validation_start, validation_end, mode: str, _guard: str) -> int:
    decisions_path = run_dir / "pipeline_decisions.csv"
    decisions, fields = v3.read_csv(decisions_path)
    blocked = 0
    for row in decisions:
        entry_time = parse_dt(row.get("entry_time"))
        if not (validation_start <= entry_time < validation_end) or not bool_value(row.get("allowed")):
            continue
        side = str(row.get("side") or "").lower()
        point = regime_asof(_REGIME_POINTS, entry_time)
        state = point.state if point is not None else "neutral"
        allowed, multiplier = policy_decision(mode, side, state)
        reason = str(row.get("reason") or "")
        if not allowed:
            row["allowed"] = "False"; row["risk_pct"] = "0"
            row["reason"] = reason + f"|regime_policy={mode}|regime_state={state}|blocked=true"
            blocked += 1
        else:
            original = float(row.get("risk_pct") or 0.0)
            row["risk_pct"] = str(round(original * multiplier, 8))
            row["reason"] = reason + f"|regime_policy={mode}|regime_state={state}|risk_multiplier={multiplier:.2f}"
    v3.write_csv(decisions_path, decisions, fields)
    return blocked


def development_gate(aggregate: dict[str, object], _sides: dict[str, dict[str, object]]) -> str:
    valid = int(aggregate.get("valid_folds", 0)); positive = int(aggregate.get("positive_folds", 0))
    trades = int(aggregate.get("total_trades", 0)); raw_pf = aggregate.get("pooled_pf", 0.0)
    pooled_pf = 10.0 if raw_pf == "inf" else float(raw_pf)
    avg_return = float(aggregate.get("avg_return_pct", 0.0)); worst_dd = float(aggregate.get("worst_dd_pct", 99.0))
    if valid == 10 and trades >= 60 and positive >= 6 and pooled_pf >= 1.20 and avg_return > 0 and worst_dd <= 8.0:
        return "PASS_DEVELOPMENT_SCREEN"
    if valid == 10 and trades >= 40 and positive >= 5 and pooled_pf >= 1.10 and avg_return > 0 and worst_dd <= 10.0:
        return "WATCH_DEVELOPMENT"
    return "BLOCK_DEVELOPMENT"


def main() -> int:
    global _REGIME_POINTS
    import sys
    args = sys.argv[1:]; candles_path = None; out_dir = None
    for idx, value in enumerate(args):
        if value == "--candles" and idx + 1 < len(args): candles_path = Path(args[idx + 1])
        if value == "--out-dir" and idx + 1 < len(args): out_dir = Path(args[idx + 1])
    if candles_path is None: raise RuntimeError("--candles is required")
    rows = read_candles_csv(candles_path); validate_candles(rows)
    btc = [row for row in rows if str(getattr(row, "symbol", "")).upper() == "BTCUSDT"]
    _REGIME_POINTS = build_regime_points(btc)
    if not _REGIME_POINTS: raise RuntimeError("no completed BTC regime points")
    engine.VARIANTS = VARIANTS; engine.threshold_spec = threshold_spec
    engine.apply_variant_filter = apply_variant_filter; engine.development_gate = development_gate
    code = engine.main()
    if out_dir:
        result_path = out_dir / "result.json"
        if result_path.exists():
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            payload.update({"mode": "LONG_SHORT_REGIME_FAMILIES_V1", "promotion_allowed": False,
                            "external_holdout_touched": False, "regime_points": len(_REGIME_POINTS)})
            result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__": raise SystemExit(main())
