#!/usr/bin/env python3
"""Run dynamic symbol-universe research.

Flow:
sector_groups.json -> combined classified universe -> dynamic-only matrix
(no fixed allowed_symbols configs) -> walk-forward -> research decision ->
symbol-first ranking with sector context -> compact diagnostics.

Research only. No API keys. No private data. No order execution.
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
    p = argparse.ArgumentParser(description="Run dynamic symbol-universe research.")
    p.add_argument("--top-n-per-group", type=int, default=10)
    p.add_argument("--limit", type=int, default=1500)
    p.add_argument("--windows", type=int, default=4)
    p.add_argument("--interval", default="1h")
    p.add_argument("--profile", default="growth_100_20x")
    p.add_argument("--root", default="results/symbol_universe_research")
    p.add_argument("--sleep-sec", type=float, default=0.05)
    args = p.parse_args()

    root = Path(args.root)
    symbols_path = root / "symbols.txt"
    universe_md = root / "sector_universe.md"
    matrix_dir = root / "deep_research" / "matrix"
    wf_dir = root / "deep_research" / "walk_forward"
    decision_dir = root / "deep_research" / "decision"
    candles_path = root / "deep_research" / "data" / "deep_research_candles.csv"
    wf_candles_path = root / "deep_research" / "data" / "walk_forward_candles.csv"
    root.mkdir(parents=True, exist_ok=True)

    print("Smoke Strategy Lab dynamic symbol-universe research")
    print("Mode: research-only public market data")
    print("API keys: not used")
    print("Order execution: disabled / not implemented")
    print("Universe: all sector groups combined")
    print("Sector use: context only, not a trading boundary")
    print("Matrix mode: dynamic-only, fixed allowed_symbols configs excluded")

    run_cmd([
        sys.executable,
        "scripts/build_sector_universe.py",
        "--groups", "all",
        "--top-n", str(args.top_n_per_group),
        "--out", str(symbols_path),
        "--md-out", str(universe_md),
    ])

    run_cmd([
        sys.executable,
        "scripts/run_binance_dynamic_matrix.py",
        "--symbols-file", str(symbols_path),
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
        "--symbols-file", str(symbols_path),
        "--interval", args.interval,
        "--limit", str(args.limit),
        "--candles-out", str(wf_candles_path),
        "--out-dir", str(wf_dir),
        "--baseline", str(baseline_path),
        "--profile", args.profile,
        "--windows", str(args.windows),
        "--lookback-days", "30",
        "--sleep-sec", str(args.sleep_sec),
    ])

    run_cmd([
        sys.executable,
        "scripts/make_research_decision.py",
        "--matrix", str(matrix_dir / "matrix_summary.csv"),
        "--baseline", str(baseline_path),
        "--walk-forward", str(wf_dir / "walk_forward_summary.csv"),
        "--out-dir", str(decision_dir),
    ])

    run_cmd([
        sys.executable,
        "scripts/rank_research_symbols.py",
        "--matrix-root", str(matrix_dir),
        "--groups-file", "strategy_lab/universe/sector_groups.json",
        "--out-dir", str(root),
        "--top-n", "40",
    ])

    run_cmd([
        sys.executable,
        "scripts/summarize_symbol_universe_diagnostics.py",
        "--matrix-root", str(matrix_dir),
        "--out-dir", str(root),
    ])

    print("\nDynamic symbol-universe research complete")
    for path in [
        root / "symbol_research_ranking.md",
        root / "dynamic_symbol_universe_candidate.json",
        root / "symbol_universe_diagnostics.md",
        matrix_dir / "matrix_summary.md",
        wf_dir / "walk_forward_summary.md",
        decision_dir / "research_decision.md",
    ]:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
