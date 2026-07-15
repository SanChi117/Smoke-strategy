#!/usr/bin/env python3
"""Calibrate the promising pullback-short control on frozen six-fold OOS data.

Reuses committed Binance Futures candles and generated trade pools from
``causal_long_history_sweep_v1``. Only causal decision thresholds are varied;
market data, trade outcomes, folds, costs and risk profile stay identical.
Research only. No API keys and no order execution.
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import run_causal_long_history_sweep as base
from strategy_lab.pipeline import run_pipeline
from strategy_lab.walk_forward_evaluation import evaluate_validation_window

SOURCE = Path("results/causal_long_history_sweep_v1")
OUT = Path("results/causal_long_history_calibration_v2")
PROFILE = "research_500"
PULLBACK_FAMILY = ("pullback", "pullback_resumption", "pullback_resumption_strict")


def spec(name: str, **overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "name": name,
        "rolling_top_n": 8,
        "require_rolling_top": False,
        "require_universe_gate": False,
        "min_confidence": 43.0,
        "quality_take_threshold": 64.0,
        "quality_watch_threshold": 52.0,
        "structure_take_threshold": 63.0,
        "structure_watch_threshold": 52.0,
        "allowed_setup_types": PULLBACK_FAMILY,
        "blocked_setup_types": ("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim", "ignition"),
        "blocked_volatility_regimes": ("high",),
        "blocked_liquidity_states": ("high_sweep_reject",),
        "blocked_candle_types": ("bear_rejection",),
        "allowed_direction_contexts": ("down",),
        "min_volume_ratio": 0.70,
    }
    item.update(overrides)
    return item


CANDIDATES = [
    spec("CAL2_CONTROL_V1"),
    spec("CAL2_CONF40_VR060_V1", min_confidence=40.0, min_volume_ratio=0.60),
    spec("CAL2_STRUCTURE_SOFT_V1", structure_take_threshold=60.0, structure_watch_threshold=48.0),
    spec("CAL2_QUALITY_SOFT_V1", quality_take_threshold=61.0, quality_watch_threshold=48.0),
    spec(
        "CAL2_ADAPTIVE_SOFT_V1",
        min_confidence=40.0,
        quality_take_threshold=61.0,
        quality_watch_threshold=48.0,
        structure_take_threshold=60.0,
        structure_watch_threshold=48.0,
        min_volume_ratio=0.60,
    ),
    spec(
        "CAL2_NEUTRAL_DIRECTION_V1",
        min_confidence=40.0,
        allowed_direction_contexts=("down", "neutral"),
        min_volume_ratio=0.60,
    ),
]


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = fields or (list(rows[0].keys()) if rows else [])
    if not names:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def parse_dt(value: object) -> datetime:
    return datetime.fromisoformat(str(value).strip().replace("Z", ""))


def main() -> int:
    fold_index, _ = read_csv(SOURCE / "fold_index.csv")
    folds_by_candidate: dict[str, list[dict[str, object]]] = {str(item["name"]): [] for item in CANDIDATES}

    for fold_row in fold_index:
        fold = fold_row["fold"]
        warmup_start = parse_dt(fold_row["warmup_start"])
        validation_start = parse_dt(fold_row["validation_start"])
        validation_end = parse_dt(fold_row["validation_end"])
        pool_path = SOURCE / "folds" / fold / "pool" / "generated_trades.csv"
        pool_rows, pool_fields = read_csv(pool_path)

        for item in CANDIDATES:
            name = str(item["name"])
            run_dir = OUT / "folds" / fold / name
            selected = base.filtered_pool(pool_rows, float(item["min_confidence"]))
            generated = run_dir / "generated_trades.csv"
            write_csv(generated, selected, pool_fields)
            cfg = base.config_for(item, warmup_start, validation_end)
            row: dict[str, object] = {
                "fold": fold,
                "validation_start": validation_start.isoformat(),
                "validation_end": validation_end.isoformat(),
                "status": "OK",
            }
            try:
                run_pipeline(generated, run_dir, cfg=cfg, profile_name=PROFILE)
                summary = evaluate_validation_window(run_dir, validation_start, validation_end, PROFILE, cfg)
                row.update(asdict(summary))
            except Exception as exc:
                row["status"] = "ERROR"
                row["error"] = f"{type(exc).__name__}: {exc}"
            folds_by_candidate[name].append(row)

    aggregates = [base.aggregate(name, rows) for name, rows in folds_by_candidate.items()]
    aggregates.sort(key=lambda row: float(row["score"]), reverse=True)
    OUT.mkdir(parents=True, exist_ok=True)
    write_csv(OUT / "candidate_summary.csv", aggregates)
    for name, rows in folds_by_candidate.items():
        write_csv(OUT / "candidate_folds" / f"{name}.csv", rows)
    result = {
        "mode": "CACHED_STRICT_OOS_PULLBACK_CALIBRATION_V2",
        "source": str(SOURCE),
        "folds": len(fold_index),
        "leader": aggregates[0] if aggregates else {},
        "candidates": aggregates,
    }
    (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
