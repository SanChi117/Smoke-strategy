#!/usr/bin/env python3
"""Strict-OOS development screen for preregistered causal Cleanshot/SMC features."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import run_twelve_month_dual_direction_screening as screening
import run_causal_long_history_calibration_v3 as v3
from strategy_lab.causal_smc_features import POLICIES, SmcFeatureEngine, policy_decision
from strategy_lab.market_data import read_candles_csv, validate_candles
from strategy_lab.walk_forward_evaluation import bool_value, parse_dt


_SMC_ENGINE: SmcFeatureEngine | None = None
_FEATURE_COUNTS: dict[str, Counter[str]] = defaultdict(Counter)


def item(name: str) -> dict[str, object]:
    return {"name": name, "threshold": "smc", "mode": name, "guard": "causal_smc"}


VARIANTS = [item(name) for name in POLICIES]


def threshold_spec(name: str, _mode: str) -> dict[str, object]:
    # Broad causal shadow pool; the preregistered SMC chain performs the actual
    # selection. Outcome-derived rolling gates and manual universe gates are off.
    return {
        "name": name,
        "rolling_top_n": 8,
        "require_rolling_top": False,
        "require_universe_gate": False,
        "min_confidence": 40.0,
        "quality_take_threshold": 65.0,
        "quality_watch_threshold": 0.0,
        "structure_take_threshold": 64.0,
        "structure_watch_threshold": 0.0,
        "allowed_setup_types": (),
        "blocked_setup_types": ("watch_impulse",),
        "blocked_volatility_regimes": (),
        "blocked_liquidity_states": (),
        "blocked_candle_types": (),
        "allowed_direction_contexts": (),
        "min_volume_ratio": 0.0,
    }


def _feature_reason(feature) -> str:
    pd = "na" if feature.dealing_range_position is None else f"{feature.dealing_range_position:.4f}"
    return (
        f"smc_state={feature.state}|smc_score={feature.score}|h4_bias={feature.h4_bias}"
        f"|pd={pd}|pd_match={str(feature.premium_discount_match).lower()}"
        f"|poi={str(feature.h4_poi).lower()}|raid={str(feature.h1_liquidity_raid).lower()}"
        f"|bos={str(feature.m15_bos).lower()}|disp={str(feature.m15_displacement).lower()}"
        f"|imb={str(feature.m15_imbalance).lower()}|idm={str(feature.m15_idm).lower()}"
        f"|vc={str(feature.volume_confirmation).lower()}"
    )


def apply_variant_filter(run_dir: Path, validation_start, validation_end, mode: str, _guard: str) -> int:
    if _SMC_ENGINE is None:
        raise RuntimeError("SMC feature engine is not initialized")
    decisions_path = run_dir / "pipeline_decisions.csv"
    decisions, fields = v3.read_csv(decisions_path)
    blocked = 0
    counts = _FEATURE_COUNTS[mode]
    for row in decisions:
        entry_time = parse_dt(row.get("entry_time"))
        if not (validation_start <= entry_time < validation_end) or not bool_value(row.get("allowed")):
            continue
        symbol = str(row.get("symbol") or "").upper()
        side = str(row.get("side") or "").lower()
        feature = _SMC_ENGINE.evaluate(symbol, entry_time, side)
        counts["evaluated"] += 1
        counts[f"state_{feature.state}"] += 1
        counts[f"score_{feature.score}"] += 1
        for name, value in (
            ("bias_match", feature.bias_match),
            ("pd_match", feature.premium_discount_match),
            ("poi", feature.h4_poi),
            ("raid", feature.h1_liquidity_raid),
            ("bos", feature.m15_bos),
            ("displacement", feature.m15_displacement),
            ("imbalance", feature.m15_imbalance),
            ("idm", feature.m15_idm),
            ("volume_confirmation", feature.volume_confirmation),
        ):
            if value:
                counts[name] += 1

        allowed, multiplier = policy_decision(mode, feature)
        reason = str(row.get("reason") or "")
        detail = _feature_reason(feature)
        if not allowed:
            row["allowed"] = "False"
            row["risk_pct"] = "0"
            row["reason"] = reason + f"|smc_policy={mode}|{detail}|smc_blocked=true"
            blocked += 1
            counts["blocked"] += 1
        else:
            original = float(row.get("risk_pct") or 0.0)
            row["risk_pct"] = str(round(original * multiplier, 8))
            row["reason"] = (
                reason
                + f"|smc_policy={mode}|{detail}|smc_blocked=false"
                + f"|smc_risk_multiplier={multiplier:.2f}"
            )
            counts["allowed"] += 1
    v3.write_csv(decisions_path, decisions, fields)
    return blocked


def development_gate(aggregate: dict[str, object], _sides: dict[str, dict[str, object]]) -> str:
    raw_pf = aggregate.get("pooled_pf", 0.0)
    pooled_pf = 10.0 if raw_pf == "inf" else float(raw_pf)
    valid = int(aggregate.get("valid_folds", 0))
    positive = int(aggregate.get("positive_folds", 0))
    trades = int(aggregate.get("total_trades", 0))
    average_return = float(aggregate.get("avg_return_pct", 0.0))
    worst_dd = float(aggregate.get("worst_dd_pct", 99.0))
    if (
        valid == 10
        and trades >= 60
        and positive >= 6
        and pooled_pf >= 1.20
        and average_return > 0.0
        and worst_dd <= 8.0
    ):
        return "PASS_DEVELOPMENT_SCREEN"
    if (
        valid == 10
        and trades >= 40
        and positive >= 5
        and pooled_pf >= 1.10
        and average_return > 0.0
        and worst_dd <= 10.0
    ):
        return "WATCH_DEVELOPMENT"
    return "BLOCK_DEVELOPMENT"


def main() -> int:
    global _SMC_ENGINE
    import sys

    args = sys.argv[1:]
    candles_path: Path | None = None
    out_dir: Path | None = None
    for index, value in enumerate(args):
        if value == "--candles" and index + 1 < len(args):
            candles_path = Path(args[index + 1])
        if value == "--out-dir" and index + 1 < len(args):
            out_dir = Path(args[index + 1])
    if candles_path is None:
        raise RuntimeError("--candles is required")

    candles = read_candles_csv(candles_path)
    validate_candles(candles)
    if not candles:
        raise RuntimeError("SMC development candle source is empty")
    _SMC_ENGINE = SmcFeatureEngine(candles)

    screening.VARIANTS = VARIANTS
    screening.threshold_spec = threshold_spec
    screening.apply_variant_filter = apply_variant_filter
    screening.development_gate = development_gate
    code = screening.main()

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        counts_payload = {
            policy: dict(sorted(counter.items()))
            for policy, counter in sorted(_FEATURE_COUNTS.items())
        }
        (out_dir / "feature_counts.json").write_text(
            json.dumps(counts_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        result_path = out_dir / "result.json"
        if result_path.exists():
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            payload.update(
                {
                    "mode": "CAUSAL_CLEANSHOT_SMC_FEATURES_V1",
                    "promotion_allowed": False,
                    "external_holdout_touched": False,
                    "formalization_scope": [
                        "4h structural bias",
                        "4h premium/discount dealing range",
                        "4h imbalance or displacement-origin POI proxy",
                        "1h liquidity raid",
                        "15m BOS",
                        "15m displacement",
                        "15m imbalance",
                        "15m inducement proxy",
                    ],
                    "feature_counts": counts_payload,
                    "limitations": [
                        "Deterministic causal proxy; not exact equivalence to discretionary manual execution.",
                        "No order-book, open-interest, funding or liquidation-map data are used.",
                        "Development data are already exposed and cannot become an external holdout.",
                        "No coefficients or variants may be changed after viewing this result.",
                    ],
                    "next_required_step": (
                        "If exactly one candidate passes, freeze it and run one untouched external holdout. "
                        "If all block, the preregistered research ladder is exhausted without robust edge."
                    ),
                }
            )
            result_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
