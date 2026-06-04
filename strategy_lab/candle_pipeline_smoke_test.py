#!/usr/bin/env python3
"""Smoke test for candle-to-trades pipeline.

Checks the missing execution chain:

candles -> data quality -> features -> candidate setups -> risk plans -> candle exits -> exit diagnostics -> candle report -> generated trades

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
        for i in range(160):
            # First two symbols trend cleanly. Third is weaker/noisier.
            drift = 0.18 if idx < 2 else -0.03
            wave = 0.25 if i % 7 in {0, 1, 2} else -0.08
            open_p = price
            close_p = max(1.0, open_p + drift + wave)
            high = max(open_p, close_p) + 0.95
            low = min(open_p, close_p) - 0.70
            volume = 1000 + idx * 100 + (600 if i % 9 in {0, 1} else 0)
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
        summary = run_candle_pipeline(candles, out, min_confidence=45.0)
        print(summary)

        assert summary["candles"] > 0, "expected candles"
        assert summary["data_quality_status"] in {"OK", "WARN"}, "expected non-failing data quality"
        assert summary["data_quality_errors"] == 0, "expected no data quality errors in clean sample"
        assert summary["features"] > 0, "expected features"
        assert summary["candidates"] > 0, "expected candidate setups"
        assert summary["risk_plans"] == summary["candidates"], "risk plan count must match candidates"
        assert summary["exit_results"] == summary["risk_plans"], "exit result count must match risk plans"
        assert summary["exit_diagnostics"] > 0, "expected exit diagnostics"
        assert summary["candle_research_report"] > 0, "expected candle research report"
        assert summary["generated_trades"] == summary["risk_plans"], "generated trade count must match risk plans"

        for name in ["data_quality_summary.csv", "data_quality_report.csv", "data_quality_issues.csv", "candle_features.csv", "candidate_setups.csv", "risk_plans.csv", "candle_exit_results.csv", "candle_exit_diagnostics.csv", "candle_research_report.csv", "generated_trades.csv"]:
            path = out / name
            assert path.exists(), f"missing output: {name}"
            if name != "data_quality_issues.csv":
                assert count_rows(path) > 0, f"empty output: {name}"

        quality_summary = read_rows(out / "data_quality_summary.csv")
        quality_columns = set(quality_summary[0])
        for column in ["symbols", "candles", "errors", "warnings", "duplicate_candles", "missing_gaps", "invalid_ohlcv", "status"]:
            assert column in quality_columns, f"missing data quality summary column: {column}"
        assert quality_summary[0]["status"] in {"OK", "WARN"}, "clean sample should not fail data quality"

        quality_report = read_rows(out / "data_quality_report.csv")
        quality_report_columns = set(quality_report[0])
        for column in ["symbol", "candles", "start_time", "end_time", "inferred_interval_seconds", "duplicate_candles", "missing_gaps", "invalid_ohlcv", "status"]:
            assert column in quality_report_columns, f"missing data quality report column: {column}"

        feature_rows = read_rows(out / "candle_features.csv")
        feature_columns = set(feature_rows[0])
        for column in ["trend_direction", "trend_strength", "range_position", "volume_state", "candle_signal", "liquidity_event", "setup_quality"]:
            assert column in feature_columns, f"missing upgraded feature column: {column}"
        assert any(row["setup_bias"] in {"breakout", "pullback", "ignition", "range_rotation", "liquidity_reclaim"} for row in feature_rows), "expected at least one actionable setup bias"

        risk_rows = read_rows(out / "risk_plans.csv")
        risk_columns = set(risk_rows[0])
        for column in ["confidence_hint", "target_policy", "risk_grade", "target_rr", "stop_pct"]:
            assert column in risk_columns, f"missing upgraded risk plan column: {column}"
        assert any(row["risk_grade"] in {"A", "B", "C"} for row in risk_rows), "expected at least one tradable risk grade"

        exit_rows = read_rows(out / "candle_exit_results.csv")
        exit_columns = set(exit_rows[0])
        for column in ["exit_reason", "bars_held", "r_mult", "exit"]:
            assert column in exit_columns, f"missing candle exit column: {column}"
        assert any(row["exit_reason"] in {"take_profit", "stop_loss", "time_stop"} for row in exit_rows), "expected real candle exit reasons"

        diagnostic_rows = read_rows(out / "candle_exit_diagnostics.csv")
        diagnostic_columns = set(diagnostic_rows[0])
        for column in ["group", "value", "trades", "take_profit", "stop_loss", "time_stop", "winrate", "avg_r", "avg_bars_held"]:
            assert column in diagnostic_columns, f"missing exit diagnostic column: {column}"
        assert any(row["group"] == "all" and row["value"] == "all" for row in diagnostic_rows), "expected all/all exit diagnostic row"
        assert any(row["group"] == "setup_type" for row in diagnostic_rows), "expected setup_type exit diagnostics"
        assert any(row["group"] == "risk_grade" for row in diagnostic_rows), "expected risk_grade exit diagnostics"

        report_rows = read_rows(out / "candle_research_report.csv")
        report_metrics = {row["metric"] for row in report_rows}
        for metric in ["candles", "features", "candidate_setups", "risk_plans", "simulated_exits", "winrate_pct", "avg_r", "total_r", "best_setup_type", "setup_types_seen"]:
            assert metric in report_metrics, f"missing candle research report metric: {metric}"

        generated_rows = read_rows(out / "generated_trades.csv")
        generated_columns = set(generated_rows[0])
        for column in ["setup_type", "trend_context", "volatility_regime", "structure_type", "confidence_hint", "target_policy", "risk_grade", "exit_reason", "bars_held", "risk_plan_reason", "target_rr", "stop_pct"]:
            assert column in generated_columns, f"missing generated trade context column: {column}"

    print("CANDLE PIPELINE SMOKE TEST OK")


if __name__ == "__main__":
    main()
