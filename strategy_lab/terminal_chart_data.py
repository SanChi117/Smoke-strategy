#!/usr/bin/env python3
"""Causal chart transport helpers for SMOKE Terminal V3.

This module only reshapes already-closed OHLCV candles for visualization. It
never changes strategy decisions and never reads future candles.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

SUPPORTED_TIMEFRAMES: dict[str, int] = {
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}


def _epoch_seconds(value: datetime | str) -> int:
    if not isinstance(value, datetime):
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.astimezone(timezone.utc).timestamp())


def _number(value: Any) -> float:
    return float(value)


def aggregate_ohlcv(candles: Sequence[Any], timeframe: str) -> list[dict[str, float | int]]:
    """Aggregate closed base candles into deterministic UTC buckets."""
    seconds = SUPPORTED_TIMEFRAMES.get(timeframe)
    if seconds is None:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    buckets: dict[int, dict[str, float | int]] = {}
    for candle in sorted(candles, key=lambda row: _epoch_seconds(row.time)):
        epoch = _epoch_seconds(candle.time)
        bucket = epoch - epoch % seconds
        row = buckets.get(bucket)
        if row is None:
            buckets[bucket] = {
                "time": bucket,
                "open": _number(candle.open),
                "high": _number(candle.high),
                "low": _number(candle.low),
                "close": _number(candle.close),
                "volume": _number(getattr(candle, "volume", 0.0)),
            }
            continue
        row["high"] = max(float(row["high"]), _number(candle.high))
        row["low"] = min(float(row["low"]), _number(candle.low))
        row["close"] = _number(candle.close)
        row["volume"] = float(row["volume"]) + _number(getattr(candle, "volume", 0.0))
    return [buckets[key] for key in sorted(buckets)]


def ema_points(rows: Sequence[dict[str, float | int]], length: int) -> list[dict[str, float | int]]:
    """Return standard causal EMA initialized from the first available close."""
    if length <= 0:
        raise ValueError("EMA length must be positive")
    if not rows:
        return []
    alpha = 2.0 / (length + 1.0)
    ema = float(rows[0]["close"])
    output: list[dict[str, float | int]] = [{"time": int(rows[0]["time"]), "value": ema}]
    for row in rows[1:]:
        ema = alpha * float(row["close"]) + (1.0 - alpha) * ema
        output.append({"time": int(row["time"]), "value": ema})
    return output


def chart_bundle(candles: Sequence[Any], timeframe: str, limit: int = 1000) -> dict[str, Any]:
    rows = aggregate_ohlcv(candles, timeframe)
    if limit > 0:
        rows = rows[-limit:]
    return {
        "timeframe": timeframe,
        "candles": rows,
        "ema20": ema_points(rows, 20),
        "ema50": ema_points(rows, 50),
        "ema200": ema_points(rows, 200),
    }


def latest_market_stats(rows: Sequence[dict[str, float | int]]) -> dict[str, float]:
    if not rows:
        return {"last": 0.0, "change_pct": 0.0, "high": 0.0, "low": 0.0, "volume": 0.0}
    window = list(rows[-96:])
    first = float(window[0]["open"])
    last = float(window[-1]["close"])
    return {
        "last": last,
        "change_pct": ((last / first) - 1.0) * 100.0 if first else 0.0,
        "high": max(float(row["high"]) for row in window),
        "low": min(float(row["low"]) for row in window),
        "volume": sum(float(row["volume"]) for row in window),
    }
