#!/usr/bin/env python3
"""Fast tagged MTF matrix.

Full tagged universe. Runtime-safe candidate set.
Research only: no API keys, no private data, no order execution.
"""

from __future__ import annotations

import run_binance_real_matrix as matrix
import run_binance_tagged_universe_matrix as tagged


# The generic matrix predates completed 4H/1D alignment filters. Register them
# here so tagged matrix rows export the exact configuration later consumed by WFO.
for _filter_key in ("allowed_context_alignments", "blocked_context_alignments"):
    if _filter_key not in matrix.TACTICAL_FILTER_KEYS:
        matrix.TACTICAL_FILTER_KEYS.append(_filter_key)


PULLBACK_FAMILY = ("pullback", "pullback_resumption", "pullback_resumption_strict")
RESUMPTION_FAMILY = ("pullback_resumption", "pullback_resumption_strict")


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


def pullback_short_cfg(name: str, **overrides: object) -> dict:
    """Legacy pullback family control derived from prior fold diagnostics."""
    item = mtf_cfg(
        name,
        blocked_trend_contexts=(),
        allowed_setup_types=PULLBACK_FAMILY,
        allowed_direction_contexts=("down",),
        blocked_setup_types=("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim", "ignition"),
        min_confidence=43.0,
        quality_take_threshold=64.0,
        quality_watch_threshold=52.0,
        structure_take_threshold=63.0,
        structure_watch_threshold=52.0,
        min_volume_ratio=0.70,
    )
    item.update(overrides)
    return item


def resumption_short_cfg(name: str, **overrides: object) -> dict:
    """Two-bar causal resumption family; not a promoted baseline."""
    item = pullback_short_cfg(
        name,
        allowed_setup_types=RESUMPTION_FAMILY,
        min_confidence=45.0,
        quality_take_threshold=64.0,
        quality_watch_threshold=52.0,
        structure_take_threshold=63.0,
        structure_watch_threshold=52.0,
        min_volume_ratio=0.65,
    )
    item.update(overrides)
    return item


MTF_SELECTED_CONFIGS = [
    # Legacy controls retained for comparison. Resumption subtypes remain part of
    # the pullback family so the control does not silently lose valid pullbacks.
    mtf_cfg(
        "TAGGED_MTF_ENTRY_CONFIRM_V1",
        allowed_setup_types=(*PULLBACK_FAMILY, "ignition"),
        allowed_direction_contexts=("down",),
        blocked_setup_types=("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim"),
        min_confidence=43.0,
        quality_take_threshold=66.0,
        quality_watch_threshold=54.0,
        structure_take_threshold=64.0,
        structure_watch_threshold=54.0,
    ),
    mtf_cfg(
        "TAGGED_MTF_NO_DIRECTION_NO_IGNITION_V1",
        blocked_trend_contexts=(),
        blocked_setup_types=("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim", "ignition"),
    ),
    mtf_cfg(
        "TAGGED_MTF_NO_DIRECTION_BLOCK_V1",
        blocked_trend_contexts=(),
        allowed_setup_types=(*PULLBACK_FAMILY, "ignition"),
        allowed_direction_contexts=("down",),
        blocked_setup_types=("breakout", "range_rotation", "watch_impulse", "liquidity_reclaim"),
        min_confidence=43.0,
        quality_take_threshold=66.0,
        quality_watch_threshold=54.0,
        structure_take_threshold=64.0,
        structure_watch_threshold=54.0,
    ),

    # Iteration 1 controls: broad pullback short, including relabelled resumption bars.
    pullback_short_cfg("TAGGED_PULLBACK_SHORT_BALANCED_V1"),
    pullback_short_cfg(
        "TAGGED_PULLBACK_SHORT_NEUTRAL_INDECISION_V1",
        allowed_candle_types=("neutral", "indecision"),
    ),
    pullback_short_cfg(
        "TAGGED_PULLBACK_SHORT_INDECISION_V1",
        allowed_candle_types=("indecision",),
    ),
    pullback_short_cfg(
        "TAGGED_PULLBACK_SHORT_INDECISION_VR09_V1",
        allowed_candle_types=("indecision",),
        min_volume_ratio=0.90,
    ),
    pullback_short_cfg(
        "TAGGED_PULLBACK_SHORT_STRICT_V1",
        allowed_candle_types=("neutral", "indecision"),
        min_confidence=48.0,
        quality_take_threshold=68.0,
        quality_watch_threshold=56.0,
        structure_take_threshold=66.0,
        structure_watch_threshold=55.0,
        min_volume_ratio=0.84,
    ),

    # Iteration 2: the entry itself requires a completed retracement followed by a
    # completed candle resuming the downtrend.
    resumption_short_cfg("TAGGED_PULLBACK_RESUMPTION_BOTH_V1"),
    resumption_short_cfg(
        "TAGGED_PULLBACK_RESUMPTION_BALANCED_V1",
        allowed_setup_types=("pullback_resumption",),
    ),
    resumption_short_cfg(
        "TAGGED_PULLBACK_RESUMPTION_STRICT_V1",
        allowed_setup_types=("pullback_resumption_strict",),
        min_volume_ratio=0.80,
    ),
    resumption_short_cfg(
        "TAGGED_PULLBACK_RESUMPTION_BOTH_VR09_V1",
        min_volume_ratio=0.90,
    ),
]


MTF_FAST_CONFIGS = MTF_SELECTED_CONFIGS


def main() -> int:
    matrix.MATRIX_CONFIGS = MTF_FAST_CONFIGS
    print("Tagged MTF fast matrix mode")
    print("Universe/tags: unchanged")
    print("Context: completed 1D/4H market context")
    print("Entry timeframe: caller interval, expected 15m")
    print("Iteration: legacy controls + causal two-bar pullback resumption")
    print("Configs: " + ", ".join(str(item["name"]) for item in MTF_FAST_CONFIGS))
    return matrix.main()


if __name__ == "__main__":
    raise SystemExit(main())
