#!/usr/bin/env python3
"""Quick strict-OOS sweep for the pullback-resumption family.

This is a screening stage only. A positive result is never enough for promotion.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


CANDIDATES = (
    "TAGGED_PULLBACK_SHORT_BALANCED_V1,"
    "TAGGED_PULLBACK_RESUMPTION_BOTH_V1,"
    "TAGGED_PULLBACK_RESUMPTION_BALANCED_V1,"
    "TAGGED_PULLBACK_RESUMPTION_STRICT_V1,"
    "TAGGED_PULLBACK_RESUMPTION_BOTH_VR09_V1"
)


def run(cmd: list[str]) -> None:
    print("\n$ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main() -> int:
    root = Path("results/causal_quick_sweep_v3")
    universe = Path("results/causal_quick_sweep_universe_v3")
    matrix = root / "matrix"
    multi = root / "multi_wfo"
    data = root / "data"
    symbols = universe / "combined_symbols.txt"

    run([
        sys.executable, "scripts/build_strategy_universe_layer.py",
        "--top-n-per-group", "4",
        "--out-dir", str(universe),
    ])
    run([
        sys.executable, "scripts/run_binance_resumption_matrix.py",
        "--symbols-file", str(symbols),
        "--interval", "15m",
        "--limit", "4500",
        "--candles-out", str(data / "matrix_candles.csv"),
        "--out-dir", str(matrix),
        "--profile", "growth_100_20x",
        "--sleep-sec", "0.02",
    ])
    run([
        sys.executable, "scripts/run_tagged_multi_wfo_cached.py",
        "--matrix", str(matrix / "matrix_summary.csv"),
        "--symbols-file", str(symbols),
        "--out-dir", str(multi),
        "--candidate-names", CANDIDATES,
        "--interval", "15m",
        "--limit", "4500",
        "--windows", "3",
        "--lookback-days", "21",
        "--profile", "growth_100_20x",
        "--sleep-sec", "0.02",
    ])
    print("Quick strict-OOS resumption sweep complete", flush=True)
    print(multi / "tagged_multi_wfo_best.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
