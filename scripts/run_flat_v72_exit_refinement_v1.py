#!/usr/bin/env python3
"""Predeclared exit-policy refinement for the recovered Flat v7.2 entries.

This cycle changes exits and holding time only. Entry logic, universe, fees,
portfolio profile, chronological folds, and causal execution remain frozen.
Development only; external holdout is not touched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import run_flat_v72_causal_screening_v1 as base
from strategy_lab.flat_v72 import FlatV72Config


base.VARIANTS = [
    {
        "name": "FLAT72_EXIT_SOFT_STRUCT_24H_CONTROL",
        "learning": "soft",
        "config": FlatV72Config(
            name="FLAT72_EXIT_SOFT_STRUCT_24H_CONTROL",
            max_holding_bars=96,
        ),
    },
    {
        "name": "FLAT72_EXIT_SOFT_STRUCT_8H",
        "learning": "soft",
        "config": FlatV72Config(
            name="FLAT72_EXIT_SOFT_STRUCT_8H",
            max_holding_bars=32,
        ),
    },
    {
        "name": "FLAT72_EXIT_SOFT_STRUCT_12H",
        "learning": "soft",
        "config": FlatV72Config(
            name="FLAT72_EXIT_SOFT_STRUCT_12H",
            max_holding_bars=48,
        ),
    },
    {
        "name": "FLAT72_EXIT_SOFT_STRUCT_16H",
        "learning": "soft",
        "config": FlatV72Config(
            name="FLAT72_EXIT_SOFT_STRUCT_16H",
            max_holding_bars=64,
        ),
    },
    {
        "name": "FLAT72_EXIT_SOFT_FIXED_RR10_8H",
        "learning": "soft",
        "config": FlatV72Config(
            name="FLAT72_EXIT_SOFT_FIXED_RR10_8H",
            use_structural_target=False,
            minimum_rr=0.80,
            fixed_target_rr=1.00,
            max_holding_bars=32,
        ),
    },
    {
        "name": "FLAT72_EXIT_SOFT_FIXED_RR12_12H",
        "learning": "soft",
        "config": FlatV72Config(
            name="FLAT72_EXIT_SOFT_FIXED_RR12_12H",
            use_structural_target=False,
            minimum_rr=0.80,
            fixed_target_rr=1.20,
            max_holding_bars=48,
        ),
    },
    {
        "name": "FLAT72_EXIT_SOFT_COMPRESSED_STRUCT_12H",
        "learning": "soft",
        "config": FlatV72Config(
            name="FLAT72_EXIT_SOFT_COMPRESSED_STRUCT_12H",
            minimum_rr=1.10,
            weak_rr_cap=1.60,
            strong_rr_cap=2.00,
            max_holding_bars=48,
        ),
    },
    {
        "name": "FLAT72_EXIT_SOFT_COMPRESSED_STRUCT_16H",
        "learning": "soft",
        "config": FlatV72Config(
            name="FLAT72_EXIT_SOFT_COMPRESSED_STRUCT_16H",
            minimum_rr=1.30,
            weak_rr_cap=1.80,
            strong_rr_cap=2.20,
            max_holding_bars=64,
        ),
    },
]


def main() -> int:
    code = base.main()
    args = sys.argv[1:]
    out_dir = None
    for index, value in enumerate(args):
        if value == "--out-dir" and index + 1 < len(args):
            out_dir = Path(args[index + 1])
            break
    if out_dir:
        result_path = out_dir / "result.json"
        if result_path.exists():
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            payload["mode"] = "FLAT_V72_EXIT_REFINEMENT_V1"
            payload["promotion_allowed"] = False
            payload["frozen_dimensions"] = [
                "entry logic",
                "universe",
                "development period",
                "fees and slippage",
                "portfolio profile",
                "next-bar-open execution",
                "closed-candle rules",
            ]
            payload["changed_dimensions"] = [
                "target policy",
                "minimum RR",
                "RR cap",
                "maximum holding bars",
            ]
            payload["next_required_step"] = (
                "If one candidate passes development, freeze exactly one candidate for a new untouched holdout. "
                "If all candidates block, do not tune these exits again on the same period; proceed to 5m soft timing and ranking."
            )
            result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
