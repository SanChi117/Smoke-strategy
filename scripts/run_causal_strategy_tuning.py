#!/usr/bin/env python3
"""Run a focused causal tuning iteration on pullback-short candidates.

This is intentionally a staged research run:
- a broad but reduced universe for iteration speed;
- strict out-of-sample WFO boundaries;
- only strategy variants justified by prior fold diagnostics;
- no live/paper promotion and no order execution.
"""

from __future__ import annotations

import sys

import run_causal_paper_review_validation as suite


TUNING_CANDIDATES = (
    "TAGGED_PULLBACK_SHORT_BALANCED_V1,"
    "TAGGED_PULLBACK_SHORT_NEUTRAL_INDECISION_V1,"
    "TAGGED_PULLBACK_SHORT_INDECISION_V1,"
    "TAGGED_PULLBACK_SHORT_INDECISION_VR09_V1,"
    "TAGGED_PULLBACK_SHORT_STRICT_V1"
)


def main() -> int:
    suite.FAST_CANDIDATES = TUNING_CANDIDATES
    if len(sys.argv) == 1:
        sys.argv.extend([
            "--top-n-per-group", "5",
            "--interval", "15m",
            "--limit", "4500",
            "--windows", "4",
            "--lookback-days", "21",
            "--deep-limit", "6000",
            "--deep-windows", "4",
            "--deep-lookback-days", "30",
            "--root", "results/causal_strategy_tuning_v1",
            "--layer-root", "results/causal_strategy_tuning_universe_v1",
            "--sleep-sec", "0.02",
        ])
    print("SMOKE causal strategy tuning iteration v1", flush=True)
    print("Candidates: " + TUNING_CANDIDATES, flush=True)
    print("Real orders: disabled", flush=True)
    return suite.main()


if __name__ == "__main__":
    raise SystemExit(main())
