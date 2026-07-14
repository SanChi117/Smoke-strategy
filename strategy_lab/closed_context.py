#!/usr/bin/env python3
"""Completed higher-timeframe context aggregation.

A closed 15m/1h entry candle can still belong to a forming 4h or 1d candle.
This replacement exposes a higher-timeframe bucket only after its final source
bar has closed and every expected source bar is present, preventing unstable
context and historical lookahead.
"""

from __future__ import annotations

from datetime import timedelta
from statistics import median

from strategy_lab import mtf_feature_builder as mtf
from strategy_lab.market_data import Candle


def infer_source_bar_seconds(rows: list[Candle]) -> int:
    ordered = sorted(rows, key=lambda candle: candle.time)
    deltas = [
        int((right.time - left.time).total_seconds())
        for left, right in zip(ordered, ordered[1:])
        if right.time > left.time
    ]
    if not deltas:
        return 15 * 60
    return max(60, int(median(deltas)))


def resample_closed_candles(rows: list[Candle], hours: int) -> list[Candle]:
    ordered = sorted(rows, key=lambda candle: candle.time)
    if not ordered:
        return []
    source_seconds = infer_source_bar_seconds(ordered)
    expected_bars = max(1, round(hours * 3600 / source_seconds))
    buckets: dict[object, list[Candle]] = {}
    for candle in ordered:
        buckets.setdefault(mtf.timeframe_bucket(candle.time, hours), []).append(candle)

    out: list[Candle] = []
    for bucket_start, bucket_rows in sorted(buckets.items(), key=lambda item: item[0]):
        bucket_rows = sorted(bucket_rows, key=lambda candle: candle.time)
        bucket_end = bucket_start + timedelta(hours=hours)
        # Candle.time is the source bar open time. Its values become known only
        # after one source interval has elapsed.
        known_through = bucket_rows[-1].time + timedelta(seconds=source_seconds)
        if known_through < bucket_end:
            continue
        if len(bucket_rows) < expected_bars:
            continue
        # Reject duplicated/gapped source timestamps even when the last bar is
        # present. A full count alone is not enough if the series is malformed.
        expected_times = {
            bucket_start + timedelta(seconds=source_seconds * index)
            for index in range(expected_bars)
        }
        actual_times = {candle.time for candle in bucket_rows}
        if not expected_times.issubset(actual_times):
            continue
        first = bucket_rows[0]
        last = bucket_rows[-1]
        out.append(
            Candle(
                symbol=first.symbol,
                time=last.time,
                open=first.open,
                high=max(candle.high for candle in bucket_rows),
                low=min(candle.low for candle in bucket_rows),
                close=last.close,
                volume=sum(candle.volume for candle in bucket_rows),
            )
        )
    return out


def apply_closed_context_patch() -> None:
    mtf.resample_candles = resample_closed_candles
