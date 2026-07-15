#!/usr/bin/env python3
"""Focused long-history audit for the broad pullback-short control."""

from __future__ import annotations

import run_causal_long_history_sweep as sweep
from run_causal_long_history_sweep_cached import archive_loader


CANDIDATE_NAME = "LONGHIST_PULLBACK_SHORT_CONTROL_V1"


def main() -> int:
    selected = [item for item in sweep.CANDIDATES if str(item.get("name")) == CANDIDATE_NAME]
    if len(selected) != 1:
        raise RuntimeError(f"Expected one {CANDIDATE_NAME} config, found {len(selected)}")
    sweep.CANDIDATES = selected
    sweep.load_binance_futures_candles = archive_loader
    return sweep.main()


if __name__ == "__main__":
    raise SystemExit(main())
