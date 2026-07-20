#!/usr/bin/env python3
"""Execution-only caches for SMOKE MTF V2 recognition exports.

The runtime preserves all causal formulas. It reuses deterministic results from
closed candles and filters precomputed structures by their original
confirmation timestamps. No future candle is exposed to an earlier snapshot.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import datetime
from typing import Any, Sequence

import strategy_lab.mtf_dealing_range_v2 as dealing
import strategy_lab.mtf_entry_model_v2 as entry
import strategy_lab.mtf_liquidity_map_v2 as liquidity
import strategy_lab.mtf_raid_signal_v2 as raid
import strategy_lab.mtf_target_selection_v2 as target
import strategy_lab.mtf_volume_confirmation_v2 as volume

_ORIGINAL_CONFIRMED_PIVOTS = dealing.confirmed_pivots
_ORIGINAL_IMBALANCE_LEVELS = dealing.imbalance_levels
_ORIGINAL_LIQUIDITY_MAP = liquidity.build_liquidity_map
_ORIGINAL_BARS_ASOF = entry._bars_asof


class FastRecognitionRuntime:
    """Memoize deterministic as-of computations for one immutable engine."""

    def __init__(self, engine: dealing.MtfDealingRangeEngine):
        self.engine = engine
        self._original_snapshot = engine.snapshot
        self._original_confirmed_pivots = _ORIGINAL_CONFIRMED_PIVOTS
        self._original_imbalance_levels = _ORIGINAL_IMBALANCE_LEVELS
        self._original_liquidity_map = _ORIGINAL_LIQUIDITY_MAP
        self._original_entry_bars_asof = _ORIGINAL_BARS_ASOF

        self._snapshot_cache: dict[tuple[str, datetime], Any] = {}
        self._full_pivot_cache: dict[tuple[str, str, int, int], tuple[Any, ...]] = {}
        self._full_pivot_times: dict[tuple[str, str, int, int], tuple[datetime, ...]] = {}
        self._full_imbalance_cache: dict[tuple[str, str], tuple[Any, ...]] = {}
        self._full_imbalance_times: dict[tuple[str, str], tuple[datetime, ...]] = {}
        self._fallback_pivot_cache: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        self._fallback_imbalance_cache: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        self._liquidity_cache: dict[tuple[str, datetime, tuple[str, ...]], Any] = {}
        self._prefix_cache: dict[tuple[int, str, datetime], tuple[Any, ...]] = {}
        self._series_by_container: dict[int, dict[str, tuple[Any, ...]]] = {}
        self._times_by_container: dict[int, dict[str, tuple[datetime, ...]]] = {}
        self._series_by_key: dict[tuple[str, str], tuple[Any, ...]] = {}
        self._times_by_key: dict[tuple[str, str], tuple[datetime, ...]] = {}
        self.hits: defaultdict[str, int] = defaultdict(int)
        self.misses: defaultdict[str, int] = defaultdict(int)

        for timeframe, rows in engine.bars.items():
            grouped: defaultdict[str, list[Any]] = defaultdict(list)
            for bar in rows:
                grouped[bar.symbol.upper()].append(bar)
            series = {
                symbol: tuple(sorted(values, key=lambda row: row.close_time))
                for symbol, values in grouped.items()
            }
            times = {
                symbol: tuple(row.close_time for row in values)
                for symbol, values in series.items()
            }
            self._series_by_container[id(rows)] = series
            self._times_by_container[id(rows)] = times
            for symbol, values in series.items():
                key = (symbol, timeframe)
                self._series_by_key[key] = values
                self._times_by_key[key] = times[symbol]

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

    def _prefix_identity(self, bars: Sequence[Any]) -> tuple[str, str, datetime] | None:
        if not bars:
            return None
        symbol = str(getattr(bars[0], "symbol", "")).upper()
        timeframe = str(getattr(bars[0], "timeframe", ""))
        full = self._series_by_key.get((symbol, timeframe))
        times = self._times_by_key.get((symbol, timeframe))
        if not full or not times:
            return None
        cutoff = getattr(bars[-1], "close_time", None)
        if not isinstance(cutoff, datetime):
            return None
        end = bisect_right(times, cutoff)
        if end != len(bars):
            return None
        if getattr(bars[0], "close_time", None) != full[0].close_time:
            return None
        return symbol, timeframe, cutoff

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
        identity = self._prefix_identity(bars)
        if identity is not None:
            symbol, timeframe, cutoff = identity
            full_key = (symbol, timeframe, left_bars, right_bars)
            pivots = self._full_pivot_cache.get(full_key)
            if pivots is None:
                full_series = self._series_by_key[(symbol, timeframe)]
                pivots = tuple(self._original_confirmed_pivots(full_series, left_bars, right_bars))
                self._full_pivot_cache[full_key] = pivots
                self._full_pivot_times[full_key] = tuple(pivot.confirmed_at for pivot in pivots)
                self.misses["full_pivots"] += 1
            else:
                self.hits["full_pivots"] += 1
            end = bisect_right(self._full_pivot_times[full_key], cutoff)
            self.hits["pivot_prefix_filter"] += 1
            return list(pivots[:end])

        key = self._bars_key(bars, left_bars, right_bars)
        cached = self._fallback_pivot_cache.get(key)
        if cached is not None:
            self.hits["fallback_pivots"] += 1
            return list(cached)
        value = tuple(self._original_confirmed_pivots(bars, left_bars, right_bars))
        self._fallback_pivot_cache[key] = value
        self.misses["fallback_pivots"] += 1
        return list(value)

    def imbalance_levels(self, bars: Sequence[Any], asof: datetime | None = None) -> list[Any]:
        identity = self._prefix_identity(bars)
        if identity is not None:
            symbol, timeframe, prefix_cutoff = identity
            cutoff = prefix_cutoff if asof is None else min(prefix_cutoff, asof)
            full_key = (symbol, timeframe)
            levels = self._full_imbalance_cache.get(full_key)
            if levels is None:
                full_series = self._series_by_key[full_key]
                levels = tuple(self._original_imbalance_levels(full_series, None))
                self._full_imbalance_cache[full_key] = levels
                self._full_imbalance_times[full_key] = tuple(level.confirmed_at for level in levels)
                self.misses["full_imbalances"] += 1
            else:
                self.hits["full_imbalances"] += 1
            end = bisect_right(self._full_imbalance_times[full_key], cutoff)
            self.hits["imbalance_prefix_filter"] += 1
            return list(levels[:end])

        key = self._bars_key(bars) + (asof,)
        cached = self._fallback_imbalance_cache.get(key)
        if cached is not None:
            self.hits["fallback_imbalances"] += 1
            return list(cached)
        value = tuple(self._original_imbalance_levels(bars, asof))
        self._fallback_imbalance_cache[key] = value
        self.misses["fallback_imbalances"] += 1
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
                "full_pivot_series": len(self._full_pivot_cache),
                "full_imbalance_series": len(self._full_imbalance_cache),
                "fallback_pivots": len(self._fallback_pivot_cache),
                "fallback_imbalances": len(self._fallback_imbalance_cache),
                "liquidity_maps": len(self._liquidity_cache),
                "bar_prefixes": len(self._prefix_cache),
            },
        }


def install_fast_runtime(engine: dealing.MtfDealingRangeEngine) -> FastRecognitionRuntime:
    return FastRecognitionRuntime(engine).install()
