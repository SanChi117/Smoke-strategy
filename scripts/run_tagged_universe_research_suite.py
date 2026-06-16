#!/usr/bin/env python3
"""Run tagged-universe research in a runtime-safe MTF validation mode.

Research only. No API keys. No private account data. No order execution.
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


def run_cmd(cmd: list[str]) -> None:
    print("\n$ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run tagged-universe MTF research suite.")
    parser.add_argument("--top-n-per-group", type=int, default=10)
    parser.add_argument("--interval", default="15m")
    parser.add_argument("--limit", type=int, default=2500)
    parser.add_argument("--windows", type=int, default=3)
    parser.add_argument("--lookback-days", type=int, default=21)
    parser.add_argument("--deep-limit", type=int, default=3500)
    parser.add_argument("--deep-windows", type=int, default=4)
    parser.add_argument("--deep-lookback-days", type=int, default=35)
    parser.add_argument("--profile", default="growth_100_20x")
    parser.add_argument("--root", default="results/tagged_universe_research")
    parser.add_argument("--layer-root", default="results/strategy_universe_layer")
    parser.add_argument("--sleep-sec", type=float, default=0.02)
    args = parser.parse_args()

    root = Path(args.root)
    layer_root = Path(args.layer_root)
    matrix_dir = root / "matrix"
    walk_forward_dir = root / "walk_forward"
    decision_dir = root / "decision"
    tagged_decision_dir = root / "tagged_decision"
    deep_validation_dir = root / "deep_validation"
    deep_fold_diagnostics_dir = root / "deep_fold_diagnostics"
    paper_review_dir = root / "paper_review"
    micro_root = root / "micro_5m"
    candles_path = root / "data" / "tagged_universe_candles.csv"
    wf_candles_path = root / "data" / "walk_forward_candles.csv"
    symbols_file = layer_root / "combined_symbols.txt"

    print("Smoke Strategy Lab tagged-universe MTF research suite")
    print("Mode: research-only public market data")
    print("Order execution: disabled / not implemented")
    print("Universe: full tagged universe, not reduced")
    print("Matrix mode: controlled MTF A/B candidates")

    run_cmd([sys.executable, "scripts/build_strategy_universe_layer.py", "--top-n-per-group", str(args.top_n_per_group), "--out-dir", str(layer_root)])
    run_cmd([sys.executable, "scripts/run_binance_tagged_mtf_fast_matrix.py", "--symbols-file", str(symbols_file), "--interval", args.interval, "--limit", str(args.limit), "--candles-out", str(candles_path), "--out-dir", str(matrix_dir), "--profile", args.profile, "--sleep-sec", str(args.sleep_sec)])

    baseline_path = matrix_dir / "baseline_candidate" / "baseline_candidate.json"
    run_cmd([sys.executable, "scripts/run_binance_walk_forward_v2.py", "--symbols-file", str(symbols_file), "--interval", args.interval, "--limit", str(args.limit), "--candles-out", str(wf_candles_path), "--out-dir", str(walk_forward_dir), "--baseline", str(baseline_path), "--profile", args.profile, "--windows", str(args.windows), "--lookback-days", str(args.lookback_days), "--sleep-sec", str(args.sleep_sec)])
    run_cmd([sys.executable, "scripts/make_research_decision.py", "--matrix", str(matrix_dir / "matrix_summary.csv"), "--baseline", str(baseline_path), "--walk-forward", str(walk_forward_dir / "walk_forward_summary.csv"), "--out-dir", str(decision_dir)])
    run_cmd([sys.executable, "scripts/summarize_tagged_universe_selection.py", "--matrix-root", str(matrix_dir), "--layer-json", str(layer_root / "strategy_universe_layer.json"), "--out-dir", str(root)])
    run_cmd([sys.executable, "scripts/run_tagged_multi_wfo.py", "--matrix", str(matrix_dir / "matrix_summary.csv"), "--symbols-file", str(symbols_file), "--out-dir", str(root / "multi_wfo"), "--candidate-names", FAST_CANDIDATES, "--interval", args.interval, "--limit", str(args.limit), "--windows", str(args.windows), "--lookback-days", str(args.lookback_days), "--profile", args.profile, "--sleep-sec", str(args.sleep_sec)])
    run_cmd([sys.executable, "scripts/diagnose_tagged_wfo_fold.py", "--multi-wfo-root", str(root / "multi_wfo"), "--best-json", str(root / "multi_wfo" / "tagged_multi_wfo_best.json"), "--layer-json", str(layer_root / "strategy_universe_layer.json"), "--out-dir", str(root / "fold_diagnostics")])
    run_cmd([sys.executable, "scripts/run_tagged_deep_validation.py", "--matrix", str(matrix_dir / "matrix_summary.csv"), "--multi-best", str(root / "multi_wfo" / "tagged_multi_wfo_best.json"), "--symbols-file", str(symbols_file), "--out-dir", str(deep_validation_dir), "--interval", args.interval, "--limit", str(args.deep_limit), "--windows", str(args.deep_windows), "--lookback-days", str(args.deep_lookback_days), "--profile", args.profile, "--sleep-sec", str(args.sleep_sec)])
    run_cmd([sys.executable, "scripts/diagnose_tagged_deep_validation_folds.py", "--deep-root", str(deep_validation_dir), "--deep-summary", str(deep_validation_dir / "deep_validation_summary.json"), "--walk-forward", str(deep_validation_dir / "walk_forward_summary.csv"), "--layer-json", str(layer_root / "strategy_universe_layer.json"), "--out-dir", str(deep_fold_diagnostics_dir)])
    run_cmd([sys.executable, "scripts/make_tagged_research_decision.py", "--multi-best", str(root / "multi_wfo" / "tagged_multi_wfo_best.json"), "--deep-summary", str(deep_validation_dir / "deep_validation_summary.json"), "--out-dir", str(tagged_decision_dir)])
    run_cmd([sys.executable, "scripts/make_tagged_paper_review_plan.py", "--decision", str(tagged_decision_dir / "tagged_research_decision.json"), "--deep", str(deep_validation_dir / "deep_validation_summary.json"), "--multi", str(root / "multi_wfo" / "tagged_multi_wfo_best.json"), "--baseline", str(deep_validation_dir / "deep_baseline_candidate.json"), "--out-dir", str(paper_review_dir)])
    run_cmd([sys.executable, "scripts/make_tagged_paper_review_templates.py", "--plan-json", str(paper_review_dir / "paper_review_plan.json"), "--out-dir", str(paper_review_dir)])

    run_cmd([sys.executable, "scripts/run_tagged_mtf_5m_confirmation_matrix.py", "--symbols-file", str(symbols_file), "--limit", str(max(args.limit * 3, 3000)), "--raw-5m-out", str(micro_root / "data" / "raw_5m_candles.csv"), "--candles-15m-out", str(micro_root / "data" / "rebuilt_15m_candles.csv"), "--out-dir", str(micro_root / "matrix"), "--profile", args.profile, "--sleep-sec", str(args.sleep_sec)])

    print("\nTagged-universe MTF research suite complete")
    for path in [layer_root / "strategy_universe_layer.md", matrix_dir / "matrix_summary.md", walk_forward_dir / "walk_forward_summary.md", root / "multi_wfo" / "tagged_multi_wfo_summary.md", deep_validation_dir / "deep_validation_summary.md", deep_fold_diagnostics_dir / "deep_fold_diagnostics.md", tagged_decision_dir / "tagged_research_decision.md", paper_review_dir / "paper_review_plan.md", paper_review_dir / "paper_review_protocol.md", paper_review_dir / "paper_review_journal_template.csv", micro_root / "matrix" / "matrix_summary.md"]:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
