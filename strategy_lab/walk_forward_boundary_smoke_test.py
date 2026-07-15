#!/usr/bin/env python3
"""Regression test: warm-up trades must never enter walk-forward P&L."""

from __future__ import annotations

import csv
import json
import tempfile
from datetime import datetime
from pathlib import Path

from strategy_lab.config import PipelineConfig
from strategy_lab.walk_forward_evaluation import evaluate_validation_window


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        generated = [
            {
                "symbol": "AAAUSDT", "side": "long",
                "entry_time": "2026-01-01T12:00:00", "exit_time": "2026-01-01T13:00:00",
                "entry": 100.0, "stop": 99.0, "exit": 102.0, "r_mult": 2.0,
                "source": "test", "kind": "pullback",
            },
            {
                "symbol": "BBBUSDT", "side": "short",
                "entry_time": "2026-01-02T12:00:00", "exit_time": "2026-01-02T13:00:00",
                "entry": 100.0, "stop": 101.0, "exit": 98.0, "r_mult": 2.0,
                "source": "test", "kind": "pullback",
            },
        ]
        decisions = [
            {
                "symbol": "AAAUSDT", "side": "long", "entry_time": "2026-01-01 12:00:00",
                "allowed": True, "reason": "allowed_full_balanced", "universe_state": "allowed",
                "quality_decision": "TAKE", "structure_decision": "TAKE", "risk_pct": 0.0075,
                "leverage": 20.0, "target_policy": "test", "setup_type": "pullback",
                "trend_context": "trend", "volatility_regime": "normal",
            },
            {
                "symbol": "BBBUSDT", "side": "short", "entry_time": "2026-01-02 12:00:00",
                "allowed": True, "reason": "allowed_full_balanced", "universe_state": "allowed",
                "quality_decision": "TAKE", "structure_decision": "TAKE", "risk_pct": 0.0075,
                "leverage": 20.0, "target_policy": "test", "setup_type": "pullback",
                "trend_context": "trend", "volatility_regime": "normal",
            },
        ]
        write_rows(root / "generated_trades.csv", generated)
        write_rows(root / "pipeline_decisions.csv", decisions)

        # Minimal structural reports used by validation helpers.
        for name in ["pipeline_universe_ranking.csv", "pipeline_risk_diagnostics.csv", "pipeline_risk_policy.csv"]:
            write_rows(root / name, [{"status": "test"}])

        summary = evaluate_validation_window(
            run_dir=root,
            validation_start=datetime(2026, 1, 2),
            validation_end=datetime(2026, 1, 3),
            profile_name="growth_100_20x",
            cfg=PipelineConfig(name="BOUNDARY_TEST"),
        )

        assert summary.candidates == 1, summary
        assert summary.allowed_candidates == 1, summary
        assert summary.executed_trades == 1, summary
        assert len(read_rows(root / "pipeline_decisions.csv")) == 1
        assert len(read_rows(root / "pipeline_decisions_with_warmup.csv")) == 2
        allowed = read_rows(root / "pipeline_allowed_trades.csv")
        assert len(allowed) == 1
        assert allowed[0]["symbol"] == "BBBUSDT"
        meta = json.loads((root / "walk_forward_evaluation_window.json").read_text(encoding="utf-8"))
        assert meta["warmup_candidates_excluded_from_pnl"] == 1
        assert meta["validation_candidates"] == 1

    print("walk_forward_boundary_smoke_test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
