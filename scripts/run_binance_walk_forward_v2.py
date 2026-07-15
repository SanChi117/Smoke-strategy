#!/usr/bin/env python3
"""Walk-forward runner with tactical gates and strict out-of-sample scoring.

The underlying pipeline still receives warm-up candles so causal Quality,
Structure Learning and rolling-universe layers can learn. Reported P&L, paper
signals and fold statistics are rebuilt from validation-window entries only.

Research only. No API keys. No private account data. No order execution.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

import run_binance_walk_forward as base
from strategy_lab.config import PipelineConfig
from strategy_lab.end_to_end_pipeline import write_summary
from strategy_lab.paper_mode import run_paper_mode
from strategy_lab.report_sanity import write_report_sanity
from strategy_lab.walk_forward_evaluation import evaluate_validation_window


_ORIGINAL_MAKE_WINDOWS = base.make_windows
_ORIGINAL_RUN_END_TO_END = base.run_end_to_end_pipeline
_EVALUATION_WINDOWS: dict[str, tuple[datetime, datetime]] = {}
_KNOWN_WINDOWS: dict[tuple[datetime, datetime], datetime] = {}


def to_bool(value: object, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def patched_make_windows(
    min_time: datetime,
    max_time: datetime,
    lookback_days: int,
    windows: int,
) -> list[tuple[datetime, datetime, datetime]]:
    folds = _ORIGINAL_MAKE_WINDOWS(min_time, max_time, lookback_days, windows)
    _KNOWN_WINDOWS.clear()
    for warmup_start, validation_start, validation_end in folds:
        _KNOWN_WINDOWS[(warmup_start, validation_end)] = validation_start
    return folds


def patched_baseline_to_cfg(
    baseline: dict[str, object],
    name: str,
    warmup_start: datetime,
    validation_end: datetime,
) -> PipelineConfig:
    validation_start = _KNOWN_WINDOWS.get((warmup_start, validation_end))
    if validation_start is None:
        raise RuntimeError(
            "Walk-forward validation boundary was not registered for "
            f"{warmup_start.isoformat()} -> {validation_end.isoformat()}"
        )
    _EVALUATION_WINDOWS[name] = (validation_start, validation_end)
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
        allowed_context_alignments=base.to_tuple(baseline.get("allowed_context_alignments")),
        blocked_context_alignments=base.to_tuple(baseline.get("blocked_context_alignments")),
    )


def patched_run_end_to_end_pipeline(
    candles_csv: str | Path,
    out_dir: str | Path = "results",
    profile: str = "growth_100_20x",
    min_confidence: float = 50.0,
    cfg: PipelineConfig | None = None,
):
    original_summary = _ORIGINAL_RUN_END_TO_END(
        candles_csv=candles_csv,
        out_dir=out_dir,
        profile=profile,
        min_confidence=min_confidence,
        cfg=cfg,
    )
    if cfg is None or cfg.name not in _EVALUATION_WINDOWS:
        return original_summary

    validation_start, validation_end = _EVALUATION_WINDOWS[cfg.name]
    fair = evaluate_validation_window(
        run_dir=out_dir,
        validation_start=validation_start,
        validation_end=validation_end,
        profile_name=profile,
        cfg=cfg,
    )

    root = Path(out_dir)
    paper_summary = run_paper_mode(
        generated_trades_csv=root / "pipeline_allowed_trades.csv",
        out_dir=root / "paper",
    )
    sanity = write_report_sanity(root)
    summary = replace(
        original_summary,
        pipeline_candidates=fair.candidates,
        allowed_candidates=fair.allowed_candidates,
        executed_trades=fair.executed_trades,
        final_cash=fair.final_cash,
        ret_pct=fair.ret_pct,
        max_dd_pct=fair.max_dd_pct,
        pf=fair.pf,
        winrate=fair.winrate,
        avg_risk_pct=fair.avg_risk_pct,
        paper_signals=paper_summary.paper_signals,
        paper_filled=paper_summary.filled_paper,
        paper_closed=paper_summary.closed_paper,
        paper_avg_pnl_pct=paper_summary.avg_pnl_pct,
        sanity_status=sanity.status,
        sanity_errors=sanity.errors,
        sanity_warnings=sanity.warnings,
    )
    write_summary(root / "end_to_end_summary.csv", summary)
    return summary


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
        "Evaluation mode: **STRICT OUT-OF-SAMPLE** (warm-up trades excluded from P&L)",
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
        lines.append("- Candidate can move to deeper paper-mode review. Warm-up trades were excluded from performance.")
    elif verdict == "WATCH_REVIEWABLE_BUT_UNSTABLE":
        lines.append("- Candidate is reviewable, but compare strict out-of-sample fold diagnostics before promotion.")
    elif verdict == "WATCH_TOO_SPARSE":
        lines.append("- Increase validation history or reduce window count before judging stability.")
    else:
        lines.append("- Continue strategy diagnostics; do not promote this candidate.")
    return "\n".join(lines) + "\n"


def main() -> int:
    base.DEFAULT_BASELINE["require_rolling_top"] = True
    base.DEFAULT_BASELINE["require_universe_gate"] = True
    base.DEFAULT_BASELINE["min_volume_ratio"] = 0.0
    base.make_windows = patched_make_windows
    base.baseline_to_cfg = patched_baseline_to_cfg
    base.run_end_to_end_pipeline = patched_run_end_to_end_pipeline
    base.build_markdown = patched_build_markdown
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
