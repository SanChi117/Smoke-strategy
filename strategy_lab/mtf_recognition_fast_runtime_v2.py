#!/usr/bin/env python3
"""Execution-only caches for SMOKE MTF V2 recognition exports.

The runtime preserves all causal formulas. It only memoizes deterministic
closed-candle computations that were previously repeated for LONG and SHORT.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Sequence

import strategy_lab.mtf_dealing_range_v2 as dealing
import strategy_lab.mtf_entry_model_v2 as entry
import strategy_lab.mtf_liquidity_map_v2 as liquidity
import strategy_lab.mtf_raid_signal_v2 as raid
import strategy_lab.mtf_target_selection_v2 as target
import strategy_lab.mtf_volume_confirmation_v2 as volume


class FastRecognitionRuntime:
    """Memoize deterministic as-of computations for one immutable engine."""

    def __init__(self, engine: dealing.MtfDealingRangeEngine):
        self.engine = engine
        self._original_snapshot = engine.snapshot
        self._original_confirmed_pivots = dealing.confirmed_pivots
        self._original_imbalance_levels = dealing.imbalance_levels
        self._original_liquidity_map = liquidity.build_liquidity_map
        self._original_entry_bars_asof = entry._bars_asof

        self._snapshot_cache: dict[tuple[str, datetime], Any] = {}
        self._pivot_cache: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        self._imbalance_cache: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        self._liquidity_cache: dict[tuple[str, datetime, tuple[str, ...]], Any] = {}
        self._prefix_cache: dict[tuple[int, str, datetime], tuple[Any, ...]] = {}
        self._series_by_container: dict[int, dict[str, tuple[Any, ...]]] = {}
        self._times_by_container: dict[int, dict[str, tuple[datetime, ...]]] = {}
        self.hits: defaultdict[str, int] = defaultdict(int)
        self.misses: defaultdict[str, int] = defaultdict(int)

        for rows in engine.bars.values():
            grouped: defaultdict[str, list[Any]] = defaultdict(list)
            for bar in rows:
                grouped[bar.symbol.upper()].append(bar)
            series = {
                symbol: tuple(sorted(values, key=lambda row: row.close_time))
                for symbol, values in grouped.items()
            }
            self._series_by_container[id(rows)] = series
            self._times_by_container[id(rows)] = {
                symbol: tuple(row.close_time for row in values)
                for symbol, values in series.items()
            }

    @staticmethod
    def _bars_key(bars: Sequence[Any], left_bars: int | None = None, right_bars: int | None = None) -> tuple[Any, ...]:
        if not bars:
            return ("EMPTY", left_bars, right_bars)
        first = bars[0]
        last = bars[-1]
        return (
            getattr(first, "symbol", ""),
            getattr(first, "timeframe", ""),
            len(bars),
            getattr(first, "close_time", None),
            getattr(last, "close_time", None),
            left_bars,
            right_bars,
        )

    def bars_asof(self, bars: Sequence[Any], symbol: str, timestamp: datetime) -> list[Any]:
        normalized = symbol.upper()
        cache_key = (id(bars), normalized, timestamp)
        cached = self._prefix_cache.get(cache_key)
        if cached is not None:
            self.hits["bars_asof"] += 1
            return list(cached)
        series_map = self._series_by_container.get(id(bars))
        times_map = self._times_by_container.get(id(bars))
        if series_map is None or times_map is None:
            self.misses["bars_asof_fallback"] += 1
            return self._original_entry_bars_asof(bars, normalized, timestamp)
        series = series_map.get(normalized, ())
        times = times_map.get(normalized, ())
        end = bisect_right(times, timestamp)
        prefix = series[:end]
        self._prefix_cache[cache_key] = prefix
        self.misses["bars_asof"] += 1
        return list(prefix)

    def confirmed_pivots(self, bars: Sequence[Any], left_bars: int = 2, right_bars: int = 2) -> list[Any]:
        key = self._bars_key(bars, left_bars, right_bars)
        cached = self._pivot_cache.get(key)
        if cached is not None:
            self.hits["pivots"] += 1
            return list(cached)
        value = tuple(self._original_confirmed_pivots(bars, left_bars, right_bars))
        self._pivot_cache[key] = value
        self.misses["pivots"] += 1
        return list(value)

    def imbalance_levels(self, bars: Sequence[Any], asof: datetime | None = None) -> list[Any]:
        key = self._bars_key(bars) + (asof,)
        cached = self._imbalance_cache.get(key)
        if cached is not None:
            self.hits["imbalances"] += 1
            return list(cached)
        value = tuple(self._original_imbalance_levels(bars, asof))
        self._imbalance_cache[key] = value
        self.misses["imbalances"] += 1
        return list(value)

    def snapshot(self, symbol: str, timestamp: datetime) -> Any:
        key = (symbol.upper(), timestamp)
        cached = self._snapshot_cache.get(key)
        if cached is not None:
            self.hits["snapshot"] += 1
            return cached
        value = self._original_snapshot(symbol, timestamp)
        self._snapshot_cache[key] = value
        self.misses["snapshot"] += 1
        return value

    def build_liquidity_map(
        self,
        engine: dealing.MtfDealingRangeEngine,
        symbol: str,
        timestamp: datetime,
        structural_timeframes: tuple[str, ...] = ("1h", "4h", "1d", "1w", "1M"),
    ) -> Any:
        if engine is not self.engine:
            return self._original_liquidity_map(engine, symbol, timestamp, structural_timeframes)
        key = (symbol.upper(), timestamp, tuple(structural_timeframes))
        cached = self._liquidity_cache.get(key)
        if cached is not None:
            self.hits["liquidity_map"] += 1
            return cached
        value = self._original_liquidity_map(engine, symbol, timestamp, structural_timeframes)
        self._liquidity_cache[key] = value
        self.misses["liquidity_map"] += 1
        return value

    def install(self) -> "FastRecognitionRuntime":
        self.engine.snapshot = self.snapshot  # type: ignore[method-assign]
        dealing.confirmed_pivots = self.confirmed_pivots
        dealing.imbalance_levels = self.imbalance_levels
        entry.confirmed_pivots = self.confirmed_pivots
        entry._bars_asof = self.bars_asof
        entry.build_liquidity_map = self.build_liquidity_map
        raid.confirmed_pivots = self.confirmed_pivots
        volume.confirmed_pivots = self.confirmed_pivots
        liquidity.confirmed_pivots = self.confirmed_pivots
        liquidity.imbalance_levels = self.imbalance_levels
        liquidity.build_liquidity_map = self.build_liquidity_map
        target.build_liquidity_map = self.build_liquidity_map
        return self

    def stats(self) -> dict[str, dict[str, int]]:
        return {
            "hits": dict(sorted(self.hits.items())),
            "misses": dict(sorted(self.misses.items())),
            "sizes": {
                "snapshots": len(self._snapshot_cache),
                "pivots": len(self._pivot_cache),
                "imbalances": len(self._imbalance_cache),
                "liquidity_maps": len(self._liquidity_cache),
                "bar_prefixes": len(self._prefix_cache),
            },
        }


def install_fast_runtime(engine: dealing.MtfDealingRangeEngine) -> FastRecognitionRuntime:
    return FastRecognitionRuntime(engine).install()
