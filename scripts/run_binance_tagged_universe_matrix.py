#!/usr/bin/env python3
"""Run matrix for tagged-universe research.

This mode keeps old fixed-core configs as control rows, but adds explicit
"same logic without allowed_symbols" configs. These configs answer the real
question: if we keep the successful strategy logic and only expand the tagged
universe, which symbols does the strategy select?

Research only. No API keys. No private account data. No order execution.
"""

from __future__ import annotations

import run_binance_real_matrix as matrix


def cfg(name: str, **overrides: object) -> dict:
    item = matrix.base_cfg(name, **overrides)
    return item


def tagged_configs() -> list[dict]:
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


def main() -> int:
    original = list(matrix.MATRIX_CONFIGS)
    existing_names = {str(item.get("name", "")) for item in original}
    additions = [item for item in tagged_configs() if str(item.get("name", "")) not in existing_names]
    matrix.MATRIX_CONFIGS = additions + original
    print("Tagged universe matrix mode")
    print("Old fixed-core configs: kept as control")
    print("Tagged no-allowlist configs: added")
    print("Added configs: " + ", ".join(str(item["name"]) for item in additions))
    return matrix.main()


if __name__ == "__main__":
    raise SystemExit(main())
