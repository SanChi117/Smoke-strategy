#!/usr/bin/env python3
"""Walk-forward runner with baseline tactical gate support.

Small compatibility wrapper around run_binance_walk_forward.py.
It preserves existing fold execution behavior, but ensures baseline_candidate.json
can control PipelineConfig tactical filters.

Research only. No API keys. No private account data. No order execution.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from statistics import mean

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
        require_universe_gate=to_bool(baseline.get("require_universe_gate"), True),
        quality_take_threshold=base.to_float(baseline.get("quality_take_threshold"), 65.0),
        quality_watch_threshold=base.to_float(baseline.get("quality_watch_threshold"), 50.0),
        structure_take_threshold=base.to_float(baseline.get("structure_take_threshold"), 64.0),
        structure_watch_threshold=base.to_float(baseline.get("structure_watch_threshold"), 52.0),
        min_volume_ratio=base.to_float(baseline.get("min_volume_ratio"), 0.0),
        allowed_symbols=base.to_tuple(baseline.get("allowed_symbols")),
        blocked_symbols=base.to_tuple(baseline.get("blocked_symbols")),
        allowed_setup_types=base.to_tuple(baseline.get("allowed_setup_types")),
        blocked_setup_types=base.to_tuple(baseline.get("blocked_setup_types")),
        allowed_trend_contexts=base.to_tuple(baseline.get("allowed_trend_contexts")),
        blocked_trend_contexts=base.to_tuple(baseline.get("blocked_trend_contexts")),
        allowed_volatility_regimes=base.to_tuple(baseline.get("allowed_volatility_regimes")),
        blocked_volatility_regimes=base.to_tuple(baseline.get("blocked_volatility_regimes")),
        allowed_liquidity_states=base.to_tuple(baseline.get("allowed_liquidity_states")),
        blocked_liquidity_states=base.to_tuple(baseline.get("blocked_liquidity_states")),
        allowed_candle_types=base.to_tuple(baseline.get("allowed_candle_types")),
        blocked_candle_types=base.to_tuple(baseline.get("blocked_candle_types")),
        allowed_direction_contexts=base.to_tuple(baseline.get("allowed_direction_contexts")),
        blocked_direction_contexts=base.to_tuple(baseline.get("blocked_direction_contexts")),
    )


def patched_build_markdown(summary_rows: list[dict[str, object]], baseline: dict[str, object]) -> str:
    ok_rows = [r for r in summary_rows if r.get("status") == "OK"]
    positive_rows = [r for r in ok_rows if base.to_float(r.get("ret_pct")) > 0]
    sanity_ok_rows = [r for r in ok_rows if r.get("sanity_status") == "OK"]
    sanity_non_fail_rows = [r for r in ok_rows if r.get("sanity_status") in {"OK", "WARN"}]
    total_executed = sum(base.to_int(r.get("executed_trades")) for r in ok_rows)
    avg_ret = round(mean([base.to_float(r.get("ret_pct")) for r in ok_rows]), 4) if ok_rows else 0.0
    avg_pf = round(mean([base.to_float(r.get("pf")) for r in ok_rows]), 4) if ok_rows else 0.0
    worst_dd = round(max([abs(base.to_float(r.get("max_dd_pct"))) for r in ok_rows], default=0.0), 4)
    positive_pct = round(len(positive_rows) / len(ok_rows) * 100.0, 2) if ok_rows else 0.0
    sanity_ok_pct = round(len(sanity_ok_rows) / len(ok_rows) * 100.0, 2) if ok_rows else 0.0
    sanity_non_fail_pct = round(len(sanity_non_fail_rows) / len(ok_rows) * 100.0, 2) if ok_rows else 0.0

    if not ok_rows:
        verdict = "BLOCK_NO_VALID_FOLDS"
    elif total_executed < 10:
        verdict = "WATCH_TOO_SPARSE"
    elif positive_pct >= 75 and sanity_non_fail_pct >= 100 and avg_pf >= 1.20 and avg_ret > 0 and worst_dd <= 10:
        verdict = "PASS_WALK_FORWARD_REVIEW"
    elif positive_pct >= 50 and sanity_non_fail_pct >= 100 and avg_pf >= 1.0 and avg_ret > 0:
        verdict = "WATCH_REVIEWABLE_BUT_UNSTABLE"
    else:
        verdict = "WATCH_UNSTABLE"

    lines = [
        "# Binance Walk-Forward Summary",
        "",
        f"Verdict: **{verdict}**",
        "",
        "## Baseline candidate",
        f"- Name: {baseline.get('name')}",
        f"- Rolling top N: {baseline.get('rolling_top_n')}",
        f"- Require rolling top: {baseline.get('require_rolling_top')}",
        f"- Require universe gate: {baseline.get('require_universe_gate')}",
        f"- Min confidence: {baseline.get('min_confidence')}",
        f"- Quality TAKE/WATCH: {baseline.get('quality_take_threshold')} / {baseline.get('quality_watch_threshold')}",
        f"- Structure TAKE/WATCH: {baseline.get('structure_take_threshold')} / {baseline.get('structure_watch_threshold')}",
        f"- Min volume ratio: {baseline.get('min_volume_ratio')}",
        f"- Allowed symbols: {', '.join(base.to_tuple(baseline.get('allowed_symbols'))) or 'none'}",
        f"- Blocked setup types: {', '.join(base.to_tuple(baseline.get('blocked_setup_types'))) or 'none'}",
        f"- Blocked volatility regimes: {', '.join(base.to_tuple(baseline.get('blocked_volatility_regimes'))) or 'none'}",
        f"- Blocked liquidity states: {', '.join(base.to_tuple(baseline.get('blocked_liquidity_states'))) or 'none'}",
        f"- Blocked candle types: {', '.join(base.to_tuple(baseline.get('blocked_candle_types'))) or 'none'}",
        f"- Blocked direction contexts: {', '.join(base.to_tuple(baseline.get('blocked_direction_contexts'))) or 'none'}",
        "",
        "## Aggregate",
        f"- Valid folds: {len(ok_rows)} / {len(summary_rows)}",
        f"- Positive folds: {len(positive_rows)} ({positive_pct}%)",
        f"- Sanity OK folds: {len(sanity_ok_rows)} ({sanity_ok_pct}%)",
        f"- Sanity non-fail folds: {len(sanity_non_fail_rows)} ({sanity_non_fail_pct}%)",
        f"- Total executed trades: {total_executed}",
        f"- Average return pct: {avg_ret}%",
        f"- Average PF: {avg_pf}",
        f"- Worst max DD pct: {worst_dd}%",
        "",
        "## Folds",
    ]
    for row in summary_rows:
        lines.append(
            f"- {row.get('fold')}: status={row.get('status')}, score={row.get('score')}, "
            f"ret={row.get('ret_pct')}%, dd={row.get('max_dd_pct')}%, pf={row.get('pf')}, "
            f"executed={row.get('executed_trades')}, sanity={row.get('sanity_status')}, "
            f"window={row.get('validation_start')} -> {row.get('validation_end')}"
        )
        if row.get("error"):
            lines.append(f"  - error: {row.get('error')}")
    lines.extend(["", "## Next step"])
    if verdict == "PASS_WALK_FORWARD_REVIEW":
        lines.append("- Candidate can move to deeper paper-mode review. WARN-only sanity is reviewable because all folds are non-fail and performance is stable.")
    elif verdict == "WATCH_REVIEWABLE_BUT_UNSTABLE":
        lines.append("- Candidate is reviewable, but compare fold diagnostics before promotion.")
    elif verdict == "WATCH_TOO_SPARSE":
        lines.append("- Increase candle limit, symbols, or reduce window count before judging stability.")
    elif verdict == "WATCH_UNSTABLE":
        lines.append("- Compare fold diagnostics and disable weak setup/regime groups before promotion.")
    else:
        lines.append("- Fix data/window generation or baseline configuration before continuing.")
    return "\n".join(lines) + "\n"


def main() -> int:
    base.DEFAULT_BASELINE["require_rolling_top"] = True
    base.DEFAULT_BASELINE["require_universe_gate"] = True
    base.DEFAULT_BASELINE["min_volume_ratio"] = 0.0
    base.baseline_to_cfg = patched_baseline_to_cfg
    base.build_markdown = patched_build_markdown
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
