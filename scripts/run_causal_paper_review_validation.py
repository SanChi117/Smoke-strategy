#!/usr/bin/env python3
"""Run the mandatory causal validation required before VPS paper review.

This runner intentionally excludes the optional 5m confirmation matrix. It
runs the exact core chain needed to decide whether the validated 15m MTF
baseline may proceed to live paper observation:

universe -> matrix -> walk-forward -> multi-WFO -> deep validation ->
fold diagnostics -> tagged decision -> paper-review plan/templates.

Research/paper only. No API keys. No real orders.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


FAST_CANDIDATES = (
    "TAGGED_MTF_NO_DIRECTION_BLOCK_V1,"
    "TAGGED_MTF_NO_DIRECTION_NO_IGNITION_V1,"
    "TAGGED_MTF_ENTRY_CONFIRM_V1"
)


def run_cmd(command: list[str]) -> None:
    print("\n$ " + " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run focused causal paper-review validation.")
    parser.add_argument("--top-n-per-group", type=int, default=10)
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--limit", type=int, default=2500)
    parser.add_argument("--windows", type=int, default=3)
    parser.add_argument("--lookback-days", type=int, default=21)
    parser.add_argument("--deep-limit", type=int, default=3500)
    parser.add_argument("--deep-windows", type=int, default=4)
    parser.add_argument("--deep-lookback-days", type=int, default=35)
    parser.add_argument("--profile", default="growth_100_20x")
    parser.add_argument("--root", default="results/causal_paper_review_validation")
    parser.add_argument("--layer-root", default="results/causal_paper_review_universe")
    parser.add_argument("--sleep-sec", type=float, default=0.02)
    args = parser.parse_args()

    root = Path(args.root)
    layer_root = Path(args.layer_root)
    matrix_dir = root / "matrix"
    walk_forward_dir = root / "walk_forward"
    decision_dir = root / "decision"
    multi_dir = root / "multi_wfo"
    fold_dir = root / "fold_diagnostics"
    deep_dir = root / "deep_validation"
    deep_diag_dir = root / "deep_fold_diagnostics"
    tagged_decision_dir = root / "tagged_decision"
    paper_dir = root / "paper_review"
    data_dir = root / "data"
    symbols_file = layer_root / "combined_symbols.txt"

    print("SMOKE focused causal paper-review validation", flush=True)
    print("Optional 5m confirmation matrix: skipped", flush=True)
    print("Live orders: disabled", flush=True)

    run_cmd([
        sys.executable,
        "scripts/build_strategy_universe_layer.py",
        "--top-n-per-group",
        str(args.top_n_per_group),
        "--out-dir",
        str(layer_root),
    ])
    run_cmd([
        sys.executable,
        "scripts/run_binance_tagged_mtf_fast_matrix.py",
        "--symbols-file",
        str(symbols_file),
        "--interval",
        args.interval,
        "--limit",
        str(args.limit),
        "--candles-out",
        str(data_dir / "matrix_candles.csv"),
        "--out-dir",
        str(matrix_dir),
        "--profile",
        args.profile,
        "--sleep-sec",
        str(args.sleep_sec),
    ])

    baseline_path = matrix_dir / "baseline_candidate" / "baseline_candidate.json"
    run_cmd([
        sys.executable,
        "scripts/run_binance_walk_forward_v2.py",
        "--symbols-file",
        str(symbols_file),
        "--interval",
        args.interval,
        "--limit",
        str(args.limit),
        "--candles-out",
        str(data_dir / "walk_forward_candles.csv"),
        "--out-dir",
        str(walk_forward_dir),
        "--baseline",
        str(baseline_path),
        "--profile",
        args.profile,
        "--windows",
        str(args.windows),
        "--lookback-days",
        str(args.lookback_days),
        "--sleep-sec",
        str(args.sleep_sec),
    ])
    run_cmd([
        sys.executable,
        "scripts/make_research_decision.py",
        "--matrix",
        str(matrix_dir / "matrix_summary.csv"),
        "--baseline",
        str(baseline_path),
        "--walk-forward",
        str(walk_forward_dir / "walk_forward_summary.csv"),
        "--out-dir",
        str(decision_dir),
    ])
    run_cmd([
        sys.executable,
        "scripts/summarize_tagged_universe_selection.py",
        "--matrix-root",
        str(matrix_dir),
        "--layer-json",
        str(layer_root / "strategy_universe_layer.json"),
        "--out-dir",
        str(root),
    ])
    run_cmd([
        sys.executable,
        "scripts/run_tagged_multi_wfo.py",
        "--matrix",
        str(matrix_dir / "matrix_summary.csv"),
        "--symbols-file",
        str(symbols_file),
        "--out-dir",
        str(multi_dir),
        "--candidate-names",
        FAST_CANDIDATES,
        "--interval",
        args.interval,
        "--limit",
        str(args.limit),
        "--windows",
        str(args.windows),
        "--lookback-days",
        str(args.lookback_days),
        "--profile",
        args.profile,
        "--sleep-sec",
        str(args.sleep_sec),
    ])
    run_cmd([
        sys.executable,
        "scripts/diagnose_tagged_wfo_fold.py",
        "--multi-wfo-root",
        str(multi_dir),
        "--best-json",
        str(multi_dir / "tagged_multi_wfo_best.json"),
        "--layer-json",
        str(layer_root / "strategy_universe_layer.json"),
        "--out-dir",
        str(fold_dir),
    ])
    run_cmd([
        sys.executable,
        "scripts/run_tagged_deep_validation.py",
        "--matrix",
        str(matrix_dir / "matrix_summary.csv"),
        "--multi-best",
        str(multi_dir / "tagged_multi_wfo_best.json"),
        "--symbols-file",
        str(symbols_file),
        "--out-dir",
        str(deep_dir),
        "--interval",
        args.interval,
        "--limit",
        str(args.deep_limit),
        "--windows",
        str(args.deep_windows),
        "--lookback-days",
        str(args.deep_lookback_days),
        "--profile",
        args.profile,
        "--sleep-sec",
        str(args.sleep_sec),
    ])
    run_cmd([
        sys.executable,
        "scripts/diagnose_tagged_deep_validation_folds.py",
        "--deep-root",
        str(deep_dir),
        "--deep-summary",
        str(deep_dir / "deep_validation_summary.json"),
        "--walk-forward",
        str(deep_dir / "walk_forward_summary.csv"),
        "--layer-json",
        str(layer_root / "strategy_universe_layer.json"),
        "--out-dir",
        str(deep_diag_dir),
    ])
    run_cmd([
        sys.executable,
        "scripts/make_tagged_research_decision.py",
        "--multi-best",
        str(multi_dir / "tagged_multi_wfo_best.json"),
        "--deep-summary",
        str(deep_dir / "deep_validation_summary.json"),
        "--out-dir",
        str(tagged_decision_dir),
    ])
    run_cmd([
        sys.executable,
        "scripts/make_tagged_paper_review_plan.py",
        "--decision",
        str(tagged_decision_dir / "tagged_research_decision.json"),
        "--deep",
        str(deep_dir / "deep_validation_summary.json"),
        "--multi",
        str(multi_dir / "tagged_multi_wfo_best.json"),
        "--baseline",
        str(deep_dir / "deep_baseline_candidate.json"),
        "--out-dir",
        str(paper_dir),
    ])
    run_cmd([
        sys.executable,
        "scripts/make_tagged_paper_review_templates.py",
        "--plan-json",
        str(paper_dir / "paper_review_plan.json"),
        "--out-dir",
        str(paper_dir),
    ])

    print("\nFocused causal validation complete", flush=True)
    for path in [
        matrix_dir / "matrix_summary.md",
        multi_dir / "tagged_multi_wfo_summary.md",
        deep_dir / "deep_validation_summary.md",
        tagged_decision_dir / "tagged_research_decision.md",
        paper_dir / "paper_review_plan.md",
    ]:
        print(path, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
