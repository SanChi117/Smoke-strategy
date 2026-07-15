#!/usr/bin/env python3
"""Multi-candidate WFO with one shared market-data download.

Outputs are compatible with run_tagged_multi_wfo.py, but every candidate uses the
same immutable candles CSV. This is faster and removes data-timestamp drift between
candidate runs.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import run_tagged_multi_wfo as legacy
from promote_matrix_baseline import normalize_row
from strategy_lab.binance_market_data import load_binance_futures_candles, parse_symbols


def read_symbols(path: str | Path) -> list[str]:
    return parse_symbols(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Run cached multi-WFO comparison.")
    ap.add_argument("--matrix", default="results/tagged_universe_research/matrix/matrix_summary.csv")
    ap.add_argument("--symbols-file", default="results/strategy_universe_layer/combined_symbols.txt")
    ap.add_argument("--out-dir", default="results/tagged_universe_research/multi_wfo")
    ap.add_argument("--candidate-names", default=legacy.DEFAULT_CANDIDATES)
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--limit", type=int, default=1500)
    ap.add_argument("--windows", type=int, default=4)
    ap.add_argument("--lookback-days", type=int, default=30)
    ap.add_argument("--profile", default="growth_100_20x")
    ap.add_argument("--sleep-sec", type=float, default=0.05)
    args = ap.parse_args()

    matrix_rows = legacy.read_csv(args.matrix)
    if not matrix_rows:
        raise SystemExit(f"No matrix rows found: {args.matrix}")
    candidates = legacy.select_rows(matrix_rows, legacy.parse_names(args.candidate_names))
    if not candidates:
        raise SystemExit("No candidates selected for cached multi-WFO")

    out = Path(args.out_dir)
    baselines_dir = out / "baselines"
    baselines_dir.mkdir(parents=True, exist_ok=True)
    shared_candles = out / "shared_walk_forward_candles.csv"
    symbols = read_symbols(args.symbols_file)

    print("Downloading one immutable candles dataset for all candidates", flush=True)
    market = load_binance_futures_candles(
        symbols=symbols,
        out_csv=shared_candles,
        interval=args.interval,
        limit=args.limit,
        sleep_sec=args.sleep_sec,
    )
    if market.status != "OK":
        raise SystemExit(f"Shared market load failed: {market}")

    summary_rows: list[dict[str, object]] = []
    for row in candidates:
        name = str(row.get("name", "")).strip()
        slug = legacy.safe_name(name)
        baseline = normalize_row(row)
        baseline["source_matrix"] = str(args.matrix)
        baseline["shared_wfo_candles"] = str(shared_candles)
        baseline_path = baselines_dir / f"{slug}.json"
        baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        candidate_out = out / slug
        env = os.environ.copy()
        env["SMOKE_WFO_CANDLES_SOURCE"] = str(shared_candles.resolve())
        command = [
            sys.executable,
            "scripts/run_binance_walk_forward_cached.py",
            "--symbols-file", args.symbols_file,
            "--interval", args.interval,
            "--limit", str(args.limit),
            "--candles-out", str(candidate_out / "walk_forward_candles.csv"),
            "--out-dir", str(candidate_out),
            "--baseline", str(baseline_path),
            "--profile", args.profile,
            "--windows", str(args.windows),
            "--lookback-days", str(args.lookback_days),
            "--sleep-sec", "0",
        ]
        print("\n$ " + " ".join(command), flush=True)
        subprocess.run(command, check=True, env=env)

        wfo = legacy.summarize_wfo(candidate_out / "walk_forward_summary.csv")
        result: dict[str, object] = {
            "name": name,
            "baseline_path": str(baseline_path),
            "wfo_out_dir": str(candidate_out),
            "matrix_score": legacy.to_float(row.get("score")),
            "matrix_ret_pct": legacy.to_float(row.get("ret_pct")),
            "matrix_pf": legacy.to_float(row.get("pf")),
            "matrix_dd_pct": legacy.to_float(row.get("max_dd_pct")),
            "matrix_executed_trades": legacy.to_int(row.get("executed_trades")),
            "matrix_allowed_pct": legacy.to_float(row.get("allowed_pct")),
            "matrix_sanity_status": row.get("sanity_status", ""),
            "matrix_diagnosis_flags": row.get("diagnosis_flags", ""),
            "shared_candles": str(shared_candles),
            **wfo,
        }
        result["multi_wfo_score"] = legacy.score_candidate(result)
        summary_rows.append(result)

    ranked = sorted(summary_rows, key=lambda row: legacy.to_float(row.get("multi_wfo_score")), reverse=True)
    legacy.write_csv(out / "tagged_multi_wfo_summary.csv", ranked)
    legacy.write_md(out / "tagged_multi_wfo_summary.md", ranked)
    if ranked:
        (out / "tagged_multi_wfo_best.json").write_text(
            json.dumps(ranked[0], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(out / "tagged_multi_wfo_summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
