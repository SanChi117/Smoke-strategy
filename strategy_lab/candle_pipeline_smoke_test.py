#!/usr/bin/env python3
"""Smoke test for candle-to-trades pipeline.

Checks the missing execution chain:

candles -> features -> candidate setups -> risk plans -> generated trades

Research only. No live trading. No API keys.
"""

from __future__ import annotations

import csv
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from strategy_lab.candle_pipeline import run_candle_pipeline


def make_candles_csv(path: Path) -> None:
    start = datetime(2025, 1, 1)
    rows: list[dict] = []
    symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT"]
    for idx, symbol in enumerate(symbols):
        price = 100.0 + idx * 20.0
        for i in range(140):
            # First two symbols trend cleanly. Third is weaker/noisier.
            drift = 0.18 if idx < 2 else -0.03
            wave = 0.25 if i % 7 in {0, 1, 2} else -0.08
            open_p = price
            close_p = max(1.0, open_p + drift + wave)
            high = max(open_p, close_p) + 0.75
            low = min(open_p, close_p) - 0.55
            volume = 1000 + idx * 100 + (250 if i % 9 == 0 else 0)
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
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def count_rows(path: Path) -> int:
    with path.open("r", newline="", encoding="utf-8") as f:
        return max(0, sum(1 for _ in csv.DictReader(f)))


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        candles = root / "candles.csv"
        out = root / "results"
        make_candles_csv(candles)
        summary = run_candle_pipeline(candles, out, min_confidence=45.0)
        print(summary)

        assert summary["candles"] > 0, "expected candles"
        assert summary["features"] > 0, "expected features"
        assert summary["candidates"] > 0, "expected candidate setups"
        assert summary["risk_plans"] == summary["candidates"], "risk plan count must match candidates"
        assert summary["generated_trades"] == summary["risk_plans"], "generated trade count must match risk plans"

        for name in ["candle_features.csv", "candidate_setups.csv", "risk_plans.csv", "generated_trades.csv"]:
            path = out / name
            assert path.exists(), f"missing output: {name}"
            assert count_rows(path) > 0, f"empty output: {name}"

    print("CANDLE PIPELINE SMOKE TEST OK")


if __name__ == "__main__":
    main()
