#!/usr/bin/env python3
"""Smoke test for the full candle-to-integrated-pipeline flow."""

from __future__ import annotations

import csv
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from strategy_lab.end_to_end_pipeline import run_end_to_end_pipeline


def make_candles_csv(path: Path) -> None:
    start = datetime(2025, 1, 1)
    rows: list[dict] = []
    symbols = ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT"]
    for idx, symbol in enumerate(symbols):
        price = 80.0 + idx * 15.0
        # More than 30 days of hourly candles so rolling selector has enough lookback.
        for i in range(1000):
            drift = 0.16 if idx < 3 else -0.02
            impulse = 0.35 if i % 11 in {0, 1, 2} else -0.06
            open_p = price
            close_p = max(1.0, open_p + drift + impulse)
            high = max(open_p, close_p) + 0.80
            low = min(open_p, close_p) - 0.55
            volume = 1200 + idx * 150 + (350 if i % 11 in {0, 1, 2} else 0)
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


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def count_rows(path: Path) -> int:
    return len(read_rows(path))


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        candles = root / "candles.csv"
        out = root / "results"
        make_candles_csv(candles)
        summary = run_end_to_end_pipeline(candles, out, profile="growth_100_20x", min_confidence=45.0)
        print(summary)

        required = [
            "candle_features.csv",
            "candidate_setups.csv",
            "risk_plans.csv",
            "generated_trades.csv",
            "pipeline_summary.csv",
            "pipeline_decisions.csv",
            "pipeline_risk_diagnostics.csv",
            "pipeline_validation_summary.csv",
            "report_sanity_summary.csv",
            "report_sanity_issues.csv",
            "end_to_end_summary.csv",
        ]
        for name in required:
            path = out / name
            assert path.exists(), f"missing output: {name}"
            if name != "report_sanity_issues.csv":
                assert count_rows(path) > 0, f"empty output: {name}"

        paper_required = ["paper_signals.csv", "paper_journal.csv", "paper_positions.csv", "paper_summary.csv"]
        for name in paper_required:
            path = out / "paper" / name
            assert path.exists(), f"missing paper output: {name}"
            assert count_rows(path) > 0, f"empty paper output: {name}"

        sanity_summary = read_rows(out / "report_sanity_summary.csv")[0]
        end_summary = read_rows(out / "end_to_end_summary.csv")[0]
        paper_summary = read_rows(out / "paper" / "paper_summary.csv")[0]
        assert sanity_summary["status"] in {"OK", "WARN", "FAIL"}, sanity_summary
        assert "sanity_status" in end_summary, "end_to_end summary must include sanity status"
        assert "paper_signals" in end_summary, "end_to_end summary must include paper_signals"
        assert int(float(end_summary["paper_signals"])) > 0, end_summary
        assert int(float(paper_summary["paper_signals"])) == int(float(end_summary["paper_signals"])), paper_summary

        assert summary.candles > 0, "expected candles"
        assert summary.features > 0, "expected features"
        assert summary.generated_trades > 0, "expected generated trades"
        assert summary.pipeline_candidates == summary.generated_trades, "generated trades must feed pipeline candidates"
        assert summary.allowed_candidates > 0, "rolling selector should allow candidates after lookback"
        assert summary.executed_trades > 0, "dynamic portfolio should execute trades"
        assert summary.avg_risk_pct > 0, "dynamic risk should be applied"
        assert summary.paper_signals > 0, "paper mode should create signals"
        assert summary.paper_closed > 0, "paper mode should close paper positions"
        assert summary.final_cash > 0, "final cash must stay positive"

    print("END-TO-END SMOKE TEST OK")


if __name__ == "__main__":
    main()
