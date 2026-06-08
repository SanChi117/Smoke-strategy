#!/usr/bin/env python3
"""Run matrix for tagged-universe research.

This mode keeps old fixed-core configs as control rows, but adds explicit
"same logic without allowed_symbols" configs. These configs answer the real
question: if we keep the successful strategy logic and only expand the tagged
universe, which symbols does the strategy select?

Correction packs are intentionally conservative:
- no universe reduction;
- no sector-as-rule logic;
- no deletion of old configs;
- no live/paper promotion;
- only extra strategy-filter variants are added for comparison.

Research only. No API keys. No private account data. No order execution.
"""

from __future__ import annotations

import run_binance_real_matrix as matrix


GOOD_TREND_CONTEXTS = ("up", "sideways")
BAD_TREND_CONTEXTS = ("down",)
BAD_DIRECTION_CONTEXTS_EXTENDED = ("up", "hard_up")


def cfg(name: str, **overrides: object) -> dict:
    item = matrix.base_cfg(name, **overrides)
    return item


def tagged_baseline_configs() -> list[dict]:
    """Current tagged-universe configs, kept unchanged for comparison."""
    return [
        cfg(
            "TAGGED_CORE_LOGIC_DIRECT",
            require_rolling_top=False,
            require_universe_gate=False,
            blocked_setup_types=("breakout",),
            blocked_volatility_regimes=("high",),
        ),
        cfg(
            "TAGGED_CORE_LOGIC_DIRECT_MIN_VR_084",
            require_rolling_top=False,
            require_universe_gate=False,
            blocked_setup_types=("breakout",),
            blocked_volatility_regimes=("high",),
            min_volume_ratio=0.84,
        ),
        cfg(
            "TAGGED_CORE_LOGIC_DIRECT_STRICTER",
            require_rolling_top=False,
            require_universe_gate=False,
            min_confidence=45.0,
            quality_take_threshold=68.0,
            quality_watch_threshold=55.0,
            structure_take_threshold=66.0,
            structure_watch_threshold=55.0,
            blocked_setup_types=("breakout",),
            blocked_volatility_regimes=("high",),
        ),
        cfg(
            "TAGGED_CORE_LOGIC_NO_BAD_LIQ",
            require_rolling_top=False,
            require_universe_gate=False,
            blocked_setup_types=("breakout",),
            blocked_volatility_regimes=("high",),
            blocked_liquidity_states=matrix.BAD_LIQUIDITY_STATES,
        ),
        cfg(
            "TAGGED_CORE_LOGIC_NO_BEAR_REJECT",
            require_rolling_top=False,
            require_universe_gate=False,
            blocked_setup_types=("breakout",),
            blocked_volatility_regimes=("high",),
            blocked_candle_types=matrix.BAD_CANDLE_TYPES,
        ),
        matrix.micro_strict_cfg(
            "TAGGED_MICRO_STRICT_DIRECT",
            require_rolling_top=False,
            require_universe_gate=False,
        ),
    ]


def correction_pack_v1_configs() -> list[dict]:
    """Strategy-logic correction pack for the tagged universe.

    These variants keep the full tagged pool intact and only test safer entry
    filters. The current best tagged baseline remains available as control.
    """
    return [
        cfg(
            "TAGGED_LOGIC_QUALITY_STRICT_V1",
            require_rolling_top=False,
            require_universe_gate=False,
            min_confidence=50.0,
            quality_take_threshold=72.0,
            quality_watch_threshold=58.0,
            structure_take_threshold=70.0,
            structure_watch_threshold=58.0,
            blocked_setup_types=("breakout",),
            blocked_volatility_regimes=("high",),
            blocked_candle_types=matrix.BAD_CANDLE_TYPES,
            min_volume_ratio=0.84,
        ),
        cfg(
            "TAGGED_LOGIC_TREND_PROTECTED_V1",
            require_rolling_top=False,
            require_universe_gate=False,
            min_confidence=45.0,
            quality_take_threshold=68.0,
            quality_watch_threshold=55.0,
            structure_take_threshold=66.0,
            structure_watch_threshold=55.0,
            blocked_setup_types=("breakout",),
            blocked_volatility_regimes=("high",),
            blocked_trend_contexts=BAD_TREND_CONTEXTS,
            blocked_direction_contexts=matrix.BAD_DIRECTION_CONTEXTS,
            blocked_candle_types=matrix.BAD_CANDLE_TYPES,
            min_volume_ratio=0.84,
        ),
        cfg(
            "TAGGED_LOGIC_LIQUIDITY_PROTECTED_V1",
            require_rolling_top=False,
            require_universe_gate=False,
            min_confidence=45.0,
            quality_take_threshold=68.0,
            quality_watch_threshold=55.0,
            structure_take_threshold=66.0,
            structure_watch_threshold=55.0,
            blocked_setup_types=("breakout",),
            blocked_volatility_regimes=("high",),
            blocked_liquidity_states=matrix.BAD_LIQUIDITY_STATES,
            blocked_candle_types=matrix.BAD_CANDLE_TYPES,
            min_volume_ratio=0.84,
        ),
        cfg(
            "TAGGED_LOGIC_GOOD_SETUPS_ONLY_V1",
            require_rolling_top=False,
            require_universe_gate=False,
            min_confidence=40.0,
            quality_take_threshold=64.0,
            quality_watch_threshold=52.0,
            structure_take_threshold=62.0,
            structure_watch_threshold=52.0,
            allowed_setup_types=matrix.BEST_RESEARCH_SETUPS,
            blocked_volatility_regimes=("high",),
            blocked_liquidity_states=matrix.BAD_LIQUIDITY_STATES,
            blocked_candle_types=matrix.BAD_CANDLE_TYPES,
            min_volume_ratio=0.70,
        ),
        cfg(
            "TAGGED_LOGIC_OVEREXTENSION_FILTER_V1",
            require_rolling_top=False,
            require_universe_gate=False,
            min_confidence=45.0,
            quality_take_threshold=68.0,
            quality_watch_threshold=55.0,
            structure_take_threshold=66.0,
            structure_watch_threshold=55.0,
            blocked_setup_types=("breakout",),
            blocked_volatility_regimes=("high",),
            blocked_direction_contexts=BAD_DIRECTION_CONTEXTS_EXTENDED,
            blocked_candle_types=matrix.BAD_CANDLE_TYPES,
            min_volume_ratio=0.84,
        ),
        cfg(
            "TAGGED_LOGIC_COMBINED_V2",
            require_rolling_top=False,
            require_universe_gate=False,
            min_confidence=50.0,
            quality_take_threshold=72.0,
            quality_watch_threshold=58.0,
            structure_take_threshold=70.0,
            structure_watch_threshold=58.0,
            allowed_setup_types=matrix.BEST_RESEARCH_SETUPS,
            blocked_volatility_regimes=("high",),
            blocked_liquidity_states=matrix.BAD_LIQUIDITY_STATES,
            blocked_candle_types=matrix.BAD_CANDLE_TYPES,
            blocked_direction_contexts=matrix.BAD_DIRECTION_CONTEXTS,
            min_volume_ratio=0.84,
        ),
    ]


def correction_pack_v3_configs() -> list[dict]:
    """Balanced v3 pack focused on WFO robustness, not prettier matrix.

    The pack keeps the 103-symbol tagged universe untouched and tests two
    directions:
    - DIRECT_STRICTER variants with volume confirmation changes;
    - TREND_PROTECTED variants with liquidity/quality balance.
    """
    return [
        cfg(
            "TAGGED_LOGIC_DIRECT_STRICTER_VR070_V2",
            require_rolling_top=False,
            require_universe_gate=False,
            min_confidence=45.0,
            quality_take_threshold=68.0,
            quality_watch_threshold=55.0,
            structure_take_threshold=66.0,
            structure_watch_threshold=55.0,
            blocked_setup_types=("breakout",),
            blocked_volatility_regimes=("high",),
            min_volume_ratio=0.70,
        ),
        cfg(
            "TAGGED_LOGIC_DIRECT_STRICTER_VR084_V2",
            require_rolling_top=False,
            require_universe_gate=False,
            min_confidence=45.0,
            quality_take_threshold=68.0,
            quality_watch_threshold=55.0,
            structure_take_threshold=66.0,
            structure_watch_threshold=55.0,
            blocked_setup_types=("breakout",),
            blocked_volatility_regimes=("high",),
            min_volume_ratio=0.84,
        ),
        cfg(
            "TAGGED_LOGIC_TREND_LIQUIDITY_BALANCED_V2",
            require_rolling_top=False,
            require_universe_gate=False,
            min_confidence=45.0,
            quality_take_threshold=68.0,
            quality_watch_threshold=55.0,
            structure_take_threshold=66.0,
            structure_watch_threshold=55.0,
            blocked_setup_types=("breakout",),
            blocked_volatility_regimes=("high",),
            blocked_trend_contexts=BAD_TREND_CONTEXTS,
            blocked_direction_contexts=matrix.BAD_DIRECTION_CONTEXTS,
            blocked_liquidity_states=matrix.BAD_LIQUIDITY_STATES,
            blocked_candle_types=matrix.BAD_CANDLE_TYPES,
            min_volume_ratio=0.70,
        ),
        cfg(
            "TAGGED_LOGIC_TREND_QUALITY_BALANCED_V2",
            require_rolling_top=False,
            require_universe_gate=False,
            min_confidence=48.0,
            quality_take_threshold=70.0,
            quality_watch_threshold=56.0,
            structure_take_threshold=68.0,
            structure_watch_threshold=56.0,
            blocked_setup_types=("breakout",),
            blocked_volatility_regimes=("high",),
            blocked_trend_contexts=BAD_TREND_CONTEXTS,
            blocked_direction_contexts=matrix.BAD_DIRECTION_CONTEXTS,
            blocked_candle_types=matrix.BAD_CANDLE_TYPES,
            min_volume_ratio=0.70,
        ),
    ]


def tagged_configs() -> list[dict]:
    return correction_pack_v3_configs() + correction_pack_v1_configs() + tagged_baseline_configs()


def main() -> int:
    original = list(matrix.MATRIX_CONFIGS)
    existing_names = {str(item.get("name", "")) for item in original}
    additions = [item for item in tagged_configs() if str(item.get("name", "")) not in existing_names]
    matrix.MATRIX_CONFIGS = additions + original
    print("Tagged universe matrix mode")
    print("Old fixed-core configs: kept as control")
    print("Tagged no-allowlist configs: added")
    print("Correction pack v1: added")
    print("Correction pack v3: added")
    print("Universe/tags: unchanged")
    print("Added configs: " + ", ".join(str(item["name"]) for item in additions))
    return matrix.main()


if __name__ == "__main__":
    raise SystemExit(main())
