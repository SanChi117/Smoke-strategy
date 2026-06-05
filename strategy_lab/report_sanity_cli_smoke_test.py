#!/usr/bin/env python3
"""Smoke test for standalone report sanity checker CLI."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_base_reports(out: Path) -> None:
    write_csv(out / "data_quality_summary.csv", [{
        "symbols": 2,
        "candles": 240,
        "errors": 0,
        "warnings": 0,
        "duplicate_candles": 0,
        "missing_gaps": 0,
        "invalid_ohlcv": 0,
        "under_min_history_symbols": 0,
        "status": "OK",
    }])
    write_csv(out / "end_to_end_summary.csv", [{
        "profile": "growth_100_20x",
        "candles": 240,
        "features": 200,
        "candidates": 10,
        "risk_plans": 10,
        "generated_trades": 10,
        "pipeline_candidates": 10,
        "allowed_candidates": 4,
        "executed_trades": 2,
        "final_cash": 101.0,
        "ret_pct": 1.0,
        "max_dd_pct": -0.5,
        "pf": 1.2,
        "winrate": 50.0,
        "avg_risk_pct": 0.75,
        "paper_signals": 10,
        "paper_filled": 10,
        "paper_closed": 10,
        "paper_avg_pnl_pct": 0.5,
        "sanity_status": "OK",
        "sanity_errors": 0,
        "sanity_warnings": 0,
    }])
    write_csv(out / "candle_research_report.csv", [
        {"metric": "avg_r", "value": "0.15", "note": "Average R"},
        {"metric": "time_stop_count", "value": "1", "note": "Time stops"},
        {"metric": "simulated_exits", "value": "10", "note": "Exits"},
    ])


def run_check(out: Path, expected_returncode: int = 0) -> dict[str, str]:
    cmd = [sys.executable, "scripts/check_report_sanity.py", "--out-dir", str(out)]
    result = subprocess.run(cmd, cwd=Path.cwd(), text=True, capture_output=True, timeout=30)
    print(result.stdout)
    if result.returncode != expected_returncode:
        print(result.stderr)
    assert result.returncode == expected_returncode, result.stderr
    summary_path = out / "report_sanity_summary.csv"
    issues_path = out / "report_sanity_issues.csv"
    assert summary_path.exists(), "missing report_sanity_summary.csv"
    assert issues_path.exists(), "missing report_sanity_issues.csv"
    return read_rows(summary_path)[0]


def write_decision(out: Path, decision: str, reason: str, approved: int, watch: int, rejected: int, avg_pnl_pct: float) -> None:
    positions = approved + watch + rejected
    approved_pct = round(approved / positions * 100.0, 4) if positions else 0.0
    rejected_pct = round(rejected / positions * 100.0, 4) if positions else 0.0
    write_csv(out / "paper" / "paper_decision_summary.csv", [{
        "decision": decision,
        "positions": positions,
        "approved": approved,
        "watch": watch,
        "rejected": rejected,
        "approved_pct": approved_pct,
        "rejected_pct": rejected_pct,
        "avg_pnl_pct": avg_pnl_pct,
        "reason": reason,
    }])


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "results"
        write_base_reports(out)
        write_decision(out, "PASS", "all_paper_trades_approved", 10, 0, 0, 0.5)
        summary = run_check(out)
        assert summary["status"] == "OK", summary
        assert summary["errors"] == "0", summary

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "results"
        write_base_reports(out)
        write_decision(out, "WATCH", "watch_paper_trades_present", 8, 2, 0, 0.3)
        summary = run_check(out)
        assert summary["status"] == "WARN", summary
        assert summary["warnings"] == "1", summary

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "results"
        write_base_reports(out)
        write_decision(out, "BLOCK", "rejected_paper_trades_present", 7, 1, 2, -0.1)
        summary = run_check(out, expected_returncode=1)
        assert summary["status"] == "FAIL", summary
        assert summary["errors"] == "1", summary
    print("REPORT SANITY CLI SMOKE TEST OK")


if __name__ == "__main__":
    main()
