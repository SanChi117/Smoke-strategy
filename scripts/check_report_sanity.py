#!/usr/bin/env python3
"""Check generated research reports without rerunning the strategy."""

from __future__ import annotations

import argparse
from pathlib import Path

from strategy_lab.report_sanity import ReportSanityConfig, write_report_sanity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="results")
    parser.add_argument("--min-generated-trades", type=int, default=5)
    parser.add_argument("--min-executed-trades", type=int, default=1)
    parser.add_argument("--min-candle-avg-r", type=float, default=-0.10)
    parser.add_argument("--max-time-stop-pct", type=float, default=65.0)
    parser.add_argument("--min-wfo-stability-score", type=float, default=45.0)
    parser.add_argument("--fail-on-warn", action="store_true")
    args = parser.parse_args()

    cfg = ReportSanityConfig(
        min_generated_trades=args.min_generated_trades,
        min_executed_trades=args.min_executed_trades,
        min_candle_avg_r=args.min_candle_avg_r,
        max_time_stop_pct=args.max_time_stop_pct,
        min_wfo_stability_score=args.min_wfo_stability_score,
    )
    summary = write_report_sanity(args.out_dir, cfg)
    out = Path(args.out_dir)

    print("Report sanity check complete")
    print(f"Output: {out}")
    print(f"Status: {summary.status}")
    print(f"Checks: {summary.checks}")
    print(f"Errors: {summary.errors}")
    print(f"Warnings: {summary.warnings}")
    print(out / "report_sanity_summary.csv")
    print(out / "report_sanity_issues.csv")

    if summary.status == "FAIL":
        return 1
    if args.fail_on_warn and summary.status == "WARN":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
