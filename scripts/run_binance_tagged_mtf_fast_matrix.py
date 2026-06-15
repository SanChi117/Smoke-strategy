#!/usr/bin/env python3
"""Fast tagged MTF matrix.

Full tagged universe. Runtime-safe candidate set.
Research only: no API keys, no private data, no order execution.
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


MTF_V1_CONFIGS = [
    mtf_cfg("TAGGED_MTF_NO_DIRECTION_BLOCK_V1"),
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


MTF_V2_CONFIGS = [
    mtf_cfg(
        "TAGGED_MTF_V2_NO_WATCH_IMPULSE",
        blocked_setup_types=("breakout", "range_rotation", "watch_impulse"),
    ),
    mtf_cfg(
        "TAGGED_MTF_V2_NO_LIQ_RECLAIM",
        blocked_setup_types=("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim"),
    ),
    mtf_cfg(
        "TAGGED_MTF_V2_PULLBACK_IGNITION_ONLY",
        allowed_setup_types=("pullback", "ignition"),
        blocked_setup_types=("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim"),
        min_confidence=45.0,
    ),
    mtf_cfg(
        "TAGGED_MTF_V2_SHORT_CONTEXT_PULLBACK_IGNITION",
        allowed_setup_types=("pullback", "ignition"),
        allowed_direction_contexts=("down",),
        blocked_setup_types=("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim"),
        min_confidence=43.0,
        quality_take_threshold=66.0,
        quality_watch_threshold=54.0,
        structure_take_threshold=64.0,
        structure_watch_threshold=54.0,
    ),
    mtf_cfg(
        "TAGGED_MTF_V2_SHORT_CONTEXT_PULLBACK_ONLY",
        allowed_setup_types=("pullback",),
        allowed_direction_contexts=("down",),
        blocked_setup_types=("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim", "ignition"),
        min_confidence=42.0,
        quality_take_threshold=65.0,
        quality_watch_threshold=53.0,
        structure_take_threshold=63.0,
        structure_watch_threshold=53.0,
    ),
]


MTF_FAST_CONFIGS = MTF_V2_CONFIGS + MTF_V1_CONFIGS


def main() -> int:
    matrix.MATRIX_CONFIGS = MTF_FAST_CONFIGS
    print("Tagged MTF fast matrix mode")
    print("Universe/tags: unchanged")
    print("Context: 1D/4H market context")
    print("Entry timeframe: caller interval, expected 15m")
    print("V2 focus: no watch_impulse, test no liquidity_reclaim, pullback/ignition, short 4H/down bias")
    print("Configs: " + ", ".join(str(item["name"]) for item in MTF_FAST_CONFIGS))
    return matrix.main()


if __name__ == "__main__":
    raise SystemExit(main())
