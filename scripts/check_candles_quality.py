#!/usr/bin/env python3
"""Check OHLCV candle CSV quality without running the strategy."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from strategy_lab.data_quality import DataQualityConfig, analyze_data_quality, rows_as_dicts
from strategy_lab.market_data import read_candles_csv


def write_dict_csv(path: str | Path, rows: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", required=True)
    parser.add_argument("--out-dir", default="results/data_quality")
    parser.add_argument("--min-candles", type=int, default=100)
    parser.add_argument("--min-symbols", type=int, default=1)
    parser.add_argument("--max-gap-multiplier", type=float, default=1.5)
    parser.add_argument("--fail-on-warn", action="store_true")
    args = parser.parse_args()

    candles = read_candles_csv(args.candles)
    cfg = DataQualityConfig(
        min_candles_per_symbol=args.min_candles,
        max_missing_gap_multiplier=args.max_gap_multiplier,
        min_symbols=args.min_symbols,
    )
    summary, coverage, issues = analyze_data_quality(candles, cfg)
    out = Path(args.out_dir)
    write_dict_csv(out / "data_quality_summary.csv", rows_as_dicts([summary]))
    write_dict_csv(out / "data_quality_report.csv", rows_as_dicts(coverage))
    write_dict_csv(out / "data_quality_issues.csv", rows_as_dicts(issues))

    print("Candle data quality check complete")
    print(f"Input: {args.candles}")
    print(f"Output: {out}")
    print(f"Symbols: {summary.symbols}")
    print(f"Candles: {summary.candles}")
    print(f"Status: {summary.status}")
    print(f"Errors: {summary.errors}")
    print(f"Warnings: {summary.warnings}")
    print(f"Duplicate candles: {summary.duplicate_candles}")
    print(f"Missing gaps: {summary.missing_gaps}")
    print(f"Invalid OHLCV: {summary.invalid_ohlcv}")

    if summary.status == "FAIL":
        return 1
    if args.fail_on_warn and summary.status == "WARN":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
