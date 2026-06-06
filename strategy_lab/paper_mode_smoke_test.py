#!/usr/bin/env python3
"""Smoke test for paper mode lifecycle, review and decision summary."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path


def write_trades(path: Path) -> None:
    rows = [
        {"symbol": "AAAUSDT", "side": "long", "entry_time": "2025-01-01T00:00:00", "exit_time": "2025-01-01T02:00:00", "entry": 100, "exit": 104, "stop": 98, "target": 104, "setup_type": "breakout", "risk_grade": "A", "target_policy": "rr", "exit_reason": "take_profit"},
        {"symbol": "BBBUSDT", "side": "long", "entry_time": "2025-01-01T01:00:00", "exit_time": "2025-01-01T03:00:00", "entry": 80, "exit": 78, "stop": 78, "target": 84, "setup_type": "pullback", "risk_grade": "B", "target_policy": "rr", "exit_reason": "stop_loss"},
        {"symbol": "CCCUSDT", "side": "long", "entry_time": "2025-01-01T04:00:00", "exit_time": "2025-01-01T06:00:00", "entry": 50, "exit": 52, "stop": 49, "kind": "continuation", "r_mult": 2.0, "exit_reason": "take_profit"},
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        trades = root / "generated_trades.csv"
        out = root / "paper"
        write_trades(trades)
        cmd = [sys.executable, "scripts/run_paper_mode.py", "--generated-trades", str(trades), "--out-dir", str(out)]
        result = subprocess.run(cmd, cwd=Path.cwd(), text=True, capture_output=True, timeout=30)
        print(result.stdout)
        assert result.returncode == 0, result.stderr
        signals = read_rows(out / "paper_signals.csv")
        journal = read_rows(out / "paper_journal.csv")
        positions = read_rows(out / "paper_positions.csv")
        review = read_rows(out / "paper_review.csv")
        review_summary = read_rows(out / "paper_review_summary.csv")[0]
        decision_summary = read_rows(out / "paper_decision_summary.csv")[0]
        summary = read_rows(out / "paper_summary.csv")[0]
        assert len(signals) == 3, signals
        assert len(journal) == 9, journal
        assert len(positions) == 3, positions
        assert len(review) == 3, review
        assert signals[0]["status"] == "OPEN_SIGNAL", signals
        assert signals[2]["target"] == "52.0", signals
        assert signals[2]["setup_type"] == "continuation", signals
        assert {row["event"] for row in journal} == {"OPEN_SIGNAL", "FILLED_PAPER", "CLOSED_PAPER"}, journal
        assert {row["status"] for row in positions} == {"CLOSED_PAPER"}, positions
        assert positions[0]["close_reason"] == "take_profit", positions
        assert positions[1]["close_reason"] == "stop_loss", positions
        assert positions[2]["close_reason"] == "take_profit", positions
        assert {row["review_status"] for row in review} == {"APPROVED", "REJECTED", "WATCH"}, review
        assert review_summary["positions"] == "3", review_summary
        assert review_summary["approved"] == "1", review_summary
        assert review_summary["watch"] == "1", review_summary
        assert review_summary["rejected"] == "1", review_summary
        assert decision_summary["decision"] == "WATCH", decision_summary
        assert decision_summary["positions"] == "3", decision_summary
        assert decision_summary["approved"] == "1", decision_summary
        assert decision_summary["watch"] == "1", decision_summary
        assert decision_summary["rejected"] == "1", decision_summary
        assert decision_summary["reason"] == "paper_sample_too_small", decision_summary
        assert summary["paper_signals"] == "3", summary
        assert summary["filled_paper"] == "3", summary
        assert summary["closed_paper"] == "3", summary
        assert summary["winners"] == "2", summary
        assert summary["losers"] == "1", summary
        assert summary["review_approved"] == "1", summary
        assert summary["review_watch"] == "1", summary
        assert summary["review_rejected"] == "1", summary
        assert summary["review_status"] == "REVIEW", summary
        assert summary["status"] == "OK", summary
    print("PAPER MODE SMOKE TEST OK")


if __name__ == "__main__":
    main()
