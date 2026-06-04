#!/usr/bin/env python3
"""Data quality checks for OHLCV candle datasets.

Checks:
- invalid OHLCV values
- duplicate candles by symbol/time
- minimum history per symbol
- inferred interval per symbol
- missing candle gaps
- per-symbol coverage

Research only. No exchange calls. No live trading.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from statistics import median
from typing import Iterable

from strategy_lab.market_data import Candle, group_candles_by_symbol


@dataclass(frozen=True)
class DataQualityConfig:
    min_candles_per_symbol: int = 100
    max_missing_gap_multiplier: float = 1.5
    min_symbols: int = 1


@dataclass(frozen=True)
class DataQualityIssue:
    level: str
    symbol: str
    check: str
    message: str
    count: int = 1


@dataclass(frozen=True)
class SymbolCoverageRow:
    symbol: str
    candles: int
    start_time: object
    end_time: object
    inferred_interval_seconds: int
    duplicate_candles: int
    missing_gaps: int
    invalid_ohlcv: int
    status: str


@dataclass(frozen=True)
class DataQualitySummary:
    symbols: int
    candles: int
    errors: int
    warnings: int
    duplicate_candles: int
    missing_gaps: int
    invalid_ohlcv: int
    under_min_history_symbols: int
    status: str


def infer_interval_seconds(rows: list[Candle]) -> int:
    if len(rows) < 3:
        return 0
    diffs = []
    for left, right in zip(rows, rows[1:]):
        delta = int((right.time - left.time).total_seconds())
        if delta > 0:
            diffs.append(delta)
    if not diffs:
        return 0
    return int(median(diffs))


def invalid_ohlcv_count(rows: Iterable[Candle]) -> int:
    count = 0
    for candle in rows:
        if candle.open <= 0 or candle.high <= 0 or candle.low <= 0 or candle.close <= 0:
            count += 1
            continue
        if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close):
            count += 1
            continue
        if candle.volume < 0:
            count += 1
    return count


def duplicate_count(rows: Iterable[Candle]) -> int:
    seen: set[tuple[str, object]] = set()
    dupes = 0
    for candle in rows:
        key = (candle.symbol, candle.time)
        if key in seen:
            dupes += 1
        seen.add(key)
    return dupes


def missing_gap_count(rows: list[Candle], interval_seconds: int, gap_multiplier: float) -> int:
    if interval_seconds <= 0 or len(rows) < 2:
        return 0
    threshold = interval_seconds * gap_multiplier
    gaps = 0
    for left, right in zip(rows, rows[1:]):
        delta = (right.time - left.time).total_seconds()
        if delta > threshold:
            gaps += 1
    return gaps


def analyze_data_quality(candles: Iterable[Candle], cfg: DataQualityConfig | None = None) -> tuple[DataQualitySummary, list[SymbolCoverageRow], list[DataQualityIssue]]:
    cfg = cfg or DataQualityConfig()
    rows = sorted(list(candles), key=lambda c: (c.symbol, c.time))
    by_symbol = group_candles_by_symbol(rows)
    issues: list[DataQualityIssue] = []
    coverage: list[SymbolCoverageRow] = []

    if len(by_symbol) < cfg.min_symbols:
        issues.append(DataQualityIssue("error", "ALL", "min_symbols", f"Expected at least {cfg.min_symbols} symbols, got {len(by_symbol)}."))

    total_duplicate = duplicate_count(rows)
    total_invalid = invalid_ohlcv_count(rows)
    total_gaps = 0
    under_min = 0

    for symbol, symbol_rows in by_symbol.items():
        symbol_rows = sorted(symbol_rows, key=lambda c: c.time)
        candles_count = len(symbol_rows)
        interval = infer_interval_seconds(symbol_rows)
        symbol_dupes = duplicate_count(symbol_rows)
        symbol_invalid = invalid_ohlcv_count(symbol_rows)
        symbol_gaps = missing_gap_count(symbol_rows, interval, cfg.max_missing_gap_multiplier)
        total_gaps += symbol_gaps

        if candles_count < cfg.min_candles_per_symbol:
            under_min += 1
            issues.append(DataQualityIssue("warning", symbol, "min_history", f"Only {candles_count} candles, expected at least {cfg.min_candles_per_symbol}."))
        if symbol_dupes > 0:
            issues.append(DataQualityIssue("error", symbol, "duplicate_candles", f"Found {symbol_dupes} duplicate symbol/time candles.", symbol_dupes))
        if symbol_invalid > 0:
            issues.append(DataQualityIssue("error", symbol, "invalid_ohlcv", f"Found {symbol_invalid} invalid OHLCV candles.", symbol_invalid))
        if symbol_gaps > 0:
            issues.append(DataQualityIssue("warning", symbol, "missing_gaps", f"Found {symbol_gaps} gaps larger than expected interval.", symbol_gaps))
        if interval <= 0:
            issues.append(DataQualityIssue("warning", symbol, "interval", "Could not infer candle interval."))

        status = "ERROR" if symbol_dupes or symbol_invalid else "WARN" if candles_count < cfg.min_candles_per_symbol or symbol_gaps or interval <= 0 else "OK"
        coverage.append(SymbolCoverageRow(
            symbol=symbol,
            candles=candles_count,
            start_time=symbol_rows[0].time if symbol_rows else "",
            end_time=symbol_rows[-1].time if symbol_rows else "",
            inferred_interval_seconds=interval,
            duplicate_candles=symbol_dupes,
            missing_gaps=symbol_gaps,
            invalid_ohlcv=symbol_invalid,
            status=status,
        ))

    errors = sum(1 for issue in issues if issue.level == "error")
    warnings = sum(1 for issue in issues if issue.level == "warning")
    status = "FAIL" if errors else "WARN" if warnings else "OK"
    summary = DataQualitySummary(
        symbols=len(by_symbol),
        candles=len(rows),
        errors=errors,
        warnings=warnings,
        duplicate_candles=total_duplicate,
        missing_gaps=total_gaps,
        invalid_ohlcv=total_invalid,
        under_min_history_symbols=under_min,
        status=status,
    )
    return summary, sorted(coverage, key=lambda r: (r.status, r.symbol)), issues


def rows_as_dicts(rows: Iterable[object]) -> list[dict]:
    out = []
    for row in rows:
        item = asdict(row)
        for key in ["start_time", "end_time"]:
            if key in item and hasattr(item[key], "isoformat"):
                item[key] = item[key].isoformat(timespec="seconds")
        out.append(item)
    return out
