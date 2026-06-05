#!/usr/bin/env python3
"""Walk-forward runner with baseline rolling-gate support.

Small compatibility wrapper around run_binance_walk_forward.py.
It preserves all existing behavior, but ensures baseline_candidate.json can
control PipelineConfig.require_rolling_top.

Research only. No API keys. No private account data. No order execution.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import run_binance_walk_forward as base
from strategy_lab.config import PipelineConfig


def to_bool(value: object, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def patched_baseline_to_cfg(
    baseline: dict[str, object],
    name: str,
    warmup_start: datetime,
    validation_end: datetime,
) -> PipelineConfig:
    return replace(
        PipelineConfig(),
        name=name,
        start=warmup_start.date().isoformat(),
        end=(validation_end + timedelta(days=1)).date().isoformat(),
        rolling_top_n=base.to_int(baseline.get("rolling_top_n"), 5),
        require_rolling_top=to_bool(baseline.get("require_rolling_top"), True),
        quality_take_threshold=base.to_float(baseline.get("quality_take_threshold"), 65.0),
        quality_watch_threshold=base.to_float(baseline.get("quality_watch_threshold"), 50.0),
        structure_take_threshold=base.to_float(baseline.get("structure_take_threshold"), 64.0),
        structure_watch_threshold=base.to_float(baseline.get("structure_watch_threshold"), 52.0),
        allowed_symbols=base.to_tuple(baseline.get("allowed_symbols")),
        blocked_symbols=base.to_tuple(baseline.get("blocked_symbols")),
        allowed_setup_types=base.to_tuple(baseline.get("allowed_setup_types")),
        blocked_setup_types=base.to_tuple(baseline.get("blocked_setup_types")),
        allowed_trend_contexts=base.to_tuple(baseline.get("allowed_trend_contexts")),
        blocked_trend_contexts=base.to_tuple(baseline.get("blocked_trend_contexts")),
        allowed_volatility_regimes=base.to_tuple(baseline.get("allowed_volatility_regimes")),
        blocked_volatility_regimes=base.to_tuple(baseline.get("blocked_volatility_regimes")),
    )


def main() -> int:
    base.DEFAULT_BASELINE["require_rolling_top"] = True
    base.baseline_to_cfg = patched_baseline_to_cfg
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
