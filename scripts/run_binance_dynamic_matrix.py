#!/usr/bin/env python3
"""Run Binance matrix in dynamic-universe mode.

This wrapper reuses run_binance_real_matrix but excludes any config with a fixed
allowed_symbols allowlist. It is intended for symbol-universe research where
sectors are metadata/context, not trading boundaries, and old fixed-core configs
must not win the baseline selection.

Research only. No API keys. No private account data. No order execution.
"""

from __future__ import annotations

import sys

import run_binance_real_matrix as matrix


def is_dynamic_config(cfg: dict) -> bool:
    return not tuple(cfg.get("allowed_symbols", ()) or ())


def main() -> int:
    original = list(matrix.MATRIX_CONFIGS)
    matrix.MATRIX_CONFIGS = [cfg for cfg in original if is_dynamic_config(cfg)]
    print("Dynamic matrix mode")
    print(f"Configs included: {len(matrix.MATRIX_CONFIGS)} / {len(original)}")
    print("Fixed allowed_symbols configs: excluded")
    return matrix.main()


if __name__ == "__main__":
    raise SystemExit(main())
