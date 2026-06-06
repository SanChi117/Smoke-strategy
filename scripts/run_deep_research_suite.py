#!/usr/bin/env python3
"""Run the full deep research suite on real Binance public data.

This is intentionally separate from CI smoke checks. It runs a larger matrix,
walk-forward validation, and final research decision in one command.

Research only. No API keys. No private account data. No order execution.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


DEFAULT_DEEP_SYMBOLS = (
    "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,LINKUSDT,"
    "AVAXUSDT,TONUSDT,NEARUSDT,APTUSDT,ARBUSDT,OPUSDT,INJUSDT,"
    "SEIUSDT,TIAUSDT,SUIUSDT,JUPUSDT,PYTHUSDT,WIFUSDT,ORDIUSDT,WLDUSDT,"
    "FETUSDT,RUNEUSDT,FILUSDT,ATOMUSDT,AAVEUSDT,UNIUSDT,DOTUSDT,LTCUSDT,"
    "ETCUSDT,BCHUSDT,TRXUSDT"
)


def run_cmd(cmd: list[str]) -> None:
    print("\n$ " + " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deep Binance research suite.")
    parser.add_argument("--symbols", default=DEFAULT_DEEP_SYMBOLS)
    parser.add_argument("--symbols-file", default=None)
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--windows", type=int, default=4)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--profile", default="growth_100_20x")
    parser.add_argument("--root", default="results/deep_research")
    parser.add_argument("--sleep-sec", type=float, default=0.05)
    args = parser.parse_args()

    root = Path(args.root)
    matrix_dir = root / "matrix"
    walk_forward_dir = root / "walk_forward"
    decision_dir = root / "decision"
    candles_path = root / "data" / "deep_research_candles.csv"
    root.mkdir(parents=True, exist_ok=True)

    symbol_args = ["--symbols", args.symbols]
    if args.symbols_file:
        symbol_args = ["--symbols-file", args.symbols_file]

    print("Smoke Strategy Lab deep research suite")
    print("Mode: research-only public market data")
    print("API keys: not used")
    print("Private account data: not used")
    print("Order execution: disabled / not implemented")
    print(f"Root: {root}")
    print(f"Interval: {args.interval}")
    print(f"Limit per symbol: {args.limit}")
    print(f"Walk-forward windows: {args.windows}")

    run_cmd([
        sys.executable,
        "scripts/run_binance_real_matrix.py",
        *symbol_args,
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
        *symbol_args,
        "--interval", args.interval,
        "--limit", str(args.limit),
        "--candles-out", str(root / "data" / "walk_forward_candles.csv"),
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

    print("\nDeep research suite complete")
    print("Main files:")
    for path in [
        matrix_dir / "matrix_summary.md",
        matrix_dir / "matrix_summary.csv",
        matrix_dir / "baseline_candidate" / "baseline_candidate.md",
        walk_forward_dir / "walk_forward_summary.md",
        walk_forward_dir / "walk_forward_summary.csv",
        decision_dir / "research_decision.md",
        decision_dir / "research_decision.json",
    ]:
        print(path)

    print("\nFinal decision:")
    decision_md = decision_dir / "research_decision.md"
    if decision_md.exists():
        print(decision_md.read_text(encoding="utf-8"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
