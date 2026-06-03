#!/usr/bin/env python3
"""Smoke test for the integrated Smoke Strategy pipeline.

The goal is not to prove profitability. The goal is to prove that the full
pipeline skeleton executes end-to-end and produces valid non-empty reports.

Research only. No live trading. No API keys.
"""

from __future__ import annotations

import csv
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from strategy_lab.pipeline import run_pipeline


def make_pipeline_sample_csv(path: Path) -> None:
    start = datetime(2025, 1, 1)
    rows: list[dict] = []
    symbols = [f"SYM{i:03d}USDT" for i in range(1, 9)]

    for day in range(180):
        for idx, symbol in enumerate(symbols):
            entry_time = start + timedelta(days=day, hours=(idx * 2) % 18)
            exit_time = entry_time + timedelta(hours=8)
            side = "long" if (day + idx) % 2 == 0 else "short"

            # First four symbols are intentionally cleaner. Last four are noisy.
            if idx < 4:
                r_mult = 1.15 if day % 4 != 0 else -1.0
                trend_context = "trend"
                structure_type = "continuation"
                setup_type = "runner"
            else:
                r_mult = -1.0 if day % 3 != 0 else 1.05
                trend_context = "countertrend"
                structure_type = "countertrend_reaction"
                setup_type = "runner"

            entry = 100.0 + idx * 4.0
            risk = entry * 0.018
            if side == "long":
                stop = entry - risk
                exit_price = entry + r_mult * risk
            else:
                stop = entry + risk
                exit_price = entry - r_mult * risk

            rows.append({
                "symbol": symbol,
                "side": side,
                "entry_time": entry_time.isoformat(timespec="seconds"),
                "exit_time": exit_time.isoformat(timespec="seconds"),
                "entry": round(entry, 6),
                "stop": round(stop, 6),
                "exit": round(exit_price, 6),
                "r_mult": round(r_mult, 6),
                "kind": "runner",
                "source": "pipeline_smoke_test",
                "setup_type": setup_type,
                "trend_context": trend_context,
                "volatility_regime": "normal",
                "structure_type": structure_type,
            })

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def count_csv_rows(path: Path) -> int:
    with path.open("r", newline="", encoding="utf-8") as f:
        return max(0, sum(1 for _ in csv.DictReader(f)))


def first_csv_row(path: Path) -> dict[str, str]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return next(csv.DictReader(f), {})


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        input_csv = root / "pipeline_sample_trades.csv"
        out_dir = root / "results"
        make_pipeline_sample_csv(input_csv)

        summary = run_pipeline(input_csv=input_csv, out_dir=out_dir, profile_name="growth_100_20x")
        print(summary)

        summary_path = out_dir / "pipeline_summary.csv"
        universe_path = out_dir / "pipeline_universe_ranking.csv"
        decisions_path = out_dir / "pipeline_decisions.csv"
        diagnostics_path = out_dir / "pipeline_risk_diagnostics.csv"
        policy_path = out_dir / "pipeline_risk_policy.csv"
        validation_summary_path = out_dir / "pipeline_validation_summary.csv"
        validation_issues_path = out_dir / "pipeline_validation_issues.csv"

        assert summary_path.exists(), "pipeline summary was not created"
        assert universe_path.exists(), "pipeline universe ranking was not created"
        assert decisions_path.exists(), "pipeline decisions were not created"
        assert diagnostics_path.exists(), "pipeline risk diagnostics were not created"
        assert policy_path.exists(), "pipeline risk policy was not created"
        assert validation_summary_path.exists(), "pipeline validation summary was not created"
        assert validation_issues_path.exists(), "pipeline validation issues file was not created"

        assert summary.profile == "growth_100_20x", "wrong risk profile"
        assert summary.initial_cash == 100.0, "wrong initial cash"
        assert summary.leverage == 20.0, "wrong leverage"
        assert summary.candidates > 0, "expected candidate trades"
        assert summary.allowed_candidates > 0, "expected allowed candidates"
        assert summary.executed_trades > 0, "expected executed trades"
        assert summary.avg_risk_pct > 0, "dynamic risk was not applied"
        assert summary.final_cash > 0, "final cash must stay positive"

        assert count_csv_rows(summary_path) == 1, "summary must contain exactly one row"
        assert count_csv_rows(universe_path) > 0, "universe ranking must not be empty"
        assert count_csv_rows(decisions_path) == summary.candidates, "decisions must cover every candidate"
        assert count_csv_rows(diagnostics_path) > 0, "risk diagnostics must not be empty"
        assert count_csv_rows(policy_path) > 0, "risk policy must not be empty"
        assert count_csv_rows(validation_summary_path) == 1, "validation summary must contain exactly one row"
        assert first_csv_row(validation_summary_path).get("status") in {"OK", "WARN"}, "validation must not fail"

    print("PIPELINE SMOKE TEST OK")


if __name__ == "__main__":
    main()
