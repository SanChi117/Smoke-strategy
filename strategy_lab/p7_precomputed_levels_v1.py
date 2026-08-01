#!/usr/bin/env python3
"""Precompute exact causal P7 liquidity levels once per symbol.

This module changes only CI execution topology. It calls the frozen P7 level
precomputation over the same locked dataset and serializes the resulting Python
objects for reuse by the ten fold jobs of that symbol. Recognition semantics,
thresholds, folds, period, fingerprinting and no-outcome scope are unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
from pathlib import Path

import strategy_lab.p7_full_recognition_runner_v1 as runner


def precompute(symbol: str, output: Path, root: Path = runner.DATA_ROOT) -> None:
    symbol = symbol.upper()
    manifest, candles_by_symbol = runner.load_locked_dataset(root)
    if symbol not in candles_by_symbol:
        raise ValueError(f"unexpected symbol: {symbol}")

    engine = runner.MtfDealingRangeEngine(candles_by_symbol[symbol])
    boundaries = [
        bar.close_time
        for bar in engine.bars["15m"]
        if bar.symbol == symbol
    ]
    config = runner.ContextLiquidityConfig()
    print(json.dumps({
        "event": "p7_symbol_levels_started",
        "symbol": symbol,
        "boundaries": len(boundaries),
    }, sort_keys=True), flush=True)
    levels = runner._precompute_levels(engine, symbol, boundaries, config)

    payload = {
        "recognition_id": runner.RECOGNITION_ID,
        "symbol": symbol,
        "data_manifest_sha256": hashlib.sha256(
            (root / "p7_full_recognition_data_manifest_v1.json").read_bytes()
        ).hexdigest(),
        "source": manifest["source"],
        "interval": manifest["interval"],
        "boundary_count": len(boundaries),
        "levels": levels,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    print(json.dumps({
        "event": "p7_symbol_levels_completed",
        "symbol": symbol,
        "boundaries": len(boundaries),
        "levels": len(levels),
        "output": str(output),
    }, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    precompute(args.symbol, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
