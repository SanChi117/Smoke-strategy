#!/usr/bin/env python3
"""Ensure tactical filters survive matrix -> baseline promotion."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from promote_matrix_baseline import normalize_row  # noqa: E402


def main() -> None:
    row = {
        "name": "ROUNDTRIP",
        "score": "1",
        "rolling_top_n": "8",
        "require_rolling_top": "false",
        "require_universe_gate": "false",
        "min_confidence": "45",
        "quality_take_threshold": "64",
        "quality_watch_threshold": "52",
        "structure_take_threshold": "63",
        "structure_watch_threshold": "52",
        "min_volume_ratio": "0.9",
        "generated_trades": "100",
        "allowed_candidates": "10",
        "allowed_pct": "10",
        "executed_trades": "8",
        "ret_pct": "2",
        "max_dd_pct": "1",
        "pf": "1.4",
        "winrate": "55",
        "avg_risk_pct": "0.005",
        "sanity_status": "OK",
        "diagnosis_flags": "",
        "out_dir": "results/example",
        "allowed_context_alignments_filter": "aligned;h4_only",
        "blocked_context_alignments_filter": "conflict",
    }
    candidate = normalize_row(row)
    assert candidate["allowed_context_alignments"] == ["aligned", "h4_only"]
    assert candidate["blocked_context_alignments"] == ["conflict"]
    assert candidate["require_rolling_top"] is False
    assert candidate["require_universe_gate"] is False
    print("baseline_filter_roundtrip_smoke_test: PASS")


if __name__ == "__main__":
    main()
