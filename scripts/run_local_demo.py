#!/usr/bin/env python3
"""One-command local demo for Smoke Strategy Lab.

Creates deterministic synthetic candles and runs the full non-live research flow:

synthetic candles -> candle pipeline -> generated trades -> integrated pipeline

Research only. No live trading. No API keys.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from strategy_lab.end_to_end_pipeline import run_end_to_end_pipeline


def make_demo_candles(path: Path, symbols: int = 6, hours: int = 1200) -> None:
    start = datetime(2025, 1, 1)
    rows: list[dict] = []
    for idx in range(symbols):
        symbol = f"DEMO{idx + 1:03d}USDT"
        price = 75.0 + idx * 18.0
        for i in range(hours):
            is_impulse = i % 12 in {0, 1, 2}
            is_pullback = i % 12 in {6, 7}
            drift = 0.14 if idx % 3 != 2 else -0.02
            impulse = 0.52 if is_impulse else -0.10 if is_pullback else 0.02
            if idx % 3 == 2:
                impulse *= -0.45
            open_p = price
            close_p = max(1.0, open_p + drift + impulse)
            high = max(open_p, close_p) + 0.85
            low = min(open_p, close_p) - 0.65
            volume = 1100 + idx * 130 + (1900 if is_impulse else 250 if is_pullback else 0)
            rows.append({
                "symbol": symbol,
                "time": (start + timedelta(hours=i)).isoformat(timespec="seconds"),
                "open": round(open_p, 6),
                "high": round(high, 6),
                "low": round(low, 6),
                "close": round(close_p, 6),
                "volume": round(volume, 6),
            })
            price = close_p

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def read_report_metric(path: Path, metric: str) -> str:
    if not path.exists():
        return "missing"
    with path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("metric") == metric:
                return str(row.get("value", ""))
    return "missing"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candles", default="data/demo_candles.csv")
    parser.add_argument("--out-dir", default="results/demo")
    parser.add_argument("--profile", default="growth_100_20x")
    parser.add_argument("--min-confidence", type=float, default=40.0)
    parser.add_argument("--symbols", type=int, default=6)
    parser.add_argument("--hours", type=int, default=1200)
    args = parser.parse_args()

    candles_path = Path(args.candles)
    out_dir = Path(args.out_dir)
    make_demo_candles(candles_path, symbols=args.symbols, hours=args.hours)

    summary = run_end_to_end_pipeline(
        candles_csv=candles_path,
        out_dir=out_dir,
        profile=args.profile,
        min_confidence=args.min_confidence,
    )

    candle_report = out_dir / "candle_research_report.csv"
    print("Smoke Strategy Lab local demo complete")
    print(f"Candles: {candles_path}")
    print(f"Reports: {out_dir}")
    print("--- End-to-end summary ---")
    for key, value in asdict(summary).items():
        print(f"{key}: {value}")
    print("--- Candle report highlights ---")
    for metric in ["winrate_pct", "avg_r", "total_r", "best_setup_type", "worst_setup_type", "best_risk_grade", "most_common_exit"]:
        print(f"{metric}: {read_report_metric(candle_report, metric)}")
    print("--- Key files ---")
    for name in [
        "end_to_end_summary.csv",
        "candle_research_report.csv",
        "candle_exit_diagnostics.csv",
        "generated_trades.csv",
        "pipeline_summary.csv",
        "pipeline_risk_diagnostics.csv",
    ]:
        print(out_dir / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
