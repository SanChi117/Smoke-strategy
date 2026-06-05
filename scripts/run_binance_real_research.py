#!/usr/bin/env python3
"""Run a complete real Binance public-data research pass in one command.

This script downloads public candles, runs the end-to-end research pipeline,
and writes a compact research diagnosis.

It does not use API keys, private account data, or order endpoints.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from analyze_research_reports import build_diagnosis  # noqa: E402
from strategy_lab.binance_market_data import load_binance_futures_candles, parse_symbols
from strategy_lab.end_to_end_pipeline import run_end_to_end_pipeline


DEFAULT_SYMBOLS = "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,LINKUSDT,AVAXUSDT,TONUSDT"


def read_symbols_file(path: str | Path) -> list[str]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Symbols file not found: {p}")
    return parse_symbols(p.read_text(encoding="utf-8"))


def resolve_symbols(symbols_arg: str | None, symbols_file: str | None) -> list[str]:
    symbols: list[str] = []
    if symbols_arg:
        symbols.extend(parse_symbols(symbols_arg))
    if symbols_file:
        symbols.extend(read_symbols_file(symbols_file))
    if not symbols:
        symbols.extend(parse_symbols(DEFAULT_SYMBOLS))

    seen: set[str] = set()
    unique: list[str] = []
    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            unique.append(symbol)
    return unique


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Binance public-data research pass for Smoke Strategy Lab.")
    parser.add_argument("--symbols", default=None, help="Comma/newline separated symbols")
    parser.add_argument("--symbols-file", default=None, help="Text file with comma/newline separated symbols")
    parser.add_argument("--interval", default="1h", help="Binance kline interval, e.g. 15m, 1h, 4h, 1d")
    parser.add_argument("--limit", type=int, default=1000, help="Candles per symbol. Binance public endpoint caps this at 1500.")
    parser.add_argument("--candles-out", default="data/binance_real_candles.csv", help="Downloaded candles CSV path")
    parser.add_argument("--out-dir", default="results/binance_real", help="Research report output directory")
    parser.add_argument("--profile", default="growth_100_20x", help="Risk/money-management profile")
    parser.add_argument("--min-confidence", type=float, default=40.0, help="Minimum setup confidence")
    parser.add_argument("--sleep-sec", type=float, default=0.05, help="Delay between symbols")
    args = parser.parse_args()

    symbols = resolve_symbols(args.symbols, args.symbols_file)
    if not symbols:
        raise SystemExit("No symbols provided.")

    print("Smoke Strategy Lab Binance real research")
    print("Mode: research-only public market data")
    print("API keys: not used")
    print("Private account data: not used")
    print("Order execution: disabled / not implemented")
    print(f"Symbols: {len(symbols)}")
    print(f"Interval: {args.interval}")
    print(f"Limit per symbol: {args.limit}")
    print(f"Candles output: {args.candles_out}")
    print(f"Research output: {args.out_dir}")

    market_summary = load_binance_futures_candles(
        symbols=symbols,
        out_csv=args.candles_out,
        interval=args.interval,
        limit=args.limit,
        sleep_sec=args.sleep_sec,
    )
    print("\nMarket data summary")
    for key, value in asdict(market_summary).items():
        print(f"{key}: {value}")

    if market_summary.status != "OK":
        raise SystemExit(1)

    research_summary = run_end_to_end_pipeline(
        candles_csv=args.candles_out,
        out_dir=args.out_dir,
        profile=args.profile,
        min_confidence=args.min_confidence,
    )
    print("\nResearch summary")
    for key, value in asdict(research_summary).items():
        print(f"{key}: {value}")

    out_dir = Path(args.out_dir)
    diagnosis, flags = build_diagnosis(out_dir)
    diagnosis_path = out_dir / "research_diagnosis.md"
    diagnosis_path.write_text(diagnosis, encoding="utf-8")
    print("\nResearch diagnosis")
    print(diagnosis)

    print("\nMain report files")
    for name in [
        "research_diagnosis.md",
        "end_to_end_summary.csv",
        "report_sanity_summary.csv",
        "report_sanity_issues.csv",
        "candle_research_report.csv",
        "pipeline_summary.csv",
        "pipeline_risk_diagnostics.csv",
        "paper/paper_decision_summary.csv",
    ]:
        print(out_dir / name)

    if "SANITY_FAIL" in flags or "PAPER_BLOCK" in flags:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
