#!/usr/bin/env python3
"""Run tagged-universe research without changing strategy logic.

Flow:
1. Build strategy universe layer: core reference + discovery pool + sector tags.
2. Run tagged-universe matrix:
   - old fixed-core configs remain as control rows;
   - additional configs reuse the successful tactical logic without allowed_symbols.
3. Run WFO on the best matrix candidate.
4. Make research decision.
5. Summarize what symbols were actually selected with core/discovery/sector tags.
6. Run multi-WFO comparison across several tagged candidates.

Research only. No API keys. No private account data. No order execution.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: list[str]) -> None:
    print("\n$ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run tagged-universe research suite.")
    parser.add_argument("--top-n-per-group", type=int, default=10)
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--windows", type=int, default=4)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--profile", default="growth_100_20x")
    parser.add_argument("--root", default="results/tagged_universe_research")
    parser.add_argument("--layer-root", default="results/strategy_universe_layer")
    parser.add_argument("--sleep-sec", type=float, default=0.05)
    args = parser.parse_args()

    root = Path(args.root)
    layer_root = Path(args.layer_root)
    matrix_dir = root / "matrix"
    walk_forward_dir = root / "walk_forward"
    decision_dir = root / "decision"
    candles_path = root / "data" / "tagged_universe_candles.csv"
    wf_candles_path = root / "data" / "walk_forward_candles.csv"
    symbols_file = layer_root / "combined_symbols.txt"

    print("Smoke Strategy Lab tagged-universe research suite")
    print("Mode: research-only public market data")
    print("API keys: not used")
    print("Private account data: not used")
    print("Order execution: disabled / not implemented")
    print("Strategy changed: False")
    print("Sector is context tag only: True")

    run_cmd([
        sys.executable,
        "scripts/build_strategy_universe_layer.py",
        "--top-n-per-group", str(args.top_n_per_group),
        "--out-dir", str(layer_root),
    ])

    run_cmd([
        sys.executable,
        "scripts/run_binance_tagged_universe_matrix.py",
        "--symbols-file", str(symbols_file),
        "--interval", args.interval,
        "--limit", str(args.limit),
        "--candles-out", str(candles_path),
        "--out-dir", str(matrix_dir),
        "--profile", args.profile,
        "--sleep-sec", str(args.sleep_sec),
    ])

    baseline_path = matrix_dir / "baseline_candidate" / "baseline_candidate.json"

    run_cmd([
        sys.executable,
        "scripts/run_binance_walk_forward_v2.py",
        "--symbols-file", str(symbols_file),
        "--interval", args.interval,
        "--limit", str(args.limit),
        "--candles-out", str(wf_candles_path),
        "--out-dir", str(walk_forward_dir),
        "--baseline", str(baseline_path),
        "--profile", args.profile,
        "--windows", str(args.windows),
        "--lookback-days", str(args.lookback_days),
        "--sleep-sec", str(args.sleep_sec),
    ])

    run_cmd([
        sys.executable,
        "scripts/make_research_decision.py",
        "--matrix", str(matrix_dir / "matrix_summary.csv"),
        "--baseline", str(baseline_path),
        "--walk-forward", str(walk_forward_dir / "walk_forward_summary.csv"),
        "--out-dir", str(decision_dir),
    ])

    run_cmd([
        sys.executable,
        "scripts/summarize_tagged_universe_selection.py",
        "--matrix-root", str(matrix_dir),
        "--layer-json", str(layer_root / "strategy_universe_layer.json"),
        "--out-dir", str(root),
    ])

    run_cmd([
        sys.executable,
        "scripts/run_tagged_multi_wfo.py",
        "--matrix", str(matrix_dir / "matrix_summary.csv"),
        "--symbols-file", str(symbols_file),
        "--out-dir", str(root / "multi_wfo"),
        "--interval", args.interval,
        "--limit", str(args.limit),
        "--windows", str(args.windows),
        "--lookback-days", str(args.lookback_days),
        "--profile", args.profile,
        "--sleep-sec", str(args.sleep_sec),
    ])

    print("\nTagged-universe research suite complete")
    for path in [
        layer_root / "strategy_universe_layer.md",
        matrix_dir / "matrix_summary.md",
        matrix_dir / "baseline_candidate" / "baseline_candidate.md",
        walk_forward_dir / "walk_forward_summary.md",
        decision_dir / "research_decision.md",
        root / "tagged_universe_selection.md",
        root / "multi_wfo" / "tagged_multi_wfo_summary.md",
    ]:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
