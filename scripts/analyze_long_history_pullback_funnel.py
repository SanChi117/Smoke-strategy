#!/usr/bin/env python3
"""Summarize rejection reasons only for the pullback family in committed long-history OOS folds.

Research diagnostic only. No market requests, API keys, or orders.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("results/causal_long_history_sweep_v1/folds")
CANDIDATE = "LONGHIST_PULLBACK_SHORT_CONTROL_V1"
PULLBACK_FAMILY = {"pullback", "pullback_resumption", "pullback_resumption_strict"}


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    aggregate_reasons: Counter[str] = Counter()
    aggregate_setups: Counter[str] = Counter()
    aggregate_quality: Counter[str] = Counter()
    aggregate_structure: Counter[str] = Counter()
    fold_rows: list[dict[str, object]] = []

    for fold in sorted(ROOT.glob("fold_*")):
        run_dir = fold / "candidates" / CANDIDATE
        decisions = read_rows(run_dir / "pipeline_decisions.csv")
        pullbacks = [row for row in decisions if str(row.get("setup_type", "")).strip().lower() in PULLBACK_FAMILY]
        reasons = Counter(str(row.get("reason", "unknown")) for row in pullbacks)
        setups = Counter(str(row.get("setup_type", "unknown")) for row in pullbacks)
        quality = Counter(str(row.get("quality_decision", "unknown")) for row in pullbacks)
        structure = Counter(str(row.get("structure_decision", "unknown")) for row in pullbacks)
        allowed = sum(str(row.get("allowed", "")).strip().lower() in {"1", "true", "yes"} for row in pullbacks)

        aggregate_reasons.update(reasons)
        aggregate_setups.update(setups)
        aggregate_quality.update(quality)
        aggregate_structure.update(structure)
        fold_rows.append({
            "fold": fold.name,
            "pullback_candidates": len(pullbacks),
            "allowed": allowed,
            "reasons": dict(sorted(reasons.items())),
            "setups": dict(sorted(setups.items())),
            "quality": dict(sorted(quality.items())),
            "structure": dict(sorted(structure.items())),
        })

    result = {
        "candidate": CANDIDATE,
        "folds": fold_rows,
        "aggregate": {
            "pullback_candidates": sum(int(row["pullback_candidates"]) for row in fold_rows),
            "allowed": sum(int(row["allowed"]) for row in fold_rows),
            "reasons": dict(sorted(aggregate_reasons.items())),
            "setups": dict(sorted(aggregate_setups.items())),
            "quality": dict(sorted(aggregate_quality.items())),
            "structure": dict(sorted(aggregate_structure.items())),
        },
    }
    out = Path("results/causal_long_history_sweep_v1/pullback_funnel_summary.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
