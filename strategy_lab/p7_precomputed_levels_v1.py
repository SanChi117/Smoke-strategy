#!/usr/bin/env python3
"""Partition and merge exact causal P7 liquidity-level precomputation.

This module changes only execution topology. It evaluates the same frozen level
constructors over the same locked dataset, but divides chronological period,
session and range timestamps into contiguous parts. Merge restores the exact
source ordering used by ``_precompute_levels`` before applying the same global
level de-duplication. Recognition semantics, thresholds, folds, period,
fingerprinting and no-outcome scope are unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
from pathlib import Path
from typing import Any, Sequence

import strategy_lab.p7_full_recognition_runner_v1 as runner


def _slice(values: Sequence[Any], part_index: int, part_count: int) -> Sequence[Any]:
    if part_count < 1 or not 0 <= part_index < part_count:
        raise ValueError("invalid part index/count")
    base, remainder = divmod(len(values), part_count)
    start = part_index * base + min(part_index, remainder)
    size = base + (1 if part_index < remainder else 0)
    return values[start : start + size]


def _manifest_sha(root: Path) -> str:
    return hashlib.sha256(
        (root / "p7_full_recognition_data_manifest_v1.json").read_bytes()
    ).hexdigest()


def precompute_part(
    symbol: str,
    part_index: int,
    part_count: int,
    output: Path,
    root: Path = runner.DATA_ROOT,
) -> None:
    symbol = symbol.upper()
    manifest, candles_by_symbol = runner.load_locked_dataset(root)
    if symbol not in candles_by_symbol:
        raise ValueError(f"unexpected symbol: {symbol}")

    engine = runner.MtfDealingRangeEngine(candles_by_symbol[symbol])
    boundaries = [bar.close_time for bar in engine.bars["15m"] if bar.symbol == symbol]
    if not boundaries:
        raise ValueError(f"no 15m boundaries: {symbol}")
    end = boundaries[-1]
    config = runner.ContextLiquidityConfig()

    daily_times = [
        bar.close_time
        for bar in engine.bars["1d"]
        if bar.symbol == symbol and bar.close_time <= end
    ]
    session_marks = {
        (spec.end_minute_utc // 60, spec.end_minute_utc % 60)
        for spec in config.session_specs
    }
    session_times = [
        timestamp
        for timestamp in boundaries
        if (timestamp.hour, timestamp.minute) in session_marks
    ]
    range_times = [
        bar.close_time
        for bar in engine.bars["4h"]
        if bar.symbol == symbol and bar.close_time <= end
    ]

    print(json.dumps({
        "event": "p7_symbol_level_part_started",
        "symbol": symbol,
        "part_index": part_index,
        "part_count": part_count,
        "daily_total": len(daily_times),
        "session_total": len(session_times),
        "range_total": len(range_times),
    }, sort_keys=True), flush=True)

    pivot_equal = []
    if part_index == 0:
        pivot_equal.extend(runner._pivot_liquidity_levels(engine, symbol, end, config))
        pivot_equal.extend(runner._equal_liquidity_levels(engine, symbol, end, config))

    period_levels = []
    for timestamp in _slice(daily_times, part_index, part_count):
        period_levels.extend(runner._period_liquidity_levels(engine, symbol, timestamp))

    session_levels = []
    for timestamp in _slice(session_times, part_index, part_count):
        session_levels.extend(runner._session_liquidity_levels(engine, symbol, timestamp, config))

    range_levels = []
    for timestamp in _slice(range_times, part_index, part_count):
        range_levels.extend(
            runner._range_liquidity_levels(
                runner._context_view(engine, symbol, timestamp, config).states
            )
        )

    payload = {
        "recognition_id": runner.RECOGNITION_ID,
        "symbol": symbol,
        "data_manifest_sha256": _manifest_sha(root),
        "source": manifest["source"],
        "interval": manifest["interval"],
        "boundary_count": len(boundaries),
        "part_index": part_index,
        "part_count": part_count,
        "pivot_equal": tuple(pivot_equal),
        "period": tuple(period_levels),
        "session": tuple(session_levels),
        "range": tuple(range_levels),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)

    print(json.dumps({
        "event": "p7_symbol_level_part_completed",
        "symbol": symbol,
        "part_index": part_index,
        "part_count": part_count,
        "pivot_equal_levels": len(pivot_equal),
        "period_levels": len(period_levels),
        "session_levels": len(session_levels),
        "range_levels": len(range_levels),
        "output": str(output),
    }, sort_keys=True), flush=True)


def merge_parts(symbol: str, input_dir: Path, output: Path) -> None:
    symbol = symbol.upper()
    paths = sorted(input_dir.rglob(f"p7_levels_{symbol}_part_*.pkl"))
    if not paths:
        raise FileNotFoundError(f"no level parts for {symbol} in {input_dir}")

    parts: dict[int, dict[str, Any]] = {}
    for path in paths:
        with path.open("rb") as handle:
            payload = pickle.load(handle)
        if payload["recognition_id"] != runner.RECOGNITION_ID:
            raise ValueError("recognition id mismatch")
        if payload["symbol"] != symbol:
            raise ValueError("symbol mismatch")
        index = int(payload["part_index"])
        if index in parts:
            raise ValueError(f"duplicate part: {index}")
        parts[index] = payload

    first = parts[min(parts)]
    part_count = int(first["part_count"])
    if set(parts) != set(range(part_count)):
        raise ValueError(f"incomplete parts: {sorted(parts)} expected {part_count}")
    invariant_keys = (
        "recognition_id", "symbol", "data_manifest_sha256", "source",
        "interval", "boundary_count", "part_count",
    )
    for payload in parts.values():
        for key in invariant_keys:
            if payload[key] != first[key]:
                raise ValueError(f"part invariant mismatch: {key}")

    ordered = [parts[index] for index in range(part_count)]
    raw_levels = []
    raw_levels.extend(ordered[0]["pivot_equal"])
    for source in ("period", "session", "range"):
        for payload in ordered:
            raw_levels.extend(payload[source])
    levels = runner._deduplicate_levels(raw_levels)

    merged = {
        "recognition_id": runner.RECOGNITION_ID,
        "symbol": symbol,
        "data_manifest_sha256": first["data_manifest_sha256"],
        "source": first["source"],
        "interval": first["interval"],
        "boundary_count": first["boundary_count"],
        "part_count": part_count,
        "levels": levels,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as handle:
        pickle.dump(merged, handle, protocol=pickle.HIGHEST_PROTOCOL)
    print(json.dumps({
        "event": "p7_symbol_levels_merged",
        "symbol": symbol,
        "part_count": part_count,
        "levels": len(levels),
        "output": str(output),
    }, sort_keys=True), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    part = sub.add_parser("part")
    part.add_argument("--symbol", required=True)
    part.add_argument("--part-index", required=True, type=int)
    part.add_argument("--part-count", required=True, type=int)
    part.add_argument("--output", required=True, type=Path)

    merge = sub.add_parser("merge")
    merge.add_argument("--symbol", required=True)
    merge.add_argument("--input-dir", required=True, type=Path)
    merge.add_argument("--output", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "part":
        precompute_part(args.symbol, args.part_index, args.part_count, args.output)
    else:
        merge_parts(args.symbol, args.input_dir, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
