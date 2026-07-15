#!/usr/bin/env python3
"""Regression test for the completed-HTF context-alignment pipeline gate."""

from __future__ import annotations

import csv
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from strategy_lab.config import PipelineConfig
from strategy_lab.pipeline import run_pipeline


def write_rows(path: Path) -> None:
    start = datetime(2026, 1, 1, 12, 0)
    rows = []
    for index, alignment in enumerate(("aligned", "fallback_entry")):
        entry_time = start + timedelta(hours=index * 4)
        entry = 100.0 + index
        stop = entry * 1.01
        rows.append({
            "symbol": f"ALIGN{index}USDT",
            "side": "short",
            "entry_time": entry_time.isoformat(timespec="seconds"),
            "exit_time": (entry_time + timedelta(hours=2)).isoformat(timespec="seconds"),
            "entry": entry,
            "stop": stop,
            "exit": entry * 0.99,
            "r_mult": 1.0,
            "kind": "pullback_resumption",
            "source": "context_alignment_gate_smoke_test",
            "setup_type": "pullback_resumption",
            "trend_context": "trend",
            "volatility_regime": "normal",
            "structure_type": "trend_pullback",
            "confidence_hint": 70.0,
            "risk_plan_reason": (
                "setup=pullback_resumption|dir=down|vr=1.1|candle=neutral|"
                f"liq=none|ctx_align={alignment}"
            ),
        })
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        input_csv = root / "trades.csv"
        out = root / "out"
        write_rows(input_csv)
        cfg = replace(
            PipelineConfig(),
            name="ALIGNMENT_GATE_TEST",
            start="2025-12-01",
            end="2026-02-01",
            require_rolling_top=False,
            require_universe_gate=False,
            allowed_context_alignments=("aligned",),
        )
        run_pipeline(input_csv, out, cfg=cfg, profile_name="research_500")
        with (out / "pipeline_decisions.csv").open(newline="", encoding="utf-8") as handle:
            decisions = list(csv.DictReader(handle))
        by_symbol = {row["symbol"]: row for row in decisions}
        assert by_symbol["ALIGN0USDT"]["allowed"].lower() == "true"
        assert by_symbol["ALIGN1USDT"]["allowed"].lower() == "false"
        assert by_symbol["ALIGN1USDT"]["reason"] == "context_alignment_filtered"
    print("context_alignment_gate_smoke_test: PASS")


if __name__ == "__main__":
    main()
