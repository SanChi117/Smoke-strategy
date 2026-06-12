#!/usr/bin/env python3
"""Fast tagged MTF matrix.

This is a runtime-safe validation entrypoint after switching to 15m entry data
with 1D/4H context. It keeps the full tagged universe, but does not run the old
large control matrix. Only current MTF/v5 candidates are compared.

Research only. No API keys. No private data. No order execution.
"""

from __future__ import annotations

import run_binance_real_matrix as matrix
import run_binance_tagged_universe_matrix as tagged


MTF_FAST_CONFIGS = [
    item
    for item in tagged.correction_pack_v5_configs()
    if item["name"] in {
        "TAGGED_LOGIC_TREND_LIQ_NO_RANGE_ROTATION_V5",
        "TAGGED_LOGIC_TREND_LIQ_NO_RANGE_NO_IGNITION_V5",
        "TAGGED_LOGIC_TREND_LIQ_DISCOVERY_STRICT_V5",
    }
]


def main() -> int:
    matrix.MATRIX_CONFIGS = MTF_FAST_CONFIGS
    print("Tagged MTF fast matrix mode")
    print("Universe/tags: unchanged")
    print("Context: 1D/4H market context")
    print("Entry timeframe: caller interval, expected 15m")
    print("Configs: " + ", ".join(str(item["name"]) for item in MTF_FAST_CONFIGS))
    return matrix.main()


if __name__ == "__main__":
    raise SystemExit(main())
