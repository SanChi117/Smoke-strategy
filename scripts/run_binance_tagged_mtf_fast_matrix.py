#!/usr/bin/env python3
"""Fast tagged MTF matrix.

This is a runtime-safe validation entrypoint after switching to 15m entry data
with 1D/4H context. It keeps the full tagged universe, but does not run the old
large control matrix.

Important correction: old v5 used blocked_direction_contexts=up, which was a
micro-context filter on 1h. After MTF, direction is 1D/4H market direction, so
blocking up breaks long context and creates short bias. The MTF configs below do
not block up/down direction; they only keep setup/vol/liquidity/candle filters.

Research only. No API keys. No private data. No order execution.
"""

from __future__ import annotations

import run_binance_real_matrix as matrix
import run_binance_tagged_universe_matrix as tagged


def mtf_cfg(name: str, **overrides: object) -> dict:
    item = tagged.cfg(
        name,
        require_rolling_top=False,
        require_universe_gate=False,
        min_confidence=45.0,
        quality_take_threshold=68.0,
        quality_watch_threshold=55.0,
        structure_take_threshold=66.0,
        structure_watch_threshold=55.0,
        blocked_setup_types=("breakout", "range_rotation"),
        blocked_volatility_regimes=("high",),
        blocked_trend_contexts=tagged.BAD_TREND_CONTEXTS,
        blocked_liquidity_states=matrix.BAD_LIQUIDITY_STATES,
        blocked_candle_types=matrix.BAD_CANDLE_TYPES,
        min_volume_ratio=0.70,
    )
    item.update(overrides)
    return item


MTF_FAST_CONFIGS = [
    mtf_cfg(
        "TAGGED_MTF_NO_DIRECTION_BLOCK_V1",
    ),
    mtf_cfg(
        "TAGGED_MTF_NO_DIRECTION_NO_IGNITION_V1",
        blocked_setup_types=("breakout", "range_rotation", "ignition"),
    ),
    mtf_cfg(
        "TAGGED_MTF_ENTRY_CONFIRM_V1",
        min_confidence=48.0,
        quality_take_threshold=70.0,
        quality_watch_threshold=56.0,
        structure_take_threshold=68.0,
        structure_watch_threshold=56.0,
        blocked_setup_types=("breakout", "range_rotation", "ignition"),
    ),
]


def main() -> int:
    matrix.MATRIX_CONFIGS = MTF_FAST_CONFIGS
    print("Tagged MTF fast matrix mode")
    print("Universe/tags: unchanged")
    print("Context: 1D/4H market context")
    print("Entry timeframe: caller interval, expected 15m")
    print("Direction context: not blocked by up/down in MTF mode")
    print("Configs: " + ", ".join(str(item["name"]) for item in MTF_FAST_CONFIGS))
    return matrix.main()


if __name__ == "__main__":
    raise SystemExit(main())
