#!/usr/bin/env python3
"""Focused long-history test for the balanced resumption hypothesis."""

from __future__ import annotations

import run_causal_long_history_sweep as sweep


CANDIDATE_NAME = "LONGHIST_RESUMPTION_BALANCED_V1"


def main() -> int:
    selected = [item for item in sweep.CANDIDATES if str(item.get("name")) == CANDIDATE_NAME]
    if len(selected) != 1:
        raise RuntimeError(f"Expected one {CANDIDATE_NAME} config, found {len(selected)}")
    sweep.CANDIDATES = selected
    return sweep.main()


if __name__ == "__main__":
    raise SystemExit(main())
