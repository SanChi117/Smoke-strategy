#!/usr/bin/env python3
"""Long-history strict-OOS sweep with one candidate pool per fold.

The expensive candle -> feature -> setup -> risk -> exit chain is executed once
per chronological fold. Strategy variants then reuse the same generated trade
pool, so they are compared on identical market data and identical raw outcomes.

Research only. Public Binance Futures candles only. No API keys. No orders.
"""

from __future__ import annotations

import argparse
import csv
import gc
import json
import sys
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_binance_walk_forward as wfo  # noqa: E402
from run_binance_real_research import DEFAULT_SYMBOLS, resolve_symbols  # noqa: E402
from strategy_lab.binance_market_data import load_binance_futures_candles  # noqa: E402
from strategy_lab.candle_exit_simulator import simulate_plan_exits  # noqa: E402
from strategy_lab.candle_pipeline import trade_rows_from_plans  # noqa: E402
from strategy_lab.config import PipelineConfig  # noqa: E402
from strategy_lab.feature_builder import build_features  # noqa: E402
from strategy_lab.market_data import read_candles_csv, validate_candles  # noqa: E402
from strategy_lab.pipeline import run_pipeline  # noqa: E402
from strategy_lab.risk_model import build_risk_plans  # noqa: E402
from strategy_lab.setup_generator import generate_candidate_setups  # noqa: E402
from strategy_lab.walk_forward_evaluation import evaluate_validation_window  # noqa: E402


PULLBACK_FAMILY = ("pullback", "pullback_resumption", "pullback_resumption_strict")


def common(name: str, **overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "name": name,
        "rolling_top_n": 8,
        "require_rolling_top": False,
        "require_universe_gate": False,
        "min_confidence": 45.0,
        "quality_take_threshold": 64.0,
        "quality_watch_threshold": 52.0,
        "structure_take_threshold": 63.0,
        "structure_watch_threshold": 52.0,
        "allowed_setup_types": ("pullback_resumption",),
        "blocked_setup_types": ("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim", "ignition", "pullback_resumption_strict", "pullback"),
        "blocked_volatility_regimes": ("high",),
        "blocked_liquidity_states": ("high_sweep_reject",),
        "blocked_candle_types": ("bear_rejection",),
        "allowed_direction_contexts": ("down",),
        "min_volume_ratio": 0.65,
    }
    item.update(overrides)
    return item


CANDIDATES = [
    common(
        "LONGHIST_PULLBACK_SHORT_CONTROL_V1",
        min_confidence=43.0,
        allowed_setup_types=PULLBACK_FAMILY,
        blocked_setup_types=("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim", "ignition"),
        min_volume_ratio=0.70,
    ),
    common("LONGHIST_RESUMPTION_BALANCED_V1"),
    common(
        "LONGHIST_RESUMPTION_HTF_V1",
        allowed_context_alignments=("aligned", "h4_only"),
    ),
    common(
        "LONGHIST_RESUMPTION_NEUTRAL_V1",
        allowed_candle_types=("neutral", "indecision"),
    ),
    common(
        "LONGHIST_RESUMPTION_VR09_V1",
        min_volume_ratio=0.90,
    ),
    common(
        "LONGHIST_RESUMPTION_HTF_VR09_V1",
        allowed_context_alignments=("aligned", "h4_only"),
        min_volume_ratio=0.90,
    ),
]


FILTER_KEYS = (
    "allowed_symbols", "blocked_symbols", "allowed_setup_types", "blocked_setup_types",
    "allowed_trend_contexts", "blocked_trend_contexts",
    "allowed_volatility_regimes", "blocked_volatility_regimes",
    "allowed_liquidity_states", "blocked_liquidity_states",
    "allowed_candle_types", "blocked_candle_types",
    "allowed_direction_contexts", "blocked_direction_contexts",
    "allowed_context_alignments", "blocked_context_alignments",
)


def parse_dt(value: object) -> datetime:
    return datetime.fromisoformat(str(value).strip().replace("Z", ""))


def read_csv(path: str | Path) -> tuple[list[dict[str, str]], list[str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: str | Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    names = fields or (list(rows[0].keys()) if rows else [])
    if not names:
        target.write_text("", encoding="utf-8")
        return
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def generate_trade_pool(candles_csv: Path, out_csv: Path, min_confidence: float) -> dict[str, object]:
    candles = read_candles_csv(candles_csv)
    validate_candles(candles)
    features = build_features(candles)
    candidates = generate_candidate_setups(features, min_confidence=min_confidence)
    plans = build_risk_plans(candidates)
    exits = simulate_plan_exits(plans, candles)
    rows = trade_rows_from_plans(plans, exits)
    write_csv(out_csv, rows)
    summary = {
        "candles": len(candles),
        "features": len(features),
        "candidates": len(candidates),
        "generated_trades": len(rows),
        "setups": dict(sorted(Counter(str(row.get("setup_type", "unknown")) for row in rows).items())),
    }
    del candles, features, candidates, plans, exits, rows
    gc.collect()
    return summary


def filtered_pool(rows: list[dict[str, str]], min_confidence: float) -> list[dict[str, str]]:
    out = []
    for row in rows:
        try:
            confidence = float(row.get("confidence_hint") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence >= min_confidence:
            out.append(row)
    return out


def config_for(spec: dict[str, object], warmup_start: datetime, validation_end: datetime) -> PipelineConfig:
    kwargs = {key: tuple(str(value) for value in spec.get(key, ())) for key in FILTER_KEYS}
    return replace(
        PipelineConfig(),
        name=str(spec["name"]),
        start=warmup_start.date().isoformat(),
        end=(validation_end + timedelta(days=1)).date().isoformat(),
        rolling_top_n=int(spec.get("rolling_top_n", 8)),
        require_rolling_top=bool(spec.get("require_rolling_top", False)),
        require_universe_gate=bool(spec.get("require_universe_gate", False)),
        quality_take_threshold=float(spec.get("quality_take_threshold", 64.0)),
        quality_watch_threshold=float(spec.get("quality_watch_threshold", 52.0)),
        structure_take_threshold=float(spec.get("structure_take_threshold", 63.0)),
        structure_watch_threshold=float(spec.get("structure_watch_threshold", 52.0)),
        min_volume_ratio=float(spec.get("min_volume_ratio", 0.0)),
        **kwargs,
    )


def aggregate(candidate: str, rows: list[dict[str, object]]) -> dict[str, object]:
    valid = [row for row in rows if row.get("status") == "OK"]
    positive = [row for row in valid if float(row.get("ret_pct", 0.0)) > 0]
    trades = sum(int(row.get("executed_trades", 0)) for row in valid)
    avg_ret = round(mean(float(row.get("ret_pct", 0.0)) for row in valid), 4) if valid else 0.0
    avg_pf = round(mean(float(row.get("pf", 0.0)) for row in valid), 4) if valid else 0.0
    worst_dd = round(max((abs(float(row.get("max_dd_pct", 0.0))) for row in valid), default=0.0), 4)
    positive_pct = len(positive) / len(valid) * 100.0 if valid else 0.0
    if not valid:
        verdict = "BLOCK_NO_VALID_FOLDS"
    elif trades < 30:
        verdict = "WATCH_TOO_SPARSE"
    elif positive_pct >= 75 and avg_pf >= 1.20 and avg_ret > 0 and worst_dd <= 10:
        verdict = "PASS_LONG_WFO"
    elif positive_pct >= 50 and avg_pf >= 1.05 and avg_ret > 0:
        verdict = "WATCH_PROMISING"
    else:
        verdict = "BLOCK_UNSTABLE"
    score = round(
        avg_ret + min(avg_pf, 3.0) * 3.0 - worst_dd * 0.5
        + positive_pct * 0.05 - max(0, 30 - trades) * 0.15,
        4,
    )
    return {
        "name": candidate,
        "verdict": verdict,
        "valid_folds": len(valid),
        "positive_folds": len(positive),
        "positive_pct": round(positive_pct, 2),
        "total_trades": trades,
        "avg_return_pct": avg_ret,
        "avg_pf": avg_pf,
        "worst_dd_pct": worst_dd,
        "score": score,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Long-history cached causal WFO sweep")
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--symbols-file", default=None)
    parser.add_argument("--out-dir", default="results/causal_long_history_sweep_v1")
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--limit", type=int, default=18000)
    parser.add_argument("--windows", type=int, default=6)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--profile", default="research_500")
    parser.add_argument("--pool-min-confidence", type=float, default=40.0)
    parser.add_argument("--sleep-sec", type=float, default=0.02)
    args = parser.parse_args()

    root = Path(args.out_dir)
    root.mkdir(parents=True, exist_ok=True)
    symbols = resolve_symbols(args.symbols, args.symbols_file)
    candles_path = root / "futures_candles.csv"
    market = load_binance_futures_candles(
        symbols=symbols,
        out_csv=candles_path,
        interval=args.interval,
        limit=args.limit,
        sleep_sec=args.sleep_sec,
        source="futures",
    )
    (root / "market_data_summary.json").write_text(json.dumps(asdict(market), indent=2) + "\n", encoding="utf-8")
    if market.status == "EMPTY" or market.symbols_loaded < max(5, int(len(symbols) * 0.75)):
        raise RuntimeError(
            f"True Binance Futures coverage is insufficient: {market.symbols_loaded}/{len(symbols)} symbols"
        )

    candle_rows, candle_fields = read_csv(candles_path)
    times = [parse_dt(row["time"]) for row in candle_rows]
    windows = wfo.make_windows(min(times), max(times), args.lookback_days, args.windows)
    if len(windows) < args.windows:
        raise RuntimeError(f"Only {len(windows)} WFO windows available")

    folds_by_candidate: dict[str, list[dict[str, object]]] = {str(spec["name"]): [] for spec in CANDIDATES}
    fold_index: list[dict[str, object]] = []
    for fold_no, (warmup_start, validation_start, validation_end) in enumerate(windows, start=1):
        fold_name = f"fold_{fold_no:02d}"
        fold_root = root / "folds" / fold_name
        fold_candles = [row for row in candle_rows if warmup_start <= parse_dt(row["time"]) < validation_end]
        write_csv(fold_root / "candles.csv", fold_candles, candle_fields)
        pool_path = fold_root / "pool" / "generated_trades.csv"
        pool_summary = generate_trade_pool(fold_root / "candles.csv", pool_path, args.pool_min_confidence)
        pool_rows, pool_fields = read_csv(pool_path)
        (fold_root / "pool" / "summary.json").write_text(
            json.dumps(pool_summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        fold_index.append({
            "fold": fold_name,
            "warmup_start": warmup_start.isoformat(),
            "validation_start": validation_start.isoformat(),
            "validation_end": validation_end.isoformat(),
            **pool_summary,
        })

        for spec in CANDIDATES:
            name = str(spec["name"])
            run_dir = fold_root / "candidates" / name
            selected_rows = filtered_pool(pool_rows, float(spec.get("min_confidence", 0.0)))
            generated_path = run_dir / "generated_trades.csv"
            write_csv(generated_path, selected_rows, pool_fields)
            cfg = config_for(spec, warmup_start, validation_end)
            row: dict[str, object] = {
                "fold": fold_name,
                "validation_start": validation_start.isoformat(),
                "validation_end": validation_end.isoformat(),
                "status": "OK",
            }
            try:
                if not selected_rows:
                    raise RuntimeError("no generated trades after confidence gate")
                run_pipeline(generated_path, run_dir, cfg=cfg, profile_name=args.profile)
                summary = evaluate_validation_window(
                    run_dir=run_dir,
                    validation_start=validation_start,
                    validation_end=validation_end,
                    profile_name=args.profile,
                    cfg=cfg,
                )
                row.update(asdict(summary))
            except Exception as exc:
                row.update({
                    "status": "ERROR",
                    "error": str(exc),
                    "candidates": 0,
                    "allowed_candidates": 0,
                    "executed_trades": 0,
                    "ret_pct": 0.0,
                    "max_dd_pct": 0.0,
                    "pf": 0.0,
                })
            folds_by_candidate[name].append(row)
            print(
                f"{name} {fold_name}: status={row['status']} trades={row.get('executed_trades', 0)} "
                f"ret={row.get('ret_pct', 0)} pf={row.get('pf', 0)} dd={row.get('max_dd_pct', 0)}",
                flush=True,
            )
        del fold_candles, pool_rows
        gc.collect()

    write_csv(root / "fold_index.csv", fold_index)
    summaries = [aggregate(name, rows) for name, rows in folds_by_candidate.items()]
    summaries.sort(key=lambda row: (row["verdict"] == "PASS_LONG_WFO", row["score"]), reverse=True)
    write_csv(root / "long_wfo_summary.csv", summaries)
    for name, rows in folds_by_candidate.items():
        write_csv(root / "candidate_folds" / f"{name}.csv", rows)

    result = {
        "mode": "STRICT_OOS_TRUE_BINANCE_FUTURES",
        "market": asdict(market),
        "windows": len(windows),
        "lookback_days": args.lookback_days,
        "screening_leader": summaries[0] if summaries else {},
        "candidates": summaries,
    }
    (root / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Causal long-history sweep", "",
        "Data source: **Binance USDT-M Futures only** (no Spot fallback).",
        f"WFO windows: **{len(windows)}**, warm-up: **{args.lookback_days} days**.", "",
        "## Candidates",
    ]
    for row in summaries:
        lines.append(
            f"- {row['name']}: **{row['verdict']}**, folds={row['positive_folds']}/{row['valid_folds']}, "
            f"trades={row['total_trades']}, avg_ret={row['avg_return_pct']}%, "
            f"PF={row['avg_pf']}, DD={row['worst_dd_pct']}%"
        )
    lines.extend(["", "No candidate is promoted by this screening alone; the leader still requires separate deep validation."])
    (root / "result.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print((root / "result.md").read_text(encoding="utf-8"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
